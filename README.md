# Babylon Live Preview &amp; Live Sync

> Keep a **Babylon.js** scene continuously in sync with an external source of
> truth — a DCC tool (**Blender / Maya / 3ds Max**), a **USD / NVIDIA Omniverse**
> stage, or any application — by streaming compact **scene‑delta buffers** over
> one of two interchangeable transports:
>
> * an **in‑process C++ bind layer** (Babylon Native), for DCC plugins that show
>   the live Babylon render inside their own viewport, or
> * a **WebSocket**, for Babylon.js running in a browser.
>
> One protocol, one decoder, many producers.

---

## What we are trying to do

Babylon.js can render almost anything, but getting *live* content into it usually
means writing a bespoke exporter or a one‑off socket format for every host. This
repository turns that into a single, reusable capability:

1. A **well‑defined binary scene‑delta protocol** — create/remove nodes, set
   transforms, upsert meshes / materials / textures / lights, move the camera —
   sent incrementally (only what changed).
2. **Two ways to deliver those deltas into a Babylon scene**, sharing the exact
   same decoder:

   | | In‑process **C++ bind layer** | Remote **WebSocket** |
   |---|---|---|
   | Host | Babylon **Native** (a DCC plugin) | Babylon.js in a **browser** |
   | Producer runs | inside the same process (C++) | anywhere (a server) |
   | Delivery | a direct native call into the JS decoder | binary WebSocket frames |
   | Where it renders | offscreen → read back into the DCC **viewport** | the web page's canvas |
   | Example producers | Blender / Maya / 3ds Max | a USD / Omniverse bridge |

3. A set of **producers** that translate a host's scene graph into that protocol:
   the three DCC plugins (via a shared C++ translator) and a USD/Omniverse
   bridge (Python).

The result: add one library (or one plugin) to your Babylon app, point it at a
source, and your scene is kept live — no per‑host scene code.

## Architecture

```
        PRODUCERS (translate a host scene graph → protocol)
   ┌───────────────────────────┬──────────────────────────────┐
   │  DCC plugins (C++)         │  USD / Omniverse bridge (Py)  │
   │  Blender · Maya · 3ds Max  │  Servers/usd-bridge           │
   │  → SceneTranslation (C++)  │  → blp_protocol.py            │
   └─────────────┬─────────────┴───────────────┬──────────────┘
                 │      binary scene‑delta buffers (one wire format)
                 ▼                              ▼
        TRANSPORTS
   ┌───────────────────────────┐   ┌──────────────────────────┐
   │  C++ bind layer (in‑proc) │   │  WebSocket (remote)       │
   │  Babylon Native host      │   │  ws://…                   │
   └─────────────┬─────────────┘   └───────────────┬──────────┘
                 │                                  │  ArrayBuffer
                 ▼                                  ▼
        CONSUMER  ── the same decoder either way ──
   ┌──────────────────────────────────────────────────────────┐
   │  SceneApplier (TypeScript)  →  mutates a BABYLON.Scene     │
   │  Clients/ts (@babylonjs/live-sync)                         │
   └──────────────────────────────────────────────────────────┘
                 ▼
           BABYLON.Scene  (host owns the engine + render loop)
```

The **decoder is identical** in both paths. In the native path it is bundled
into each DCC plugin (`live_preview.js`, built from the TypeScript project); in
the web path it is the same TypeScript library shipped as an npm/UMD bundle. The
host always owns the `Engine`, `Scene` and render loop — the library only applies
deltas.

## The protocol (the product)

A compact, little‑endian binary command buffer
(`Shared/include/BabylonLivePreview/SceneProtocol.h`):

```
[u32 magic 'BLPC'][u16 version][u16 count] then `count` records: [u16 type][payload…]
```

Commands: `UpsertNode`, `RemoveNode`, `SetTransform`, `UpsertMeshGeometry`,
`UpsertMaterial`, `UpsertLight`, `SetCamera`, `UpsertMaterialTexture`,
`BindNodePath`, `ResetScene`, `SetClearColor`.

* **Node addressing** — nodes are referenced by a producer‑assigned integer id,
  or bound to a **stable path** (`BindNodePath`, e.g. a glTF node name / USD
  PrimPath) so deltas can drive a **pre‑loaded** (glTF‑baked) scene. This enables
  the *"load geometry once, stream only deltas"* model for large scenes.
* **One format, four implementations, kept in lock‑step** — encoders in C++
  (`SceneProtocol.cpp`), TypeScript (`CommandWriter`) and Python
  (`blp_protocol.py`, plus the Blender add‑on's `capture.py`); the single decoder
  in TypeScript (`SceneApplier`).

## Repository layout

```
Shared/                 DCC‑agnostic C++ core
  include/… + src/…      BabylonLivePreviewCore: Babylon Native lifecycle, JS
                         loading, render/readback, the protocol + SceneTranslator
  python/blp_protocol.py shared Python protocol encoder
Clients/ts/             @babylonjs/live-sync — the TypeScript decoder + transports
                         (WebSocket + native), the browser API, and a demo
Plugins/Blender/        Blender add‑on + C‑API DLL          → Plugins/Blender/README.md
Plugins/Maya/           Maya .mll plugin                    → Plugins/Maya/README.md
Plugins/Max/            3ds Max .dlu plugin (SDK‑gated)     → Plugins/Max/README.md
Plugins/Omniverse/      Live Sync architecture spec (Plan.md)
Servers/usd-bridge/     USD / Omniverse → WebSocket bridge  → Servers/usd-bridge/README.md
Tests/                  headless C++ tests (protocol, translator, render)
cmake/                  build helpers (script staging, per‑DCC JS bundling)
Dependencies/           Babylon Native (git submodule)
```

## How the pieces fit

* **`BabylonLivePreviewCore`** (C++ static lib, `Shared/`) — owns the Babylon
  Native session: creates the engine, loads `babylon.js` + the generated
  `live_preview.js`, renders offscreen, reads frames back to CPU, and exposes a
  C ABI + a C++ API plus the `SubmitCommands` channel.
* **`SceneTranslation`** (C++, `Shared/`) — turns a DCC scene graph into protocol
  buffers with incremental diffing and coordinate conversion. **Shared by Maya
  and 3ds Max**; Blender uses a Python port (`capture.py`) because `bpy` is
  Python‑only.
* **`@babylonjs/live-sync`** (`Clients/ts/`) — the `SceneApplier` decoder + the
  WebSocket/native transports + the browser `BabylonLiveSync` API. It is also the
  **source of truth** for each DCC plugin's bundled `live_preview.js` (built
  per‑DCC at compile time; see `cmake/BlpHelpers.cmake`).
* **USD bridge** (`Servers/usd-bridge/`) — opens a USD/Omniverse stage, translates
  it, and broadcasts deltas over WebSocket, with `ObjectsChanged` → incremental
  updates and an optional bake‑once glTF flow.

## Prerequisites

- Windows 10/11, x64 · Visual Studio 2022 (Desktop C++) · CMake ≥ 3.21
- Node.js + npm (used both for Babylon scripts and to build the TS bundles)
- Git · Python with `pxr` + `websockets` (only for the USD bridge)

## Build

```powershell
git clone --recursive <repo-url>
cd BabylonLivePreviewPlugin
git submodule update --init --recursive   # if not cloned with --recursive

# 1. Babylon scripts + TS toolchain (esbuild, typescript)
npm install

# 2. Configure (first run downloads Babylon Native deps — slow)
cmake --preset windows-x64-release

# 3. Build the C++ core, the Blender DLL, and the headless tests
cmake --build --preset windows-x64-release
```

Each DCC plugin generates its own `live_preview.js` from `Clients/ts` at build
time (via `blp_build_live_script`), so Node must be installed and `npm install`
must have run.

| CMake option | Default | Description |
|---|---|---|
| `BLP_BUILD_BLENDER` | ON | Build the Blender C‑API DLL |
| `BLP_BUILD_MAYA` | OFF | Build the Maya plugin (auto‑detects a Maya install, or set `MAYA_SDK_ROOT`) |
| `BLP_BUILD_MAX` | OFF | Build the 3ds Max plugin (needs `MAX_SDK_ROOT`) |
| `BLP_BUILD_TESTS` | ON | Build the headless C++ tests |
| `BABYLON_NATIVE_DIR` | *(submodule)* | Use an external Babylon Native checkout |

## Try it

**DCC live preview (in‑process C++ bind layer):** build a plugin and follow its
README — [Blender](Plugins/Blender/README.md) · [Maya](Plugins/Maya/README.md) ·
[3ds Max](Plugins/Max/README.md).

**Browser (WebSocket):** stream a mock scene into a Babylon page —

```powershell
node Clients/ts/build.mjs --web          # build the browser bundles
node Clients/ts/demo/server.mjs          # http + ws on http://localhost:8080
#   open http://localhost:8080
node Clients/ts/demo/client-check.mjs    # headless end‑to‑end check (no browser)
```

**USD / Omniverse → browser:** see [Servers/usd-bridge/README.md](Servers/usd-bridge/README.md).

## Status

| Area | State |
|---|---|
| C++ core (Babylon Native lifecycle, readback) | ✅ validated |
| Scene protocol + C++/TS/Python encoders + TS decoder | ✅ validated |
| Blender add‑on (live viewport, incremental capture, PBR textures, IBL) | ✅ working |
| Shared C++ `SceneTranslator` + Maya plugin | ✅ builds + validated headlessly |
| 3ds Max plugin | 🚧 SDK‑gated scaffold (compiles once the Max SDK is installed) |
| TypeScript client + WebSocket transport | ✅ validated (headless + browser) |
| USD/Omniverse bridge + bake‑once glTF + path‑addressing | ✅ validated (headless + browser) |

## Coordinate systems

| Host | Space | Mapping to Babylon (Y‑up, LH) |
|---|---|---|
| Blender | Z‑up RH | `(x,y,z) → (x,z,-y)`, reverse winding |
| 3ds Max | Z‑up RH | same as Blender |
| Maya | Y‑up RH | `(x,y,z) → (x,y,-z)` |
| USD | Y‑up RH (or Z‑up) | `(x,y,-z)` (or `(x,z,-y)`) |

## Further reading

- **Architecture / vision spec** — [Plugins/Omniverse/Plan.md](Plugins/Omniverse/Plan.md)
- **TypeScript client** — [Clients/ts/README.md](Clients/ts/README.md)
- **USD / Omniverse bridge** — [Servers/usd-bridge/README.md](Servers/usd-bridge/README.md)
- Per‑plugin docs are linked in the layout table above.
