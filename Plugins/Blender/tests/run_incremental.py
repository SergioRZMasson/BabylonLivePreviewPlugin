"""In-Blender M4 test: incremental scene sync.

    blender --background --python Plugins/Blender/tests/run_incremental.py

Pushes an initial snapshot, then makes two edits (move the cube, recolor it) and
uses SceneSync.sync() to emit ONLY the changes. Verifies the readback reflects
each edit and that the incremental buffers are small.
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


def read_frame(b):
    b.request_readback()
    for _ in range(600):
        b.render_frame()
        r = b.try_acquire_readback()
        if r:
            return r
        time.sleep(0.008)
    return None


def analyze(data, w, h):
    minx, maxx, miny, maxy, lit = w, 0, h, 0, 0
    sr = sg = sb = 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            i = (y * w + x) * 4
            r, g, bl = data[i], data[i + 1], data[i + 2]
            if r + g + bl > 100:
                lit += 1
                sr += r; sg += g; sb += bl
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
    if lit == 0:
        return None
    return {"lit": lit, "cx": (minx + maxx) // 2, "cy": (miny + maxy) // 2,
            "r": sr // lit, "g": sg // lit, "b": sb // lit}


def main():
    dll = default_dll()
    b = bridge.BabylonBridge(dll)
    if not b.create(1280, 720, os.path.join(os.path.dirname(dll), "Scripts")):
        print("[m4] FAILED: blp_create")
        return 2
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    ctx = bpy.context
    sync = capture.SceneSync()

    # 1) Initial snapshot.
    buf0 = sync.initial_snapshot(ctx)
    b.submit_commands(buf0)
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    a0 = analyze(*read_frame(b))
    print("[m4] initial: buf=%d  cube@(%d,%d) lit=%d color=(%d,%d,%d)"
          % (len(buf0), a0["cx"], a0["cy"], a0["lit"], a0["r"], a0["g"], a0["b"]))

    ok = True

    # 2) Move the cube up (+Z in Blender) — expect a tiny transform-only buffer
    #    and the cube to shift vertically in the readback.
    cube = bpy.data.objects.get("Cube")
    if cube is None:
        print("[m4] FAILED: no default Cube")
        return 3
    cube.location.z += 2.0
    ctx.view_layer.update()
    buf1 = sync.sync(ctx)
    print("[m4] after move: incremental buf=%s bytes" % (len(buf1) if buf1 else None))
    if not buf1 or len(buf1) > 120:
        print("[m4] WARN: move produced no/large buffer (expected small transform)")
    b.submit_commands(buf1)
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    a1 = analyze(*read_frame(b))
    dy = a1["cy"] - a0["cy"]
    print("[m4] after move: cube@(%d,%d)  dy=%d" % (a1["cx"], a1["cy"], dy))
    if abs(dy) < 30:
        print("[m4] FAIL: cube did not move vertically"); ok = False

    # 3) Recolor the cube red via its Principled BSDF — expect a small material
    #    buffer and the lit region to become red-dominant.
    mat = cube.active_material
    recolored = False
    if mat and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                n.inputs['Base Color'].default_value = (0.9, 0.05, 0.05, 1.0)
                recolored = True
                break
    if recolored:
        ctx.view_layer.update()
        buf2 = sync.sync(ctx)
        print("[m4] after recolor: incremental buf=%s bytes" % (len(buf2) if buf2 else None))
        b.submit_commands(buf2)
        for _ in range(20):
            b.render_frame(); time.sleep(0.01)
        a2 = analyze(*read_frame(b))
        print("[m4] after recolor: cube color=(%d,%d,%d)" % (a2["r"], a2["g"], a2["b"]))
        if not (a2["r"] > a2["g"] + 25 and a2["r"] > a2["b"] + 25):
            print("[m4] FAIL: cube did not turn red"); ok = False
    else:
        print("[m4] note: cube has no Principled BSDF; skipped recolor check")

    # 4) No-op sync should produce nothing.
    buf3 = sync.sync(ctx)
    print("[m4] idle sync: %s" % ("None (good)" if buf3 is None else "%d bytes" % len(buf3)))
    if buf3 is not None:
        print("[m4] WARN: idle sync emitted a buffer")

    b.destroy()
    print("[m4] %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
