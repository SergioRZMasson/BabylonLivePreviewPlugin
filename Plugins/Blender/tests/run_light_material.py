"""In-Blender test: PBR materials + live light change detection.

    blender --background --python Plugins/Blender/tests/run_light_material.py

Pushes an initial snapshot, then (1) boosts the light energy and confirms the
readback gets brighter, and (2) recolors the cube green and confirms the cube
region turns green. Exercises SceneSync light/material diffing end-to-end.
"""

import os
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
    return os.path.join(_REPO, "build", "Plugins", "Blender", "Release", "babylon_live_preview.dll")


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
    total = 0
    n = 0
    lit = 0
    lr = lg = lb = 0
    minx, maxx = w, 0
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            i = (y * w + x) * 4
            r, g, bl = data[i], data[i + 1], data[i + 2]
            total += r + g + bl
            n += 1
            if r + g + bl > 120:
                lit += 1
                lr += r; lg += g; lb += bl
                minx = min(minx, x); maxx = max(maxx, x)
    avg = total / (n * 3.0) if n else 0.0
    col = (lr // lit, lg // lit, lb // lit) if lit else (0, 0, 0)
    return {"avg": avg, "lit": lit, "col": col}


def main():
    dll = default_dll()
    b = bridge.BabylonBridge(dll)
    if not b.create(1280, 720, os.path.join(os.path.dirname(dll), "Scripts")):
        print("[lm] FAILED: blp_create")
        return 2
    for _ in range(3000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    ctx = bpy.context
    sync = capture.SceneSync()
    b.submit_commands(sync.initial_snapshot(ctx))
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    a0 = analyze(*read_frame(b))
    print("[lm] initial: avg=%.1f litcol=%s" % (a0["avg"], a0["col"]))

    ok = True

    # (1) Light: increase energy -> render should get brighter.
    light = next((o for o in bpy.data.objects if o.type == 'LIGHT'), None)
    if light is None:
        print("[lm] FAILED: no light in scene")
        return 3
    print("[lm] light '%s' type=%s energy=%.1f" % (light.name, light.data.type, light.data.energy))
    light.data.energy *= 8.0
    ctx.view_layer.update()
    lbuf = sync.sync(ctx)
    print("[lm] light change -> incremental buf=%s bytes" % (len(lbuf) if lbuf else None))
    if lbuf:
        b.submit_commands(lbuf)
    for _ in range(20):
        b.render_frame(); time.sleep(0.01)
    a1 = analyze(*read_frame(b))
    b0 = sum(a0["col"]) / 3.0
    b1 = sum(a1["col"]) / 3.0
    print("[lm] cube brightness %.0f -> %.0f  (litcol %s -> %s)" % (b0, b1, a0["col"], a1["col"]))
    if not (lbuf and b1 > b0 + 5):
        print("[lm] FAIL: brighter light not reflected"); ok = False

    # (2) Material: recolor the cube green -> lit region should be green-dominant.
    cube = bpy.data.objects.get("Cube")
    recolored = False
    if cube and cube.active_material and cube.active_material.use_nodes:
        for n in cube.active_material.node_tree.nodes:
            if n.type == 'BSDF_PRINCIPLED':
                n.inputs['Base Color'].default_value = (0.05, 0.85, 0.10, 1.0)
                recolored = True
                break
    if recolored:
        ctx.view_layer.update()
        mbuf = sync.sync(ctx)
        print("[lm] material change -> incremental buf=%s bytes" % (len(mbuf) if mbuf else None))
        if mbuf:
            b.submit_commands(mbuf)
        for _ in range(20):
            b.render_frame(); time.sleep(0.01)
        a2 = analyze(*read_frame(b))
        print("[lm] after green material: litcol=%s" % (a2["col"],))
        if not (a2["col"][1] > a2["col"][0] + 20 and a2["col"][1] > a2["col"][2] + 20):
            print("[lm] FAIL: cube did not turn green"); ok = False
    else:
        print("[lm] note: no Principled BSDF; skipped material check")

    b.destroy()
    print("[lm] %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
