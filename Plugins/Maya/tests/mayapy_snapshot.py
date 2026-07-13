"""Headless validation of the Maya plugin via mayapy + maya.standalone.

Loads babylonLivePreview.mll, builds a small scene (cube + light), runs the
`-snapshot` command (which drives MayaCapture -> shared SceneTranslator ->
LivePreviewSession), and asserts the written BMP has plausibly-lit pixels.

Run:
  & "C:\Program Files\Autodesk\Maya2024\bin\mayapy.exe" `
    "E:\Babylon Live preview\BabylonLivePreviewPlugin\Plugins\Maya\tests\mayapy_snapshot.py"
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_MLL_DIR = os.path.join(_REPO, "build", "Plugins", "Maya", "Release")
_MLL = os.path.join(_MLL_DIR, "babylonLivePreview.mll")


def read_bmp_lit(path):
    """Return (width, height, lit_pixel_count) for a 24-bit BMP."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"BM":
        return None
    pixoff = struct.unpack_from("<I", data, 10)[0]
    w = struct.unpack_from("<i", data, 18)[0]
    h = struct.unpack_from("<i", data, 22)[0]
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp != 24:
        return (w, h, -1)
    row = ((w * 3) + 3) & ~3
    lit = 0
    for y in range(abs(h)):
        base = pixoff + y * row
        for x in range(w):
            i = base + x * 3
            b, g, r = data[i], data[i + 1], data[i + 2]
            if r + g + b > 90:
                lit += 1
    return (w, h, lit)


def main():
    # Ensure the Babylon Native / V8 runtime DLLs next to the .mll resolve when
    # the plugin instantiates a session.
    if hasattr(os, "add_dll_directory") and os.path.isdir(_MLL_DIR):
        os.add_dll_directory(_MLL_DIR)
    os.environ["PATH"] = _MLL_DIR + os.pathsep + os.environ.get("PATH", "")

    # Maya's loadPlugin uses a loader that ignores add_dll_directory/PATH for the
    # module's own dependencies (v8.dll, ...). Preload the module via ctypes so
    # it (and its deps) are already resident when Maya loads it by name. For
    # interactive Maya, ship a .mod that extends PATH to the plugin's bin dir.
    import ctypes
    ctypes.WinDLL(_MLL)

    import maya.standalone
    maya.standalone.initialize("Python")
    import maya.cmds as cmds

    print("[mayatest] loading", _MLL)
    cmds.loadPlugin(_MLL)

    # Build a simple scene: a cube lifted up + a directional light.
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(w=2, h=2, d=2)[0]
    cmds.move(0, 1, 0, cube)
    # Give it a standardSurface with a red base color.
    shd = cmds.shadingNode("standardSurface", asShader=True)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True)
    cmds.connectAttr(shd + ".outColor", sg + ".surfaceShader", force=True)
    cmds.setAttr(shd + ".baseColor", 0.9, 0.15, 0.12, type="double3")
    cmds.sets(cube, edit=True, forceElement=sg)
    cmds.directionalLight(rotation=(-35, -25, 0), intensity=1.2)

    out = os.path.join(os.environ.get("TEMP", _HERE), "maya_blp_snapshot.bmp")
    if os.path.exists(out):
        os.remove(out)

    print("[mayatest] running babylonLivePreview -snapshot")
    cmds.babylonLivePreview(snapshot=out, width=320, height=240)

    ok = os.path.exists(out)
    print("[mayatest] snapshot written:", ok, "path:", out)
    result = 1
    if ok:
        info = read_bmp_lit(out)
        print("[mayatest] bmp:", info)
        if info and info[2] > 2000:
            print("[mayatest] PASS (scene rendered with lit pixels)")
            result = 0
        else:
            print("[mayatest] CHECK (few lit pixels)")

    # Exercise the live start/stop path in batch mode: the Render View display
    # must degrade to a no-op (doesRenderEditorExist() == False) without error.
    try:
        cmds.babylonLivePreview(start=True, width=320, height=240)
        print("[mayatest] -start OK (batch: Render View display no-ops)")
        cmds.babylonLivePreview(stop=True)
        print("[mayatest] -stop OK")
    except Exception as exc:
        print("[mayatest] start/stop FAILED:", exc)
        result = 1

    # --- protocol parity: UVs + PBR texture channels via -dumpbuffer ---------
    if verify_textures(cmds) != 0:
        result = 1

    try:
        cmds.unloadPlugin(os.path.basename(_MLL).replace(".mll", ""))
    except Exception as exc:
        print("[mayatest] unload note:", exc)
    maya.standalone.uninitialize()
    return result


def _png_2x2(rgb):
    """A valid 2x2 8-bit RGB PNG (so it renders too, not just decodes as bytes)."""
    import zlib
    w = h = 2
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _walk_buffer(buf):
    """Decode the protocol buffer -> {cmd_type: [records]} (subset of fields)."""
    sys.path.insert(0, os.path.join(_REPO, "Shared", "python"))
    import blp_protocol as blp
    magic, ver, count = struct.unpack_from("<IHH", buf, 0)
    assert magic == blp.MAGIC, "bad magic in dumped buffer"
    off, out = 8, {}
    for _ in range(count):
        (ctype,) = struct.unpack_from("<H", buf, off); off += 2
        rec = {"type": ctype}
        if ctype == blp.CMD_RESET_SCENE:
            pass
        elif ctype == blp.CMD_SET_CLEAR_COLOR:
            off += 16
        elif ctype == blp.CMD_UPSERT_NODE:
            off += 18
            (nlen,) = struct.unpack_from("<H", buf, off); off += 2 + nlen + 40
        elif ctype == blp.CMD_REMOVE_NODE:
            off += 8
        elif ctype == blp.CMD_BIND_NODE_PATH:
            off += 8
            (plen,) = struct.unpack_from("<H", buf, off); off += 2 + plen
        elif ctype == blp.CMD_SET_TRANSFORM:
            off += 48
        elif ctype == blp.CMD_UPSERT_MESH_GEOMETRY:
            (nid, vtx) = struct.unpack_from("<QI", buf, off); off += 12
            (hn, hu) = struct.unpack_from("<BB", buf, off); off += 2
            (idx,) = struct.unpack_from("<I", buf, off); off += 4
            off += vtx * 3 * 4 + (vtx * 3 * 4 if hn else 0) + (vtx * 2 * 4 if hu else 0) + idx * 4
            rec.update(vtx=vtx, idx=idx, has_normals=bool(hn), has_uvs=bool(hu))
        elif ctype == blp.CMD_UPSERT_MATERIAL:
            off += 8 + 40
        elif ctype == blp.CMD_UPSERT_LIGHT:
            off += 10 + 28
        elif ctype == blp.CMD_SET_CAMERA:
            (mode,) = struct.unpack_from("<B", buf, off); off += 1
            off += 24 if mode == 0 else 128
        elif ctype == blp.CMD_UPSERT_MATERIAL_TEXTURE:
            (nid, ch) = struct.unpack_from("<QH", buf, off); off += 10 + 1
            (blen,) = struct.unpack_from("<I", buf, off); off += 4
            data = bytes(buf[off:off + blen]); off += blen
            rec.update(channel=ch, len=blen, data=data)
        else:
            raise AssertionError("unknown cmd %d" % ctype)
        out.setdefault(ctype, []).append(rec)
    return out


def verify_textures(cmds):
    """Build a UV-mapped, fully-textured cube and assert the emitted protocol
    buffer carries UVs and every PBR texture channel (base/MR/normal/emissive)."""
    sys.path.insert(0, os.path.join(_REPO, "Shared", "python"))
    import blp_protocol as blp

    tmp = os.path.join(os.environ.get("TEMP", _HERE), "blp_maya_tex")
    os.makedirs(tmp, exist_ok=True)
    base_png = os.path.join(tmp, "base.png")
    mr_png = os.path.join(tmp, "orm.png")
    nrm_png = os.path.join(tmp, "nrm.png")
    emi_png = os.path.join(tmp, "emi.png")
    for path, rgb in ((base_png, (200, 80, 40)), (mr_png, (30, 200, 60)),
                      (nrm_png, (128, 128, 255)), (emi_png, (240, 240, 60))):
        with open(path, "wb") as f:
            f.write(_png_2x2(rgb))

    cmds.file(new=True, force=True)
    cube = cmds.polyCube(w=2, h=2, d=2)[0]  # polyCube ships a default UV set
    shd = cmds.shadingNode("standardSurface", asShader=True)
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True)
    cmds.connectAttr(shd + ".outColor", sg + ".surfaceShader", force=True)
    cmds.sets(cube, edit=True, forceElement=sg)

    def file_node(path):
        fn = cmds.shadingNode("file", asTexture=True, isColorManaged=True)
        p2d = cmds.shadingNode("place2dTexture", asUtility=True)
        cmds.connectAttr(p2d + ".outUV", fn + ".uvCoord", force=True)
        cmds.setAttr(fn + ".fileTextureName", path, type="string")
        return fn

    base = file_node(base_png)
    cmds.connectAttr(base + ".outColor", shd + ".baseColor", force=True)
    # metalness + specularRoughness driven by the SAME file node -> combined MR.
    mr = file_node(mr_png)
    cmds.connectAttr(mr + ".outAlpha", shd + ".metalness", force=True)
    cmds.connectAttr(mr + ".outAlpha", shd + ".specularRoughness", force=True)
    # normal via bump2d (tangent-space normal map).
    nrm = file_node(nrm_png)
    bump = cmds.shadingNode("bump2d", asUtility=True)
    cmds.setAttr(bump + ".bumpInterp", 1)  # tangent-space normals
    cmds.connectAttr(nrm + ".outAlpha", bump + ".bumpValue", force=True)
    cmds.connectAttr(bump + ".outNormal", shd + ".normalCamera", force=True)
    # emissive.
    emi = file_node(emi_png)
    cmds.connectAttr(emi + ".outColor", shd + ".emissionColor", force=True)
    cmds.setAttr(shd + ".emission", 1.0)

    out = os.path.join(tmp, "buffer.bin")
    if os.path.exists(out):
        os.remove(out)
    cmds.babylonLivePreview(dumpbuffer=out)
    if not os.path.exists(out):
        print("[mayatest] TEX FAIL: no buffer dumped")
        return 1

    with open(out, "rb") as f:
        cmds_map = _walk_buffer(f.read())

    failures = 0

    def check(cond, msg):
        nonlocal failures
        print(("  ok:   " if cond else "  FAIL: ") + msg)
        if not cond:
            failures += 1

    geo = cmds_map.get(blp.CMD_UPSERT_MESH_GEOMETRY, [])
    check(any(g["has_uvs"] for g in geo), "mesh geometry carries UVs")
    check(any(g["has_normals"] for g in geo), "mesh geometry carries normals")

    texs = {r["channel"] for r in cmds_map.get(blp.CMD_UPSERT_MATERIAL_TEXTURE, [])}
    check(blp.TEX_BASECOLOR in texs, "base-color texture channel emitted")
    check(blp.TEX_METALROUGH in texs, "combined metallic-roughness channel emitted")
    check(blp.TEX_NORMAL in texs, "normal texture channel emitted")
    check(blp.TEX_EMISSIVE in texs, "emissive texture channel emitted")

    print("[mayatest] texture parity:", "PASS" if failures == 0 else "%d FAIL" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
