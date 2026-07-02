"""Headless check of the timer-pump logic (bpy.app.timers path).

    blender --background --python Plugins/Blender/tests/run_pump.py

Registers the packaged add-on, calls _start(), then drives _pump() in a loop
(simulating the timer) and confirms it pushes the snapshot and completes a
readback. The GPU texture upload is skipped in background (no draw context),
but everything else on the pump path is exercised.
"""

import os
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIST = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "dist"))
sys.path.insert(0, _DIST)

import babylon_live_preview as a  # noqa: E402


def main():
    print("[pump] module file: %s" % getattr(a, "__file__", "?"))
    print("[pump] has _start=%s _pump=%s _stop=%s"
          % (hasattr(a, "_start"), hasattr(a, "_pump"), hasattr(a, "_stop")))
    if not hasattr(a, "_start"):
        print("[pump] sys.path[0:3]=%s" % sys.path[0:3])
        return 9
    ok, msg = a._start(bpy.context)
    print("[pump] start: ok=%s msg=%s" % (ok, msg))
    if not ok:
        return 2

    pumps = 0
    for i in range(1000):
        a._pump()
        pumps = i + 1
        if a._pushed and a._readback_logged:
            break
        time.sleep(0.008)

    pushed, readback = a._pushed, a._readback_logged
    print("[pump] after %d pumps: pushed=%s readback_logged=%s" % (pumps, pushed, readback))

    a._stop()
    print("[pump] stopped; bridge=%s timer_registered=%s"
          % (a._bridge, bpy.app.timers.is_registered(a._pump)))

    result = ok and pushed and readback
    print("[pump] %s" % ("PASS" if result else "FAIL"))
    return 0 if result else 5


if __name__ == "__main__":
    sys.exit(main())
