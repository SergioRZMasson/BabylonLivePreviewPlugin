"""Visual verification that the default environment (IBL) is lighting materials.

    python Plugins/Blender/tests/run_env_visual.py

Builds a scene with a single PURE METALLIC (metallic=1) box and NO analytic
light. A pure-metal PBR material has no diffuse response, so it can only be lit
by the environment (image-based reflections). If the box region is bright, IBL
is working. Writes env_metallic.bmp for a visual check.
"""

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
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
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
    dll = default_dll()
    b = bridge.BabylonBridge(dll)
    if not b.create(800, 600, os.path.join(os.path.dirname(dll), "Scripts")):
        print("[env] FAILED: blp_create")
        return 2
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    pos, nrm, idx = make_box(2.5)
    enc = capture.CommandEncoder()
    enc.reset_scene()
    enc.set_clear_color((0.02, 0.02, 0.03, 1.0))
    enc.set_camera_arcrotate(-math.pi / 2 + 0.6, 1.2, 6.0, (0.0, 0.0, 0.0))
    # NOTE: deliberately NO light. A pure metal is lit only by the environment.
    enc.upsert_node(1, 0, capture.KIND_MESH, "metalBox",
                    (0, 0, 0), (0, 0, 0, 1), (1, 1, 1))
    enc.upsert_mesh_geometry(1, pos, nrm, None, idx)
    enc.upsert_material(1, (0.95, 0.95, 0.95, 1.0), 1.0, 0.25)  # metallic=1, smooth
    b.submit_commands(enc.finish())

    for _ in range(40):
        b.render_frame(); time.sleep(0.01)

    b.request_readback()
    result = None
    for _ in range(600):
        b.render_frame()
        result = b.try_acquire_readback()
        if result:
            break
        time.sleep(0.008)
    if not result:
        print("[env] FAILED: no readback")
        return 3

    data, w, h = result
    # Measure the lit metal region: brightness + color variance (reflections).
    lit = 0
    total = 0
    vals = []
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            i = (y * w + x) * 4
            lum = data[i] + data[i + 1] + data[i + 2]
            if lum > 60:
                lit += 1
                total += lum
                vals.append(lum)
    avg = (total / lit) if lit else 0
    # variance of luminance across the metal (reflections => non-uniform)
    var = 0
    if vals:
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / len(vals)
    print("[env] metallic box: lit=%d avg_lum=%.0f var=%.0f" % (lit, avg, var))

    write_bmp(os.path.join(os.path.dirname(dll), "env_metallic.bmp"), data, w, h)
    print("[env] wrote env_metallic.bmp")
    b.destroy()

    # A pure metal with no analytic light is only visible via the environment.
    ok = lit > 3000 and avg > 90 and var > 100
    print("[env] %s (IBL %s)" % ("PASS" if ok else "FAIL",
                                  "lighting the metal" if ok else "NOT working"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
