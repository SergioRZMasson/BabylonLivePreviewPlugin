# Babylon Live Preview — Blender add-on

Renders the Blender scene live in Babylon.js (via Babylon Native) and shows the
result in the 3D viewport. Target: **Blender 4.2 LTS (Python 3.11)**.

## Layout
```
addon/babylon_live_preview/   the add-on (register with Blender)
  __init__.py                 operators, preferences, modal loop
  bridge.py                   ctypes wrapper over the C-API DLL
  capture.py                  Blender scene -> protocol command buffer
  viewport.py                 draws the readback frame via the gpu module
tests/run_bridge.py           standalone (no Blender) bridge smoke test
tests/run_in_blender.py       in-Blender headless capture test
exports.def / src/            the C-API DLL target (built by CMake)
```

## Build the core DLL
From the repo root (see the top-level README):
```powershell
npm install
cmake --preset windows-x64-release
cmake --build build --config Release --target BabylonLivePreviewBlender
```
This produces `build/Plugins/Blender/Release/babylon_live_preview.dll` together
with its `Scripts/` folder and the Babylon Native / V8 runtime DLLs.

## Verify without Blender (bridge + protocol path)
```powershell
python Plugins/Blender/tests/run_bridge.py
```
Loads the DLL through `bridge.py`, builds a red/green-box scene via `capture.py`,
reads a frame back, writes `bridge_scene.bmp`, and prints `PASS`.

## Verify the capture path inside Blender (headless)
```powershell
blender --background --python Plugins/Blender/tests/run_in_blender.py
blender --background --python Plugins/Blender/tests/run_incremental.py
```
`run_in_blender.py` captures Blender's default scene (`build_scene_snapshot`) and renders it.
`run_incremental.py` pushes an initial snapshot, then moves and recolors the cube via
`SceneSync.sync()` and confirms the readback updates with tiny incremental buffers (transform
~85 B, material ~42 B). Babylon Native uses its own D3D11 device, so both work in background mode.

## Install & run the live add-on
1. Zip the `addon/babylon_live_preview` folder (or point Blender's script path at it).
2. Blender ▸ Edit ▸ Preferences ▸ Add-ons ▸ Install… ▸ enable **Babylon Live Preview**.
3. In the add-on preferences, set **Core DLL** to your built
   `babylon_live_preview.dll` (the in-repo dev build path is auto-detected).
4. In the 3D viewport: **Sidebar (N) ▸ Babylon ▸ Toggle Live Preview**.

The modal loop pumps Babylon Native, pushes a snapshot of the scene on start, and
paints the readback frame in the viewport. Press **Esc** to stop.

## Status / notes
- Bridge + protocol path: **verified** (`run_bridge.py` passes).
- `build_scene_snapshot` (mesh/material/light/camera capture): **verified in Blender 4.2.9**
  (`run_in_blender.py` captures the default scene and Babylon renders it — PASS).
- gpu-module viewport display (`viewport.py`): needs interactive Blender to verify the on-screen
  draw (the data path it shows is already proven).
- **Build requirement:** the C-API DLL must be compiled with `_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR`
  (set at repo root). Blender bundles an older `msvcp140.dll`, and the VS 2022 17.10+ constexpr
  `std::mutex` crashes on first lock against it. The CMake build already applies this.
- Coordinate mapping Blender(Z-up, RH) → Babylon(Y-up, LH): `(x, y, z) → (x, z, -y)`
  with reversed triangle winding. Geometry is baked to world space for now
  (identity node transform); **M4** switches to local geometry + node transforms
  plus depsgraph-diff incremental updates.
