# @babylonjs/live-sync

Live-update a Babylon.js scene from compact **scene-delta buffers**, delivered
either by an in-process **native call** (Babylon Native — the DCC plugins) or a
**WebSocket** stream (browser — e.g. an Omniverse/USD bridge). One decoder, two
transports.

This TypeScript project is the **single source of truth** for the JS side of the
protocol. The DCC plugins (Blender, Maya, 3ds Max) each build their own
`live_preview.js` from it at build time (see *Per-DCC bundles* below); browser
apps consume the web bundle.

## Layout

```
src/
  babylon.ts              access to the host's BABYLON namespace (never bundled)
  protocol.ts             wire-format constants + Reader (mirrors SceneProtocol.h)
  SceneApplier.ts         decode a buffer -> mutate a BABYLON.Scene (transport-agnostic)
  NativeHost.ts           Babylon Native bootstrap: engine + scene + render loop + C++ bridge
  LiveSync.ts             browser API: new BabylonLiveSync(scene, { source })
  transports/
    Source.ts             transport interface
    WebSocketSource.ts    binary WebSocket frames -> applier
    NativeSource.ts       in-process global-call transport
  entries/
    native.ts             -> live_preview.js (DCC plugins)
    web.ts                -> ESM/UMD (browser/npm)
build.mjs                 esbuild bundler
```

Babylon is **never bundled**: the code uses the host's global `BABYLON` (Babylon
Native, or a UMD `<script>`), or a namespace you inject via `options.babylon`.
Only `import type` references `babylonjs`, which esbuild erases.

## Build

Dependencies (esbuild, typescript) live in the repo-root `node_modules`:

```powershell
# once, at the repo root:
npm install

# native bundle (what a DCC plugin ships):
node Clients/ts/build.mjs --entry native --dcc maya --out <dir>/live_preview.js

# browser/npm bundles (ESM + UMD) into Clients/ts/dist:
node Clients/ts/build.mjs --web

# type-check:
node node_modules/typescript/bin/tsc -p Clients/ts/tsconfig.json
```

## Per-DCC bundles (native)

Each DCC plugin's CMake calls `blp_build_live_script(<target> <dcc>)`
(`cmake/BlpHelpers.cmake`), which runs `build.mjs` to emit
`<plugin output>/Scripts/live_preview.js` with the DCC name embedded as the
`BLP_DCC` define. So Blender/Maya/3ds Max each generate their own bundle from
this shared source — letting them diverge later without forking the decoder.

At runtime the C++ core loads `babylon.js` then this `live_preview.js`;
`NativeHost` creates the engine + scene + render loop and installs the bridge
globals (`applyCommands`, `blpEval`) the core calls.

## Browser / WebSocket use

```ts
import { BabylonLiveSync } from "@babylonjs/live-sync";

// scene is your existing BABYLON.Scene (e.g. a glTF-baked stage)
const sync = new BabylonLiveSync(scene, { source: "ws://localhost:8765" });
await sync.start();   // scene now updates live from delta frames
```

For a USD/Omniverse source, a bridge service watches the stage and broadcasts
scene-delta buffers over WebSocket; the initial geometry is loaded once from a
baked glTF and deltas are addressed to those nodes. See
`Plugins/Omniverse/Plan.md`.

## Protocol

Binary, little-endian, mirrors `Shared/include/BabylonLivePreview/
SceneProtocol.h` (magic `BLPC`, version 2). Keeping the C++/Python encoders and
this TS decoder against one spec is essential — see the "single source of truth"
note in the architecture doc.
