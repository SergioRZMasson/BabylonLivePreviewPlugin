"""Validate the USD bridge: build_snapshot + build_delta against sample.usda.

Pure (no WebSocket): decodes the emitted command buffers and asserts the scene
and a transform delta. Run:
    python Servers/usd-bridge/test_bridge.py
"""

import os
import struct
import sys

from pxr import Usd, UsdGeom

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "..", "Shared", "python"))

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
            rec.update(id=nid, vtx=vtx, idx=idx)
        elif ctype == blp.CMD_UPSERT_MATERIAL:
            (nid,) = struct.unpack_from("<Q", buf, off); off += 8
            off += 48 - 8
            rec["id"] = nid
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
            off += 1
            (blen,) = struct.unpack_from("<I", buf, off); off += 4
            off += blen
            rec.update(id=nid, channel=ch, len=blen)
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

    if failures == 0:
        print("[usdtest] ALL PASS")
        return 0
    print("[usdtest] %d FAILURE(S)" % failures)
    return 1


if __name__ == "__main__":
    sys.exit(main())
