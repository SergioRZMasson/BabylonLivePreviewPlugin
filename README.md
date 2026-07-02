# Babylon Live Preview Plugin

Native C++ plugins for **3ds Max**, **Maya**, and **Blender** that render the DCC
scene live in **Babylon.js** using [Babylon Native](https://github.com/BabylonJS/BabylonNative),
displaying the result as a texture inside the DCC viewport.

Shared, DCC-agnostic logic (Babylon Native lifecycle, JS loading, render/readback,
scene-sync protocol) lives in a reusable static library, `BabylonLivePreviewCore`.
Each DCC integration lives under `Plugins/<Dcc>/`.

```
Shared/            BabylonLivePreviewCore (static lib) + live_preview.js
Plugins/Blender/   C-API DLL + Python add-on (first target)
Plugins/Max/       3ds Max plugin (M6, SDK-gated)
Plugins/Maya/      Maya plugin (M7, SDK-gated)
Tests/             headless render smoke test
Dependencies/      Babylon Native (git submodule)
```

## Prerequisites

- Windows 10/11, x64
- Visual Studio 2022 (Desktop development with C++)
- CMake ≥ 3.21
- Node.js + npm
- Git

## Getting the source

```powershell
git clone --recursive git@github.com:SergioRZMasson/BabylonLivePreviewPlugin.git
cd BabylonLivePreviewPlugin
# if you cloned without --recursive:
git submodule update --init --recursive
```

## Build

```powershell
# 1. Install the Babylon.js scripts (babylon.max.js, loaders, materials)
npm install

# 2. Configure (downloads Babylon Native's dependencies on first run — slow)
cmake --preset windows-x64-release

# 3. Build
cmake --build --preset windows-x64-release
```

The default build produces `BabylonLivePreviewCore`, the Blender C-API DLL, and
the `blp_headless_render` smoke test.

Useful options:

| Option | Default | Description |
|--------|---------|-------------|
| `BLP_BUILD_BLENDER` | ON | Build the Blender C-API DLL |
| `BLP_BUILD_MAX` | OFF | Build the 3ds Max plugin (needs `MAX_SDK_ROOT`) |
| `BLP_BUILD_MAYA` | OFF | Build the Maya plugin (needs `MAYA_SDK_ROOT`) |
| `BLP_BUILD_TESTS` | ON | Build headless tests |
| `BABYLON_NATIVE_DIR` | *(submodule)* | Use an external Babylon Native checkout |

## Run the smoke test

```powershell
.\build\Tests\headless_render\Release\blp_headless_render.exe
```

It boots Babylon Native, renders the default scene, reads the frame back to CPU
memory, and writes `live_preview_frame.bmp` next to the executable.

## Blender add-on (in development)

After building, the Blender add-on lives in
`Plugins/Blender/addon/babylon_live_preview/`. Point its **Core DLL** preference
at the built `babylon_live_preview.dll` (with its `Scripts/` folder alongside),
then use **View3D ▸ Sidebar ▸ Babylon ▸ Toggle Live Preview**.
