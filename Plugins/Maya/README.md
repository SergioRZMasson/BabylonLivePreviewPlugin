# Babylon Live Preview — Maya plugin

Live‑previews the current Maya scene in **Babylon.js** (via Babylon Native),
displaying the render in Maya's **Render View**. It reuses the **shared**
`SceneTranslator` (`Shared/SceneTranslation.h`) — only the scene extraction
(`MayaCapture.cpp`) is Maya‑specific. Maya is right‑handed **Y‑up**, so the
translator uses `CoordinateBasis::YUpRightHanded()`.

This is the **in‑process C++ bind layer**: the `.mll` embeds `BabylonLivePreviewCore`
(Babylon Native), translates the Maya DAG to protocol buffers, submits them
directly into the embedded JS decoder, and reads frames back for display — no
network.

## How it works

```
Maya DAG                              babylonLivePreview.mll
┌───────────────────────────┐         ┌─────────────────────────────────┐
│ MayaCapture               │ POD     │ SceneTranslator (shared C++)    │
│  MItDag / MFnMesh /       ├────────▶│  diff + coordinate convert →    │
│  MFnLight / MFnCamera     │ structs │  protocol buffer                │
│ plugin.cpp                │         │ BabylonLivePreviewCore          │
│  babylonLivePreview cmd   │ submit  │  Babylon Native render offscreen│
│  MTimerMessage pump       │◀────────┤  RGBA8 readback → MRenderView   │
└───────────────────────────┘ frame   └─────────────────────────────────┘
```

* **`MayaCapture.cpp`** — walks the DAG (`MItDag`): `MFnMesh` (points, vertex
  normals, triangles), `standardSurface` (baseColor / metalness /
  specularRoughness / emission) plus a connected `file` node for the base‑colour
  texture, `MFnLight` (directional vs point), and the `persp` `MFnCamera`. It
  fills the DCC‑agnostic POD structs and hands them to the shared
  `SceneTranslator`. Maya's `MMatrix` (row‑vector) is transposed into the
  translator's column‑major convention.
* **`plugin.cpp`** — registers the `babylonLivePreview` command and drives the
  shared pipeline. A `MTimerMessage` pump re‑syncs incrementally, renders a frame,
  reads it back, and pushes it to Maya's **Render View** (`MRenderView`, a
  shader‑free live‑render surface). Display degrades to a no‑op in batch/`mayapy`.

## Requirements

- **Maya devkit / SDK** — auto‑detected from a standard Autodesk install
  (`C:/Program Files/Autodesk/Maya<ver>` with `include/maya` + `lib`), or set
  `-DMAYA_SDK_ROOT=<path>`. Validated against **Maya 2024**.
- Everything else is shared with the rest of the repo (Babylon Native, V8, CMake).

## Build

```powershell
cmake --preset windows-x64-release -DBLP_BUILD_MAYA=ON
cmake --build --preset windows-x64-release --target BabylonLivePreviewMaya
```

Output: `build/Plugins/Maya/Release/babylonLivePreview.mll` with its `Scripts/`
bundle (including a `live_preview.js` built from `Clients/ts`) and the Babylon
Native / V8 runtime DLLs staged alongside.

## Install &amp; use

The plugin ships bundled runtime DLLs (V8, Babylon Native). Maya's `loadPlugin`
does **not** put a plugin's own folder on the DLL search path, so use the provided
**Maya module** (`.mod`), which adds `plug-ins/` to `PATH`:

```powershell
# package the .mll + runtime + Scripts as a relocatable module in dist/maya/
powershell -File Plugins/Maya/deploy.ps1
```

Then:

1. Add `dist/maya` to the `MAYA_MODULE_PATH` environment variable (or copy
   `dist/maya/BabylonLivePreview.mod` into your `Maya/2024/modules` folder and fix
   the path inside it).
2. Start Maya ▸ **Windows ▸ Settings/Preferences ▸ Plug‑in Manager** ▸ load
   `babylonLivePreview.mll`.
3. Run the command, then open the Render View:

   ```mel
   babylonLivePreview -start;                       // live preview
   babylonLivePreview -snapshot "C:/tmp/frame.bmp";  // render one frame to a BMP
   babylonLivePreview -stop;
   babylonLivePreview -status;
   ```
   **Windows ▸ Rendering Editors ▸ Render View** shows the live Babylon render,
   updated ~10 Hz as you edit the scene.

## Verify (headless, `mayapy`)

```powershell
& "C:/Program Files/Autodesk/Maya2024/bin/mayapy.exe" Plugins/Maya/tests/mayapy_snapshot.py
```

Loads the `.mll` (preloading it via `ctypes` first so the bundled DLLs resolve),
builds a cube + `standardSurface` + directional‑light scene, runs
`babylonLivePreview -snapshot`, and asserts the BMP has lit pixels. The
interactive Render View display needs a running Maya to eyeball.

## What's shared vs Maya‑specific

| Shared (all DCCs) | Maya‑specific (this folder) |
|---|---|
| Protocol (`SceneProtocol.h`) + the TypeScript decoder | DAG walk / geometry / material / light extraction (`MayaCapture.cpp`) |
| `SceneTranslator` diff + encode | Plugin entry points + `babylonLivePreview` command (`plugin.cpp`) |
| `BabylonLivePreviewCore` (Babylon Native host) | Render View display + `MTimerMessage` pump |
| `live_preview.js` (generated from `Clients/ts`) | Coordinate basis choice (Y‑up RH) |

## Known follow‑ups

- UsdShade‑style full material graphs (currently `standardSurface` core params +
  a base‑colour file texture).
- True in‑viewport (VP2 / `MRenderOverride`) overlay instead of the Render View
  window.
- DG/DAG change callbacks (currently a periodic incremental re‑sync).
