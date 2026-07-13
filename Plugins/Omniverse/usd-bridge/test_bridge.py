"""Validate the USD bridge: build_snapshot + build_delta against sample.usda.

Pure (no WebSocket): decodes the emitted command buffers and asserts the scene
and a transform delta. Run:
    python Plugins/Omniverse/usd-bridge/test_bridge.py
"""

import os
import struct
import sys
import tempfile

from pxr import Sdf, Usd, UsdGeom, UsdShade

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", "Shared", "python"))

import bridge as bridgemod  # noqa: E402
import blp_protocol as blp  # noqa: E402


def walk(buf):
    """Return {cmd_type: [records]}; each record is a dict with a few fields."""
    magic, ver, count = struct.unpack_from("<IHH", buf, 0)
    assert magic == blp.MAGIC, "bad magic"
    off = 8
    out = {}
    for _ in range(count):
        (ctype,) = struct.unpack_from("<H", buf, off); off += 2
        rec = {"type": ctype}
        if ctype == blp.CMD_RESET_SCENE:
            pass
        elif ctype == blp.CMD_SET_CLEAR_COLOR:
            off += 16
        elif ctype == blp.CMD_UPSERT_NODE:
            (nid, pid, kind) = struct.unpack_from("<QQH", buf, off); off += 18
            (nlen,) = struct.unpack_from("<H", buf, off); off += 2
            name = buf[off:off + nlen].decode("utf-8"); off += nlen
            trs = struct.unpack_from("<10f", buf, off); off += 40
            rec.update(id=nid, name=name, pos=trs[0:3])
        elif ctype == blp.CMD_REMOVE_NODE:
            (nid,) = struct.unpack_from("<Q", buf, off); off += 8
            rec["id"] = nid
        elif ctype == blp.CMD_SET_TRANSFORM:
            (nid,) = struct.unpack_from("<Q", buf, off); off += 8
            trs = struct.unpack_from("<10f", buf, off); off += 40
            rec.update(id=nid, pos=trs[0:3])
        elif ctype == blp.CMD_UPSERT_MESH_GEOMETRY:
            (nid, vtx) = struct.unpack_from("<QI", buf, off); off += 12
            (hn, hu) = struct.unpack_from("<BB", buf, off); off += 2
            (idx,) = struct.unpack_from("<I", buf, off); off += 4
            off += vtx * 3 * 4
            if hn:
                off += vtx * 3 * 4
            if hu:
                off += vtx * 2 * 4
            off += idx * 4
            rec.update(id=nid, vtx=vtx, idx=idx, has_normals=bool(hn), has_uvs=bool(hu))
        elif ctype == blp.CMD_UPSERT_MATERIAL:
            (nid,) = struct.unpack_from("<Q", buf, off); off += 8
            vals = struct.unpack_from("<10f", buf, off); off += 40
            rec.update(id=nid, rgba=vals[0:4], metallic=vals[4], roughness=vals[5],
                       emissive=vals[6:9], emissive_strength=vals[9])
        elif ctype == blp.CMD_UPSERT_LIGHT:
            (nid, lt) = struct.unpack_from("<QH", buf, off); off += 10
            off += 28
            rec.update(id=nid, light_type=lt)
        elif ctype == blp.CMD_SET_CAMERA:
            (mode,) = struct.unpack_from("<B", buf, off); off += 1
            off += 24 if mode == 0 else 128
            rec["mode"] = mode
        elif ctype == blp.CMD_UPSERT_MATERIAL_TEXTURE:
            (nid, ch) = struct.unpack_from("<QH", buf, off); off += 10
            (enc,) = struct.unpack_from("<B", buf, off); off += 1
            (blen,) = struct.unpack_from("<I", buf, off); off += 4
            data = bytes(buf[off:off + blen]); off += blen
            rec.update(id=nid, channel=ch, len=blen, data=data)
        elif ctype == blp.CMD_BIND_NODE_PATH:
            (nid,) = struct.unpack_from("<Q", buf, off); off += 8
            (plen,) = struct.unpack_from("<H", buf, off); off += 2
            path = buf[off:off + plen].decode("utf-8"); off += plen
            rec.update(id=nid, path=path)
        else:
            raise AssertionError("unknown cmd %d" % ctype)
        out.setdefault(ctype, []).append(rec)
    return out


def main():
    failures = 0

    def check(cond, msg):
        nonlocal failures
        if cond:
            print("  ok:   " + msg)
        else:
            print("  FAIL: " + msg)
            failures += 1

    stage = Usd.Stage.Open(os.path.join(_HERE, "sample.usda"))
    assert stage is not None, "failed to open sample.usda"
    bridge = bridgemod.UsdBridge(stage)

    snap = walk(bridge.build_snapshot())
    print("[usdtest] snapshot commands:", {k: len(v) for k, v in snap.items()})
    check(len(snap.get(blp.CMD_RESET_SCENE, [])) == 1, "ResetScene emitted")
    check(len(snap.get(blp.CMD_UPSERT_NODE, [])) == 2, "two mesh nodes (Cube + Ground)")
    check(len(snap.get(blp.CMD_UPSERT_MESH_GEOMETRY, [])) == 2, "two geometries")
    check(len(snap.get(blp.CMD_UPSERT_MATERIAL, [])) == 2, "two materials")
    check(len(snap.get(blp.CMD_UPSERT_LIGHT, [])) == 1, "one directional light")
    check(len(snap.get(blp.CMD_SET_CAMERA, [])) == 1, "one camera")

    lights = snap.get(blp.CMD_UPSERT_LIGHT, [])
    check(lights and lights[0]["light_type"] == blp.LIGHT_DIRECTIONAL, "light is directional")

    # The Cube is translated (0,1,0) in USD (Y-up) -> Babylon (0,1,0).
    cube_node = next((r for r in snap[blp.CMD_UPSERT_NODE] if r["name"] == "Cube"), None)
    check(cube_node is not None and abs(cube_node["pos"][1] - 1.0) < 1e-4,
          "Cube node at y=1 (%s)" % (str(cube_node["pos"]) if cube_node else None))

    # Geometry sanity: cube has 8 verts, 36 tri-indices (12 tris); ground 4 verts, 6 indices.
    geos = {r["vtx"]: r for r in snap[blp.CMD_UPSERT_MESH_GEOMETRY]}
    check(8 in geos and geos[8]["idx"] == 36, "cube geometry: 8 verts, 36 indices")
    check(4 in geos and geos[4]["idx"] == 6, "ground geometry: 4 verts, 6 indices")

    # Cube binds a UsdPreviewSurface -> PBR scalars flow through; Ground uses the
    # displayColor fallback.
    mats = {r["id"]: r for r in snap[blp.CMD_UPSERT_MATERIAL]}
    cube_mat = mats.get(cube_node["id"]) if cube_node else None
    check(cube_mat is not None and abs(cube_mat["metallic"] - 0.9) < 1e-4,
          "cube material metallic=0.9 (%s)" % (cube_mat["metallic"] if cube_mat else None))
    check(cube_mat is not None and abs(cube_mat["roughness"] - 0.15) < 1e-4,
          "cube material roughness=0.15 (%s)" % (cube_mat["roughness"] if cube_mat else None))
    check(cube_mat is not None and abs(cube_mat["rgba"][0] - 0.90) < 1e-4
          and abs(cube_mat["rgba"][1] - 0.35) < 1e-4,
          "cube diffuseColor -> base rgba (%s)" % (str(cube_mat["rgba"]) if cube_mat else None))
    check(cube_mat is not None and cube_mat["emissive_strength"] > 0.0
          and cube_mat["emissive"][0] > 0.0,
          "cube emissiveColor emitted with strength (%s)"
          % (str(cube_mat["emissive"]) if cube_mat else None))

    # --- baked snapshot: bind pre-loaded glTF nodes by path, no geometry, no reset ---
    baked = walk(bridge.build_snapshot_baked())
    print("[usdtest] baked snapshot commands:", {k: len(v) for k, v in baked.items()})
    check(len(baked.get(blp.CMD_BIND_NODE_PATH, [])) == 2, "two BindNodePath (Cube + Ground)")
    check(len(baked.get(blp.CMD_UPSERT_MESH_GEOMETRY, [])) == 0, "no geometry streamed in baked mode")
    check(len(baked.get(blp.CMD_RESET_SCENE, [])) == 0, "no ResetScene in baked mode (keeps glTF)")
    check(len(baked.get(blp.CMD_SET_CAMERA, [])) == 1, "baked snapshot has a camera")
    binds = {r["path"] for r in baked.get(blp.CMD_BIND_NODE_PATH, [])}
    check(binds == {"/World/Cube", "/World/Ground"}, "binds by PrimPath: %s" % sorted(binds))

    # --- change delta: move the cube in Z and re-read ---
    cube = stage.GetPrimAtPath("/World/Cube")
    xf = UsdGeom.Xformable(cube)
    xf.GetOrderedXformOps()[0].Set((2.0, 1.0, 3.0))  # translate to (2,1,3)

    delta = bridge.build_delta([cube.GetPath()])
    check(delta is not None, "delta produced after edit")
    if delta:
        d = walk(delta)
        st = d.get(blp.CMD_SET_TRANSFORM, [])
        check(len(st) == 1, "one SetTransform in delta")
        # USD (2,1,3) Y-up -> Babylon (2,1,-3).
        check(st and abs(st[0]["pos"][0] - 2.0) < 1e-4 and abs(st[0]["pos"][2] + 3.0) < 1e-4,
              "SetTransform position basis-converted to (2,1,-3): %s" % (str(st[0]["pos"]) if st else None))

    # Baked delta keeps glTF space (raw USD), matching the baked node's frame.
    baked_delta = bridge.build_delta([cube.GetPath()], baked=True)
    if baked_delta:
        bd = walk(baked_delta)
        bst = bd.get(blp.CMD_SET_TRANSFORM, [])
        check(bst and abs(bst[0]["pos"][0] - 2.0) < 1e-4 and abs(bst[0]["pos"][2] - 3.0) < 1e-4,
              "baked SetTransform keeps USD space (2,1,3): %s" % (str(bst[0]["pos"]) if bst else None))

    check_normals_uvs_textures(check)

    if failures == 0:
        print("[usdtest] ALL PASS")
        return 0
    print("[usdtest] %d FAILURE(S)" % failures)
    return 1


def check_normals_uvs_textures(check):
    """In-memory stage exercising authored normals + UVs (faceVarying) and a
    fully-textured UsdPreviewSurface (base/normal/emissive + combined ORM)."""
    tmp = tempfile.mkdtemp(prefix="blp_usdtex_")
    base_png = _write(os.path.join(tmp, "base.png"), b"\x89PNG-base-color")
    orm_png = _write(os.path.join(tmp, "orm.png"), b"\x89PNG-metal-rough")
    nrm_png = _write(os.path.join(tmp, "nrm.png"), b"\x89PNG-normal-map")
    emi_png = _write(os.path.join(tmp, "emi.png"), b"\x89PNG-emissive")

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    mesh = UsdGeom.Mesh.Define(stage, "/World/Quad")
    mesh.CreatePointsAttr([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.CreateNormalsAttr([(0, 1, 0)] * 4)
    mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)
    st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying)
    st.Set([(0, 0), (1, 0), (1, 1), (0, 1)])

    surf = UsdShade.Shader.Define(stage, "/World/Looks/M/Surface")
    surf.CreateIdAttr("UsdPreviewSurface")
    surf.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set((1, 1, 1))
    surf.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(1.0)
    surf.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(1.0)
    surf.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set((1, 1, 1))
    surf.CreateInput("normal", Sdf.ValueTypeNames.Normal3f)
    surf_out = surf.CreateOutput("surface", Sdf.ValueTypeNames.Token)

    def texture(path, name, out_names):
        tex = UsdShade.Shader.Define(stage, "/World/Looks/M/" + name)
        tex.CreateIdAttr("UsdUVTexture")
        tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(path)
        return {n: tex.CreateOutput(n, Sdf.ValueTypeNames.Float3) for n in out_names}

    base = texture(base_png, "BaseTex", ["rgb"])
    orm = texture(orm_png, "OrmTex", ["g", "b"])
    nrm = texture(nrm_png, "NrmTex", ["rgb"])
    emi = texture(emi_png, "EmiTex", ["rgb"])
    surf.GetInput("diffuseColor").ConnectToSource(base["rgb"])
    surf.GetInput("metallic").ConnectToSource(orm["b"])
    surf.GetInput("roughness").ConnectToSource(orm["g"])
    surf.GetInput("normal").ConnectToSource(nrm["rgb"])
    surf.GetInput("emissiveColor").ConnectToSource(emi["rgb"])

    mat = UsdShade.Material.Define(stage, "/World/Looks/M")
    mat.CreateSurfaceOutput().ConnectToSource(surf_out)
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)

    snap = walk(bridgemod.UsdBridge(stage).build_snapshot())
    geo = snap.get(blp.CMD_UPSERT_MESH_GEOMETRY, [])
    check(len(geo) == 1 and geo[0]["has_normals"] and geo[0]["has_uvs"],
          "quad geometry carries authored normals + UVs")
    check(geo and geo[0]["vtx"] == 4 and geo[0]["idx"] == 6,
          "faceVarying quad expanded to 4 corner verts, 6 indices (%s)"
          % (str((geo[0]["vtx"], geo[0]["idx"])) if geo else None))

    texs = {r["channel"]: r for r in snap.get(blp.CMD_UPSERT_MATERIAL_TEXTURE, [])}
    check(blp.TEX_BASECOLOR in texs and texs[blp.TEX_BASECOLOR]["data"] == b"\x89PNG-base-color",
          "base-color texture bytes streamed")
    check(blp.TEX_METALROUGH in texs and texs[blp.TEX_METALROUGH]["data"] == b"\x89PNG-metal-rough",
          "combined metallic-roughness texture (shared file) streamed")
    check(blp.TEX_NORMAL in texs and texs[blp.TEX_NORMAL]["data"] == b"\x89PNG-normal-map",
          "normal texture bytes streamed")
    check(blp.TEX_EMISSIVE in texs and texs[blp.TEX_EMISSIVE]["data"] == b"\x89PNG-emissive",
          "emissive texture bytes streamed")


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return path


if __name__ == "__main__":
    sys.exit(main())
