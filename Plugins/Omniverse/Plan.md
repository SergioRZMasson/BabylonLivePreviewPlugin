# Babylon Live Sync — Protocol & Architecture

> Generic architecture for live-updating a **Babylon.js** scene from an external
> source of truth using a **well-defined delta protocol**. The same protocol is
> delivered over two interchangeable transports:
>
> * **Native function call** — in-process, for **Babylon Native** hosts
>   (Blender / Maya / 3ds Max plugins).
> * **WebSocket stream** — out-of-process, for **Babylon.js in the browser**
>   (e.g. an NVIDIA Omniverse / USD source of truth).
>
> A consumer adds one library to their Babylon app, points it at a source, and
> their scene is kept live. Digital-twin / IoT dashboards are *one* application
> of this, not the design center.

---

## 1. Motivation

We already have a compact binary **scene-delta protocol** (`Shared/include/
BabylonLivePreview/SceneProtocol.h`) and a JavaScript **decoder** that applies
those deltas to a `BABYLON.Scene` (`applyCommands` in `Shared/Scripts/
live_preview.js`). Today they only run *inside* Babylon Native to preview a DCC
scene. But nothing about the protocol or the decoder is DCC- or Native-specific:

* The **producer** of deltas can be a DCC translator (C++), a server bridging
  another authoring tool (Omniverse/USD), or any application.
* The **transport** can be an in-process native call or a network stream.
* The **consumer** is always the same: decode a delta buffer and mutate a
  `BABYLON.Scene`.

So the protocol is the product. Everything else is a producer or a transport
binding around it.

## 2. Core concept: the scene-delta protocol as the contract

A **delta** is a small, self-describing binary command buffer that mutates a live
scene: create/remove nodes, set transforms, upsert meshes / materials / textures
/ lights, move the camera, etc. (see §6 for the current command set).

Design tenets:

* **Transport-agnostic.** A delta is a byte buffer. How it arrives (native call,
  WebSocket frame, file) is irrelevant to the decoder.
* **Incremental first.** After an initial state, only what changed is sent. The
  producer diffs; the consumer applies.
* **One canonical wire format: binary, little-endian.** Compact for both native
  in-process hand-off and WebSocket binary frames, and efficient when geometry
  must be streamed. A JSON projection may exist for debugging/interop, but binary
  is the source of truth so a single decoder serves every transport.
* **Addressable nodes.** Every node has a stable identity so deltas find their
  target. Two addressing modes (see §7): producer-assigned integer ids (DCC), and
  stable string paths (glTF-baked scenes, e.g. USD PrimPath).

## 3. Architecture layers

```
   ┌────────────────────────── PRODUCERS ──────────────────────────┐
   │  DCC translator (C++)   Omniverse/USD bridge   any application │
   │  Blender · Maya · Max   (USD deltas → protocol)                │
   └───────────────┬───────────────────┬───────────────────────────┘
                   │  scene-delta buffers (binary)
                   ▼                    ▼
   ┌──────────────────────── TRANSPORTS ───────────────────────────┐
   │  Native function call            WebSocket server/stream       │
   │  (in-process, Babylon Native)    (out-of-process, browser)     │
   └───────────────┬───────────────────┬───────────────────────────┘
                   │  ArrayBuffer                    │  ArrayBuffer
                   ▼                                 ▼
   ┌──────────────────────── CONSUMER (TS library) ────────────────┐
   │  Source (native | websocket)  →  SceneApplier.apply(buffer)    │
   │                                   mutates a BABYLON.Scene       │
   └───────────────────────────────────────────────────────────────┘
                   ▼
             BABYLON.Scene  (host owns engine + render loop)
```

The **consumer library never creates the engine**. The host application (a
Babylon Native app, or a web page) owns the `Engine`/`Scene` and render loop, then
hands the `Scene` to the library. This is what lets the identical library run in
both environments.

## 4. Components

### 4.1 Protocol (single source of truth)
A versioned spec plus **shared conformance vectors**: golden input buffers with
their expected decoded result. Every implementation (C++ encoder, Python encoder,
TS decoder) is tested against the same vectors so they cannot silently drift.

### 4.2 Consumer — TypeScript library (new)
A standalone TS/npm package, independent of the native C++ code:

```ts
import { BabylonLiveSync } from "@babylonjs/live-sync";

const sync = new BabylonLiveSync(scene, { source: "ws://host:8765" });
await sync.start();   // scene now updates live
```

Internals:
* **`SceneApplier`** — the port of today's `applyCommands` + `_cmd*` handlers to
  TypeScript, operating on an injected `BABYLON.Scene` (no engine creation).
* **Transports (`Source`)**
  * `WebSocketSource(url)` — connects, receives binary frames → `apply()`; handles
    reconnect/backoff.
  * `NativeSource(binding)` — receives buffers pushed/pulled across the Babylon
    Native JS⇄C++ bridge → `apply()`.
* **Public API** — `new BabylonLiveSync(scene, { source })`, `.start()`, `.stop()`,
  events (`connected`, `applied`, `error`), and stats.
* **Packaging** — ESM/UMD for the browser; also loadable by Babylon Native's
  `ScriptLoader` (or consumed by the thin native host script).

### 4.3 Producers
* **DCC translator (C++)** — `SceneTranslation.{h,cpp}`: walks the DCC graph, diffs,
  emits deltas. Shared by Maya and 3ds Max; Blender uses a Python port
  (`capture.py`) because `bpy` is Python-only.
* **Omniverse/USD bridge** — see §8.
* **Any application** — anything that can produce the byte buffers.

## 5. Transport bindings (same wire format)

| | Native function call | WebSocket |
|---|---|---|
| Host | Babylon Native app / DCC plugin | Browser page |
| Producer location | In-process (C++) | Remote server |
| Delivery | `submitCommands(ptr,len)` → JS bridge → `apply` | `ws.onmessage` (binary) → `apply` |
| Initial geometry | Streamed via protocol, **or** loaded from a file/glTF | Loaded from **baked glTF** (see §8), deltas after |
| Back-channel | readback / stats | optional `ws` uplink (selection, stats) |

Both converge on a single entry point: **`SceneApplier.apply(ArrayBuffer)`**.

## 6. Command set (current v2)

Buffer: `[u32 magic 'BLPC'][u16 version][u16 count]` then `count` records, each
`[u16 type][payload…]`, little-endian. Strings are `[u16 len][utf8]`.

| Type | Command | Payload |
|---|---|---|
| 1 | UpsertNode | id, parentId, kind, name, transform |
| 2 | RemoveNode | id |
| 3 | SetTransform | id, pos[3], quat[4], scale[3] |
| 4 | UpsertMeshGeometry | id, vtxCount, hasNormals, hasUV, idxCount, arrays |
| 5 | UpsertMaterial | id, rgba[4], metallic, roughness, emissive[3], emissiveStrength |
| 6 | UpsertLight | id, type, dir/pos[3], color[3], intensity |
| 7 | SetCamera | mode + arcRotate params or view/proj matrices |
| 8 | UpsertMaterialTexture | id, channel, encoding, len, bytes (len 0 = clear) |
| 10 | ResetScene | — |
| 11 | SetClearColor | rgba[4] |

This set already covers "bake once, update often": geometry (4) for streamed
scenes, or pure transform/material/visibility deltas (3, 5, 8) for glTF-baked
scenes.

## 7. Node addressing (key design decision)

Deltas must resolve to a target node. Two modes:

* **Integer id (producer-assigned).** DCC translators allocate stable `u64` ids
  and keep a `name→id` registry. Works when the producer *builds* the scene.
* **Stable string path.** For **pre-loaded (glTF-baked) scenes**, the producer
  does not build geometry; it references nodes by a path that must match a node
  identity in the loaded asset — e.g. USD **PrimPath** exported into the glTF node
  name (or an `extras`/extension). The consumer resolves path→node once and caches
  it for O(1) updates.

**Recommendation:** keep the current integer-id path for DCC, and add a
**path-addressing mode** (either a string-keyed `UpsertNode`/`SetTransform`
variant, or a one-time "bind path→id" handshake the producer sends after the
client loads the glTF). The bake-once producer and the glTF exporter must agree on
this identity — specify it once, in the protocol.

## 8. Reference integration: external source of truth → web (Omniverse/USD)

A concrete producer for a non-Babylon authoring tool. Generalized from a
digital-twin scenario, but the shape applies to any USD/Omniverse source.

**Strategy — "bake once, update often":**
1. **Initial state (bake):** export the current USD stage to **glTF** once. Babylon
   loads it with the standard glTF loader. Each node carries its **PrimPath** as a
   stable identity (node name / `extras`).
2. **Deltas (stream):** a **bridge service** watches the stage and converts each
   USD change into a scene-delta buffer addressed by PrimPath, broadcast over
   WebSocket.
3. **Apply:** the web client's `SceneApplier` resolves PrimPath→node and applies
   transform/material/visibility deltas — no re-load, O(1) per change.

**Bridge service:**
* Can run **standalone — no Kit required**. `omni.client` + `OmniUsdResolver` +
  the `.live` layer plugin let a plain process `Usd.Stage.Open("omniverse://…")`
  and subscribe to fine-grained change notices (`ObjectsChanged`:
  resynced / changed-info / per-field). A local `.usd`/`.usdc` works the same way
  for non-Omniverse USD.
* **Language:** Python (fast to build, matches `omni.usd`/`pxr`) **or** C++
  linking `libusd` — the C++ option can **reuse `SceneTranslation`** (coordinate
  conversion, diffing, delta encoding) instead of re-implementing it.
* **Coordinate conversion:** USD is Y-up right-handed (or Z-up via `upAxis`);
  Babylon is Y-up left-handed. The bridge applies the same basis change our
  `CoordinateBasis` encodes for Maya (Y-up RH) / Blender (Z-up RH).
* **Throttling:** coalesce high-frequency updates to a target rate (e.g. 30–60 Hz)
  and merge repeated changes to the same prim within a tick to avoid WS
  saturation.

**Data flow:**
```
 authoring / telemetry → USD stage (source of truth)
      → bridge: ObjectsChanged → delta buffer (addressed by PrimPath)
      → WebSocket broadcast
      → web client: SceneApplier.apply → BABYLON.Scene (glTF-baked)
```

## 9. Constraints & open decisions

* **Addressing (§7).** Add path-addressing for baked scenes. *Highest priority.*
* **Wire format.** Stay binary end-to-end; JSON only as an optional debug encoding.
* **Versioning/negotiation.** With producers and consumers shipped separately, add
  a handshake: consumer advertises the max protocol version it supports; producer
  emits at or below it. (The `version` field exists but is currently unchecked.)
* **Spec drift.** Maintain the protocol as ONE spec + shared conformance vectors
  exercised by the C++, Python, and TS implementations.
* **Geometry policy.** Prefer glTF for initial heavy geometry; reserve
  `UpsertMeshGeometry` for producers that genuinely author geometry live (DCC).
* **Security (web).** WebSocket origin checks / auth for any non-local deployment;
  cap buffer sizes.

## 10. Proposed repository separation

Split the two shippable artifacts so the JS/web side no longer lives inside the
native build:

```
<repo>/
  Protocol/                 spec.md + conformance vectors (source of truth)
  Clients/ts/               TypeScript library (npm package) — SceneApplier + transports
  Native/                   C++ core: Babylon Native host + protocol encoder
    (was Shared/)           + SceneTranslation (shared DCC translator)
  Plugins/                  DCC producers: Blender · Maya · Max
  Servers/Omniverse/        USD→glTF bake + delta bridge (Python or C++)
```

* The **TS library** is consumable with zero native dependencies (browser/web).
* The **native library** consumes the *same* protocol spec and vectors.
* The DCC plugins keep using the native encoder; the browser uses the TS decoder;
  both are validated against `Protocol/`.

## 11. Roadmap (generic)

| Phase | Goal | Exit criteria |
|---|---|---|
| **P0** | Extract the protocol spec + conformance vectors | `Protocol/` with golden buffers; C++ & Python encoders validated against them |
| **P1** | TypeScript consumer library | `SceneApplier` ported to TS; unit-tested against the vectors (headless, no engine) |
| **P2** | Transports | `WebSocketSource` + `NativeSource`; browser demo updates a scene from a mock WS producer |
| **P3** | Native re-integration | Babylon Native host script consumes the TS library (or its build) via the native source; DCC preview unchanged |
| **P4** | Path addressing | glTF-baked scene updated by string path; bind handshake or string-keyed commands |
| **P5** | Omniverse/USD bridge | standalone bridge: USD `ObjectsChanged` → deltas → WS → live web scene |
| **P6** | Hardening | version negotiation, throttling, reconnect, auth, packaging (npm + native) |

---

### Relationship to the existing project
This repo already implements the **producer + native transport + decoder** for
DCC live preview (Blender shipping; Maya/3ds Max in progress). This document
generalizes the *decoder* into a standalone, transport-agnostic **consumer
library** and adds a second **WebSocket transport** plus a **USD/Omniverse
producer**, without changing the DCC path. It also has natural synergy with the
separate `BabylonUSDPlugin` (USD↔Babylon) effort.
