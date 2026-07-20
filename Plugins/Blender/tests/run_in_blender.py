"""In-Blender headless harness for the Babylon Live Preview capture path.

Run it from Blender (no GUI needed):

    blender --background --python Plugins/Blender/tests/run_in_blender.py

It uses the add-on's capture.build_scene_snapshot() on Blender's default scene
(cube + light + camera), drives the C-API DLL through bridge.py, reads a frame
back, and writes `blender_capture.bmp` next to the DLL. This validates the
bpy -> protocol -> Babylon Native path that the live add-on relies on, including
the parts that need real bpy data (mesh extraction, materials, camera).

Babylon Native creates its own D3D11 device + hidden window, so this works even
in Blender's background mode.
"""

import os
import struct
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import bridge   # noqa: E402
import capture  # noqa: E402


def default_dll():
    # Cross-platform: resolve the built native module (.dll/.dylib/.so) across
    # multi-config (Windows) and single-config (macOS/Linux) build trees.
    return bridge.default_build_library(_REPO)


def write_bmp(path, rgba, w, h):
    row = ((w * 3) + 3) & ~3
    img = row * h
    with open(path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<IHHI", 54 + img, 0, 0, 54))
        f.write(struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, img, 0, 0, 0, 0))
        for y in range(h - 1, -1, -1):
            line = bytearray(row)
            for x in range(w):
                i = (y * w + x) * 4
                line[x * 3 + 0] = rgba[i + 2]
                line[x * 3 + 1] = rgba[i + 1]
                line[x * 3 + 2] = rgba[i + 0]
            f.write(bytes(line))


def main():
    dll = default_dll()
    print("[in-blender] DLL:", dll)
    b = bridge.BabylonBridge(dll)
    scripts_root = os.path.join(os.path.dirname(dll), "Scripts")
    if not b.create(1280, 720, scripts_root):
        print("[in-blender] FAILED: blp_create")
        return 2

    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)
    print("[in-blender] ready:", b.is_ready())

    # Capture Blender's current scene (default startup: cube + light + camera).
    buf = capture.build_scene_snapshot(bpy.context)
    print("[in-blender] snapshot: %d bytes" % len(buf))
    b.submit_commands(buf)

    for _ in range(30):
        b.render_frame()
        time.sleep(0.01)

    b.request_readback()
    result = None
    for _ in range(600):
        b.render_frame()
        result = b.try_acquire_readback()
        if result:
            break
        time.sleep(0.008)

    if not result:
        print("[in-blender] FAILED: no readback")
        b.destroy()
        return 3

    data, w, h = result
    lit = sum(1 for i in range(0, len(data) - 3, 4)
              if data[i] + data[i + 1] + data[i + 2] > 90)
    out = os.path.join(os.path.dirname(dll), "blender_capture.bmp")
    write_bmp(out, data, w, h)
    print("[in-blender] readback %dx%d, lit pixels=%d, wrote %s" % (w, h, lit, out))
    b.destroy()
    # The default cube should occupy a meaningful chunk of the frame.
    print("[in-blender] %s" % ("PASS" if lit > 5000 else "CHECK (few lit pixels)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
