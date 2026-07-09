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

    try:
        cmds.unloadPlugin(os.path.basename(_MLL).replace(".mll", ""))
    except Exception as exc:
        print("[mayatest] unload note:", exc)
    maya.standalone.uninitialize()
    return result


if __name__ == "__main__":
    sys.exit(main())
