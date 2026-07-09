# USD → Babylon Live Sync bridge

Streams a **USD stage** (including NVIDIA **Omniverse** stages) into a live
**Babylon.js** scene over WebSocket, using the same scene-delta protocol as the
DCC plugins. A web client adds `@babylonjs/live-sync`, points at the bridge, and
the USD content appears and updates live — no page-specific scene code.

```
USD stage (local .usd/.usda, or omniverse://…)
   → bridge.py: traverse → snapshot;  ObjectsChanged notices → deltas
   → WebSocket broadcast (binary protocol buffers)
   → Babylon Live Sync web client → BABYLON.Scene
```

## Requirements

- Python with **`pxr`** (OpenUSD) and **`websockets`** importable.
- For `omniverse://` stages: the Omniverse USD resolver (`omni.client` +
  `OmniUsdResolver` + the `.live` layer plugin). Local USD needs none of that.

## Run

```powershell
# 1. Build the web client bundle (once):
node Clients/ts/build.mjs --web

# 2. Start the bridge on a USD stage:
python Servers/usd-bridge/bridge.py --stage Servers/usd-bridge/sample.usda --port 8765

# 3a. Headless check (no browser): a NullEngine client builds the scene:
node Servers/usd-bridge/verify.mjs 8765

# 3b. Browser: serve the demo page and point it at the bridge:
node Clients/ts/demo/server.mjs --port 8080
#     open  http://localhost:8080/?ws=ws://localhost:8765
```

Editing the stage while the bridge runs (e.g. moving a prim) streams a delta and
the Babylon scene updates within a frame.

## How it works

- **`bridge.py`** — `UsdBridge.build_snapshot()` traverses the stage
  (`UsdGeom.Mesh` → geometry + `displayColor` material, `UsdLux` lights,
  `UsdGeom.Camera`) into a command buffer; `build_delta(paths)` emits
  `SetTransform`/material updates for changed prims. `serve()` registers a
  `Usd.Notice.ObjectsChanged` listener, coalesces dirty prims, and broadcasts
  throttled deltas to connected clients.
- **Coordinate systems** — USD is right-handed (default Y-up); Babylon is
  left-handed Y-up. Points map `(x,y,z)→(x,y,-z)`; a decomposed world transform
  maps translation `(tx,ty,-tz)` and quaternion `(qx,qy,qz,qw)→(-qx,-qy,qz,qw)`.
  Z-up stages use `(x,z,-y)`. Materials are double-sided, so winding under the
  reflection is not a visual concern.
- **Encoder** — reuses `Shared/python/blp_protocol.py`, the shared Python
  `CommandEncoder` (byte-identical to the C++/TS/Blender encoders).

## Current scope & follow-ups

This first bridge **builds the scene via the protocol** (streams geometry). The
architecture's "bake glTF once, stream deltas addressed by PrimPath" optimization
(for large scenes) is a follow-up, and needs the protocol's path-addressing mode
(see `Plugins/Omniverse/Plan.md`). Also deferred: UsdShade → PBR material/texture
translation (currently `displayColor` only), UsdSkel/animation, instancing, and
camera orientation (the arc camera currently looks at the origin).
