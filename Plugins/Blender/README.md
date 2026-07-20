# Babylon Live Preview — Blender add‑on

Renders the Blender scene live in **Babylon.js** (via Babylon Native) and paints
the result back into the 3D viewport, updating as you edit. Target:
**Blender 4.2 LTS (Python 3.11)**.

This is the **in‑process C++ bind layer** in action: a Python add‑on drives a
native module (`babylon_live_preview.dll` on Windows, `libbabylon_live_preview.dylib` on macOS) that embeds Babylon Native. The add‑on
translates the Blender scene to protocol buffers and submits them straight into
the embedded JS decoder — no network.

## How it works

```
Blender (bpy)                         babylon_live_preview.dll (C ABI)
┌───────────────────────────┐         ┌─────────────────────────────────┐
│ capture.py  SceneSync      │ bytes   │ BabylonLivePreviewCore          │
│  scene graph → protocol    ├────────▶│  Babylon Native + live_preview  │
│ __init__.py timer pump     │ submit  │  render offscreen               │
│  render → readback → draw  │◀────────┤  RGBA8 frame (readback)         │
│ viewport.py  gpu draw      │ pixels  │                                 │
└───────────────────────────┘         └─────────────────────────────────┘
```

* **`capture.py`** — `SceneSync` walks the scene and, on each `sync()`, emits only
  what changed (add/remove, transform, geometry on topology change, material,
  lights, camera). Materials are always PBR; PBR **textures** (base colour,
  metallic‑roughness, normal, emissive) are traced from the Principled BSDF and
  streamed as encoded image bytes. Geometry is sent in local space with a node
  transform, so moving an object is a tiny `set_transform`, not a re‑upload.
* **`bridge.py`** — a `ctypes` wrapper over the DLL's C ABI (`blp_create`,
  `blp_submit_commands`, `blp_render_frame`, `blp_request_readback`, …). Zero
  Blender dependencies, so it is unit‑testable standalone.
* **`__init__.py`** — a `bpy.app.timers` pump that each tick renders a frame, reads
  it back, and updates the viewport; a `depsgraph_update_post` handler feeds
  incremental scene changes; plus operators and preferences.
* **`viewport.py`** — draws the readback frame in the viewport with the Blender
  `gpu` module (RGBA8 → float32 `GPUTexture`, POST_PIXEL draw handler).

Coordinate mapping: Blender (Z‑up, RH) → Babylon (Y‑up, LH) is
`(x, y, z) → (x, z, -y)` with reversed triangle winding; per‑loop normals and the
active UV layer (V‑flipped) are sent so real models shade and texture correctly.
A default environment (`Shared/Assets/environment.env`) is applied as IBL, and
materials output linear so Blender's sRGB viewport encodes exactly once.

## Layout

```
addon/babylon_live_preview/   the add‑on (install into Blender)
  __init__.py                 operators, preferences, timer pump, depsgraph handler
  bridge.py                   ctypes wrapper over the C‑API DLL
  capture.py                  Blender scene → protocol (SceneSync, textures)
  viewport.py                 draws the readback frame via the gpu module
  bin/                        (deployed) the DLL + Scripts/ + runtime DLLs
src/ + exports.def            the C‑API DLL target (built by CMake)
tests/                        standalone + in‑Blender headless tests
```

## Build the native module

From the repo root (see the [top‑level README](../../README.md)). `npm install`
once first (it provides the Babylon.js scripts bundled next to the module).

**Windows** (Visual Studio, D3D11, V8):

```powershell
npm install
cmake --preset windows-x64-release
cmake --build --preset windows-x64-release --target BabylonLivePreviewBlender
```

Produces `build/Plugins/Blender/Release/babylon_live_preview.dll` + its
`Scripts/` folder + the Babylon Native / V8 runtime DLLs.

**macOS** (Apple Silicon, Metal, JavaScriptCore):

```bash
npm install
cmake --preset macos-arm64
cmake --build --preset macos-arm64 --target BabylonLivePreviewBlender
```

Produces `build/macos-arm64/Plugins/Blender/libbabylon_live_preview.dylib` + its
`Scripts/` folder. The `.dylib` is **self‑contained** — Babylon Native and
JavaScriptCore are linked statically / as a system framework, so there are no
sibling runtime libraries to ship.

Either build also emits a ready‑to‑install add‑on zip at
`build/<preset>/babylon_live_preview-<platform>-<arch>.zip` (see *Install & run*).

> **macOS notes:** the JS engine is JavaScriptCore (V8 is Windows‑only here), the
> renderer is Metal, and the headless render surface is an off‑screen
> `CAMetalLayer` (`framebufferOnly = NO` so the frame can be read back) — the
> analogue of the hidden window used for D3D11 readback on Windows.

> **Windows note:** the DLL is compiled with `_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR`
> (set at the repo root). Blender bundles an older `msvcp140.dll`, and the VS 2022
> 17.10+ constexpr `std::mutex` crashes on first lock against it. The CMake build
> already applies this. (Not applicable to the macOS/clang build.)

## Install &amp; run

1. Install the packaged add‑on zip produced by the build
   (`build/<preset>/babylon_live_preview-<platform>-<arch>.zip`). It already
   contains the Python package plus `bin/<native module>` and `bin/Scripts/`.
   (For dev iteration you can instead point Blender's scripts path at
   `Plugins/Blender/addon/` — the add‑on auto‑detects the in‑repo build output.)
2. Blender ▸ **Edit ▸ Preferences ▸ Add‑ons**, use the **⌄ menu ▸ Install from
   Disk…** (Blender 4.2+/5.x) to pick the zip, then enable **Babylon Live
   Preview**. The **Core Module** preference auto‑detects the native module
   (`babylon_live_preview.dll` / `libbabylon_live_preview.dylib`) from the add‑on's
   `bin/` folder or the in‑repo build; only set it manually if you moved it.
3. In the 3D viewport: **Sidebar (N) ▸ Babylon ▸ Toggle Live Preview**.

The timer pump renders Babylon, pushes a snapshot on start, and paints the
readback frame in the viewport; edits stream incrementally. Toggle again to stop.

> **Note:** an enabled add‑on auto‑loads from Blender's user add‑ons folder —
> Windows `%APPDATA%\Blender Foundation\Blender\4.2\scripts\addons\babylon_live_preview\`,
> macOS `~/Library/Application Support/Blender/4.2/scripts/addons/babylon_live_preview/`.
> When iterating on a build, overwrite that installed copy, delete its
> `__pycache__`, and restart Blender to pick up changes.

## Verify (headless, no GUI)

```bash
# standalone: native module + protocol path (no Blender), cross-platform
python Plugins/Blender/tests/run_bridge.py

# inside Blender (background): capture + render the default scene, and incremental
blender --background --python Plugins/Blender/tests/run_in_blender.py
blender --background --python Plugins/Blender/tests/run_incremental.py

# PBR texture streaming (decode / UV / colour space) and multi‑channel tracing
blender --background --python Plugins/Blender/tests/run_texture_blender.py
blender --background --python Plugins/Blender/tests/run_texture_channels.py
```

Babylon Native renders to its own off‑screen surface (a hidden‑window D3D11
swapchain on Windows, an off‑screen `CAMetalLayer` on macOS), so these all work
in background mode.
The on‑screen `gpu` draw (`viewport.py`) is the only part that needs an
interactive Blender to eyeball; the data path it displays is covered by the
headless tests.

## What's shared vs Blender‑specific

| Shared (all producers) | Blender‑specific (this folder) |
|---|---|
| Protocol (`SceneProtocol.h`) + the TypeScript decoder | `capture.py` (bpy scene → protocol) |
| `BabylonLivePreviewCore` (Babylon Native host) | `bridge.py` (ctypes over the C ABI) |
| `live_preview.js` (generated from `Clients/ts`) | timer pump + `gpu` viewport draw |

> Blender uses a Python port of the scene translator (`capture.py`) rather than the
> shared C++ `SceneTranslator` that Maya and 3ds Max link, because `bpy` is
> Python‑only.
