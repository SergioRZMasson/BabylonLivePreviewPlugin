// ===========================================================================
// BabylonLivePreview — Maya scene capture (Maya DAG -> shared translator)
// ===========================================================================
// The Maya-SPECIFIC leaf: walk the DAG and fill the DCC-agnostic POD structs,
// then let the SHARED SceneTranslator (Shared/SceneTranslation.h) diff + encode.
// Everything below the "fill a MeshData/MaterialData/LightData" line is what
// differs from the 3ds Max plugin; the translation + protocol are shared.
#pragma once

#include <BabylonLivePreview/SceneTranslation.h>

#include <cstdint>

namespace BabylonLivePreview::MayaPlugin
{
    // Snapshot of the current Maya scene into a command buffer, using `tr` for id
    // assignment + coordinate conversion. When `incremental` is false this emits
    // a full ResetScene snapshot; when true it diffs against the translator's
    // state and emits only changes (+ removals). Returns the finished buffer.
    std::vector<uint8_t> CaptureScene(SceneTranslator& tr, uint32_t width, uint32_t height,
        bool incremental);
}
