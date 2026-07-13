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
python Plugins/Omniverse/usd-bridge/bridge.py --stage Plugins/Omniverse/usd-bridge/sample.usda --port 8765

# 3a. Headless check (no browser): a NullEngine client builds the scene:
node Plugins/Omniverse/usd-bridge/verify.mjs 8765

# 3b. Browser: serve the demo page and point it at the bridge:
node Plugins/Omniverse/web/server.mjs --port 8080
#     open  http://localhost:8080/?ws=ws://localhost:8765
```

Editing the stage while the bridge runs (e.g. moving a prim) streams a delta and
the Babylon scene updates within a frame.

## How it works

- **`bridge.py`** — `UsdBridge.build_snapshot()` traverses the stage
  (`UsdGeom.Mesh` → geometry with authored normals + UVs, bound
  `UsdPreviewSurface` → PBR scalars + base/metallic‑roughness/normal/emissive/
  occlusion textures (falling back to `displayColor`), `UsdLux` lights,
  `UsdGeom.Camera`) into a command buffer; `build_delta(paths)` emits
  `SetTransform`/material‑scalar updates for changed prims (textures stream once
  in the snapshot). `serve()` registers a
  `Usd.Notice.ObjectsChanged` listener, coalesces dirty prims, and broadcasts
  throttled deltas to connected clients.
- **Coordinate systems** — USD is right-handed (default Y-up); Babylon is
  left-handed Y-up. Points map `(x,y,z)→(x,y,-z)`; a decomposed world transform
  maps translation `(tx,ty,-tz)` and quaternion `(qx,qy,qz,qw)→(-qx,-qy,qz,qw)`.
  Z-up stages use `(x,z,-y)`. Materials are double-sided, so winding under the
  reflection is not a visual concern.
- **Encoder** — reuses `../../../Shared/python/blp_protocol.py`, the shared Python
  `CommandEncoder` (byte-identical to the C++/TS/Blender encoders).

## Current scope & follow-ups

Two flows are supported:

- **Streaming** (default) — the bridge streams geometry over the protocol
  (`build_snapshot` + geometry). Simple; good for small/medium stages.
- **Bake once, update often** (`--baked`) — the bridge bakes the stage's meshes
  to a **glTF** (`--bake out.gltf`, node.name = PrimPath); the client loads that
  once, and the bridge sends **`BindNodePath(id, primPath)`** to bind each loaded
  node, then streams only transform/material **deltas** addressed by path. This
  is the scalable path for large scenes (geometry loads via the glTF loader / a
  CDN, not the socket).

```powershell
# bake, then serve baked + self-animate for a demo:
python Plugins/Omniverse/usd-bridge/bridge.py --stage Plugins/Omniverse/usd-bridge/sample.usda --bake Plugins/Omniverse/web/baked.gltf
python Plugins/Omniverse/usd-bridge/bridge.py --stage Plugins/Omniverse/usd-bridge/sample.usda --port 8765 --baked --animate
node Plugins/Omniverse/web/server.mjs --port 8080
#   open  http://localhost:8080/?ws=ws://localhost:8765&gltf=/baked.gltf
```

Baked geometry + node transforms are written in glTF space (≈ Y-up USD space);
Babylon's glTF loader converts on load, and the baked deltas are sent in the same
(un-converted) space, so bound nodes and deltas stay in one frame.

Deferred: UsdShade node‑graph shaders beyond `UsdPreviewSurface` (e.g. MaterialX,
MDL), UsdSkel/animation, instancing, camera orientation (the arc camera looks at
the origin), and baking normals/UVs/materials/lights/cameras into the glTF (the
baker currently emits positions + `displayColor` only).

