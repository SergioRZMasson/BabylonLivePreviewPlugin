# Babylon Live Preview — 3ds Max plugin

Live-previews the current 3ds Max scene in Babylon.js, mirroring the Maya plugin.
It reuses the **shared** `SceneTranslator` (`Shared/SceneTranslation.h`) — only the
scene extraction (`MaxCapture.cpp`) is Max-specific. 3ds Max is right-handed
Z-up (like Blender), so the translator uses `CoordinateBasis::ZUpRightHanded()`.

## Status

Scaffold, **SDK-gated**. The code is complete and written against the documented
3ds Max SDK, but this machine has the 3ds Max *application* without the *SDK*, so
it has not yet been compiled. It builds once `MAX_SDK_ROOT` points at a `maxsdk`.
Expect a few minor per-SDK-version fixups on first compile (noted inline).

## Requirements

- 3ds Max SDK (install the **SDK** component from the 3ds Max installer — the
  application alone does not include `maxsdk/`).
- Everything else is shared with the rest of the repo (Babylon Native, V8, CMake).

## Build

```powershell
cmake --preset windows-x64-release -DBLP_BUILD_MAX=ON
# If the SDK isn't auto-detected:
cmake --preset windows-x64-release -DBLP_BUILD_MAX=ON `
  "-DMAX_SDK_ROOT=C:/Program Files/Autodesk/3ds Max 2026 SDK/maxsdk"
cmake --build --preset windows-x64-release --target BabylonLivePreviewMax
```

Output: `build/Plugins/Max/Release/BabylonLivePreview.dlu` with its `Scripts/`
bundle and the Babylon Native / V8 runtime DLLs staged alongside.

## Install & use

1. Copy the `.dlu` **and** its sibling `Scripts/` folder + runtime DLLs into a
   folder on Max's plug-in path (or add the folder via *Customize ▸ Configure
   System Paths ▸ 3rd Party Plug-Ins*). Keep the DLLs next to the `.dlu` so the
   plugin's own dependencies resolve.
2. Start 3ds Max. The plugin loads as a Global Utility Plugin and publishes a
   MAXScript interface:

   ```maxscript
   BabylonLivePreview.start()                  -- start live preview + VFB window
   BabylonLivePreview.snapshot "C:/tmp/f.bmp"  -- render one frame to a BMP
   BabylonLivePreview.stop()
   BabylonLivePreview.status()
   ```

3. `start()` opens a Virtual Frame Buffer window showing the live Babylon render,
   updated ~10 Hz as you edit the scene.

## What's shared vs Max-specific

| Shared (all DCCs) | Max-specific (this folder) |
|---|---|
| Protocol (`SceneProtocol.h`) + the TypeScript decoder | DAG walk / geometry / material / light extraction (`MaxCapture.cpp`) |
| `SceneTranslator` diff + encode | Plugin entry points + MAXScript interface (`plugin.cpp`) |
| `BabylonLivePreviewCore` (Babylon Native host) | VFB display + timer pump |
| `live_preview.js` (generated from `Clients/ts`) | Coordinate basis choice (Z-up RH) |

## Known follow-ups

- **Compile it.** The code is complete but SDK‑gated: install the 3ds Max SDK and
  configure with `-DBLP_BUILD_MAX=ON -DMAX_SDK_ROOT=<…/maxsdk>`. It has not been
  compiled or run on a machine without the SDK.
- Smoothing-group-aware vertex normals (currently per-face normals).
- Node-change notifications (currently a periodic incremental re-sync).
- True in-viewport (Nitrous) overlay instead of the VFB window.
- Roughness/glossiness‑mode toggle on the Physical Material (currently reads the
  `roughness` param directly; assumes roughness, not inverted glossiness).
