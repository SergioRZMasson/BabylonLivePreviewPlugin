# Babylon Live Sync — Omniverse / remote WebSocket scenario

This is the **remote WebSocket** side of the project (the counterpart to the
in‑process C++ DCC plugins). A **producer** translates an external source of
truth — a **USD / NVIDIA Omniverse** stage — into the shared scene‑delta protocol
and streams it over a **WebSocket** to a Babylon.js page, which applies the deltas
with `@babylonjs/live-sync`. The browser owns the engine and render loop; the
scene (camera, lights, meshes, animation) arrives entirely over the socket.

```
USD / Omniverse stage ──► usd-bridge (Python)  ──► WebSocket ──► web client (browser)
   source of truth        translate + diff          binary          @babylonjs/live-sync
                          (ObjectsChanged → deltas)  frames          → BABYLON.Scene
```

## Layout

```
Plan.md          the Live Sync architecture / vision spec (read this first)
usd-bridge/      the server: USD/Omniverse → protocol → WebSocket (Python)
  bridge.py        open a stage, snapshot + ObjectsChanged deltas, broadcast;
                   emits normals, UVs and UsdPreviewSurface PBR + textures
  gltf_export.py   minimal glTF baker for the "bake once, stream deltas" flow
  sample.usda      a demo stage (PBR cube + ground + light + camera)
  test_bridge.py   pure unit test (snapshot / delta / baked / normals+UVs+textures)
  verify.mjs       headless NullEngine client vs a live bridge
  README.md        details
web/             the client: a Babylon.js page + a mock demo server + checks
  index.html       a page that only owns the engine/scene; deltas do the rest
  server.mjs       http static + a mock ws producer (no USD needed)
  deltas.mjs       builds demo buffers with the TS CommandWriter
  client-check.mjs headless end‑to‑end check (NullEngine + mock ws)
  bind-check.mjs   headless check of path‑addressing (BindNodePath)
```

The reusable transport/decoder (`WebSocketSource`, `SceneApplier`, the browser
`BabylonLiveSync` API) lives in [`Clients/ts`](../../Clients/ts); this folder is
the concrete Omniverse application built on top of it.

## Quick start

```powershell
npm install                          # once, at the repo root
node Clients/ts/build.mjs --web      # build the browser bundles

# A) mock producer (no USD) — good for a first look:
node Plugins/Omniverse/web/server.mjs
#   open http://localhost:8080
node Plugins/Omniverse/web/client-check.mjs   # headless check, no browser

# B) real USD source:
python Plugins/Omniverse/usd-bridge/bridge.py --stage Plugins/Omniverse/usd-bridge/sample.usda --port 8765
node Plugins/Omniverse/usd-bridge/verify.mjs 8765             # headless check
node Plugins/Omniverse/web/server.mjs                         # serve the page
#   open http://localhost:8080/?ws=ws://localhost:8765
```

See [usd-bridge/README.md](usd-bridge/README.md) for the streaming vs
**bake‑once glTF** flows and the USD→Babylon coordinate conversion, and
[Plan.md](Plan.md) for the overall architecture.
