"""Probe the readback pixel format: channel order (RGBA vs BGRA) and gamma.

    python Plugins/Blender/tests/run_format_probe.py

Renders unlit emissive-ish flat quads of known colors filling the view and reads
back the center pixel, so we can tell if R/B are swapped and whether values are
linear or sRGB-encoded.
"""

import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import bridge   # noqa: E402


def default_dll():
    # Cross-platform: resolve the built native module (.dll/.dylib/.so) across
    # multi-config (Windows) and single-config (macOS/Linux) build trees.
    return bridge.default_build_library(_REPO)


def center(b):
    b.request_readback()
    for _ in range(400):
        b.render_frame()
        r = b.try_acquire_readback()
        if r:
            data, w, h = r
            i = (h // 2 * w + w // 2) * 4
            return [data[i], data[i + 1], data[i + 2], data[i + 3]]
        time.sleep(0.008)
    return None


def set_clear_and_read(b, r, g, bl, label):
    # Fill the whole frame with a known clear color; disable tone mapping so we
    # read the value straight through, then re-read center.
    b.eval(
        "(function(){var s=currentScene;"
        "s.imageProcessingConfiguration.toneMappingEnabled=false;"
        "s.imageProcessingConfiguration.exposure=1;s.imageProcessingConfiguration.contrast=1;"
        "while(s.meshes.length){s.meshes[0].dispose();}"
        "s.clearColor=new BABYLON.Color4(%f,%f,%f,1);"
        "})()" % (r, g, bl))
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    px = center(b)
    print("[fmt] clear(%.2f,%.2f,%.2f) -> readback %s   [%s]" % (r, g, bl, px, label))
    return px


def main():
    dll = default_dll()
    b = bridge.BabylonBridge(dll)
    if not b.create(320, 240, os.path.join(os.path.dirname(dll), "Scripts")):
        print("[fmt] FAILED: blp_create")
        return 2
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    # Pure red in the RED channel: if readback[0] is high -> RGBA; if readback[2] high -> BGRA
    red = set_clear_and_read(b, 1.0, 0.0, 0.0, "pure red input")
    blue = set_clear_and_read(b, 0.0, 0.0, 1.0, "pure blue input")
    # Mid gray 0.5 linear: sRGB-encoded ~188, linear ~128 -> tells us gamma
    gray = set_clear_and_read(b, 0.5, 0.5, 0.5, "linear 0.5 gray (clearColor)")

    # Now test a MESH of known color. An "unlit" PBR material outputs baseColor
    # straight through image processing (gamma), so baseColor 0.5 tells us if the
    # mesh path is sRGB-encoded (~188) while the background is linear (~127).
    b.eval(
        "(function(){var s=currentScene;"
        "s.clearColor=new BABYLON.Color4(0,0,0,1);"
        "var m=BABYLON.MeshBuilder.CreateSphere('probe',{diameter:4},s);"
        "var mat=new BABYLON.PBRMetallicRoughnessMaterial('pm',s);"
        "mat.unlit=true;mat.baseColor=new BABYLON.Color3(0.5,0.5,0.5);"
        "m.material=mat;s.activeCamera.setTarget(BABYLON.Vector3.Zero());s.activeCamera.radius=6;"
        "})()")
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    mesh = center(b)
    print("[fmt] unlit mesh baseColor 0.5 -> readback %s" % mesh)

    print("--- ANALYSIS ---")
    if red:
        if red[0] > red[2] + 40:
            print("[fmt] channel order: RGBA (red in [0])")
        elif red[2] > red[0] + 40:
            print("[fmt] channel order: BGRA (red in [2]) <-- SWAP NEEDED")
        else:
            print("[fmt] channel order: ambiguous %s" % red)
    for label, px in (("clearColor bg", gray), ("emissive mesh", mesh)):
        if px:
            g = px[0]
            kind = ("sRGB-encoded" if g > 170 else "LINEAR" if g < 145 else "in-between")
            print("[fmt] %s: 0.5 -> %d  (%s)" % (label, g, kind))
    b.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
