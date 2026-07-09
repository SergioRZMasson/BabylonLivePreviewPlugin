// ===========================================================================
// BabylonLivePreview — 3ds Max scene capture (Max node graph -> shared translator)
// ===========================================================================
// The Max-SPECIFIC leaf, mirroring Plugins/Maya/src/MayaCapture.*: walk the Max
// node graph and fill the DCC-agnostic POD structs, then let the SHARED
// SceneTranslator (Shared/SceneTranslation.h) diff + encode. 3ds Max is right-
// handed Z-up (like Blender), so the translator is created with
// CoordinateBasis::ZUpRightHanded().
//
// NOTE: This target is SDK-gated (needs MAX_SDK_ROOT). It is written against the
// documented 3ds Max SDK; some leaf details (Physical Material parameter access)
// are marked TODO and may need minor adjustment on first compile against a
// specific SDK version.
#pragma once

#include <BabylonLivePreview/SceneTranslation.h>

#include <cstdint>
#include <vector>

class Interface; // 3ds Max (max.h)

namespace BabylonLivePreview::MaxPlugin
{
    // Snapshot (or incremental diff) of the current Max scene into a command
    // buffer via `tr`. When `incremental` is false, emits a full ResetScene
    // snapshot; when true, diffs against the translator state and emits only
    // changes + removals. `ip` is the running Max Interface.
    std::vector<uint8_t> CaptureScene(SceneTranslator& tr, Interface* ip, bool incremental);
}
