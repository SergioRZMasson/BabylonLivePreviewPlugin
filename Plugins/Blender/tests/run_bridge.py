"""Standalone harness for the Babylon Live Preview Blender bridge.

Runs WITHOUT Blender: it loads the same ctypes bridge (bridge.py) and protocol
encoder (capture.py) the add-on uses, drives the C-API DLL to build a scene and
read a frame back, then writes/validates a BMP. This proves the entire
Python -> C-API -> Babylon Native path that the Blender add-on relies on.

Usage:
    python run_bridge.py [path\\to\\babylon_live_preview.dll]

If no DLL path is given, the default Release build location is used.
"""

import ctypes
import math
import os
import struct
import sys
import time

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


def make_box(size):
    h = size * 0.5
    faces = [
        ((1, 0, 0), [(h, -h, -h), (h, h, -h), (h, h, h), (h, -h, h)]),
        ((-1, 0, 0), [(-h, -h, h), (-h, h, h), (-h, h, -h), (-h, -h, -h)]),
        ((0, 1, 0), [(-h, h, -h), (-h, h, h), (h, h, h), (h, h, -h)]),
        ((0, -1, 0), [(-h, -h, h), (-h, -h, -h), (h, -h, -h), (h, -h, h)]),
        ((0, 0, 1), [(h, -h, h), (h, h, h), (-h, h, h), (-h, -h, h)]),
        ((0, 0, -1), [(-h, -h, -h), (-h, h, -h), (h, h, -h), (h, -h, -h)]),
    ]
    positions, normals, indices = [], [], []
    for n, verts in faces:
        base = len(positions) // 3
        for v in verts:
            positions += [v[0], v[1], v[2]]
            normals += [n[0], n[1], n[2]]
        indices += [base + 0, base + 1, base + 2, base + 0, base + 2, base + 3]
    return positions, normals, indices


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
    dll = sys.argv[1] if len(sys.argv) > 1 else default_dll()
    print("[bridge] DLL:", dll)

    b = bridge.BabylonBridge(dll)
    scripts_root = os.path.join(os.path.dirname(dll), "Scripts")
    if not b.create(1280, 720, scripts_root):
        print("[bridge] FAILED: blp_create returned null")
        return 2

    # Wait for the JS engine + first frame.
    ready = False
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            ready = True
            break
        time.sleep(0.01)
    if not ready:
        print("[bridge] FAILED: not ready")
        b.destroy()
        return 3
    print("[bridge] session ready")

    # Build a red-box / green-box scene through the protocol encoder.
    pos, nrm, idx = make_box(1.4)
    enc = capture.CommandEncoder()
    enc.reset_scene()
    enc.set_clear_color((0.05, 0.06, 0.12, 1.0))
    enc.set_camera_arcrotate(-math.pi / 2, 1.15, 9.0, (0.0, 0.5, 0.0))
    enc.upsert_light(100, capture.LIGHT_HEMISPHERIC, (0.3, 1.0, 0.2), (1.0, 1.0, 1.0), 1.2)

    enc.upsert_node(1, 0, capture.KIND_MESH, "leftBox",
                    (-2.0, 0.5, 0.0), (0, 0, 0, 1), (1, 1, 1))
    enc.upsert_mesh_geometry(1, pos, nrm, None, idx)
    enc.upsert_material(1, (0.90, 0.08, 0.08, 1.0), 0.0, 0.6)

    enc.upsert_node(2, 0, capture.KIND_MESH, "rightBox",
                    (2.0, 0.5, 0.0), (0, 0, 0, 1), (1, 1, 1))
    enc.upsert_mesh_geometry(2, pos, nrm, None, idx)
    enc.upsert_material(2, (0.08, 0.80, 0.10, 1.0), 0.0, 0.6)

    buf = enc.finish()
    print("[bridge] submitting %d-byte command buffer" % len(buf))
    b.submit_commands(buf)

    for _ in range(30):
        b.render_frame()
        time.sleep(0.01)

    b.request_readback()
    result = None
    for _ in range(600):
        b.render_frame()
        result = b.try_acquire_readback()
        if result is not None:
            break
        time.sleep(0.008)

    if result is None:
        print("[bridge] FAILED: no readback")
        b.destroy()
        return 4

    data, w, h = result
    red = green = bg = 0
    for i in range(0, len(data) - 3, 4):
        r, g, bl = data[i], data[i + 1], data[i + 2]
        if r > g + 30 and r > bl + 30:
            red += 1
        elif g > r + 30 and g > bl + 30:
            green += 1
        elif bl >= r and bl > g and r < 60 and g < 60:
            bg += 1
    print("[bridge] readback %dx%d  red=%d green=%d background=%d" % (w, h, red, green, bg))

    out = os.path.join(os.path.dirname(dll), "bridge_scene.bmp")
    write_bmp(out, data, w, h)
    print("[bridge] wrote", out)

    b.destroy()

    ok = red > 1500 and green > 1500 and bg > 10000
    print("[bridge] %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
