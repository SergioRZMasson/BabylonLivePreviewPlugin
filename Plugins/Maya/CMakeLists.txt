# ---------------------------------------------------------------------------
# Maya plugin (milestone M7)
#
# Requires the Maya devkit. Enable with -DBLP_BUILD_MAYA=ON and
# -DMAYA_SDK_ROOT=<path to devkit>. Links the shared BabylonLivePreviewCore and
# renders into Maya's Viewport 2.0 (MHWRender) via the shared-texture path.
# ---------------------------------------------------------------------------

set(MAYA_SDK_ROOT "" CACHE PATH "Path to the Maya devkit")

if(NOT MAYA_SDK_ROOT)
    message(STATUS "BLP: Maya plugin skipped (set MAYA_SDK_ROOT to enable).")
    return()
endif()

message(STATUS "BLP: Maya plugin scaffolding present, implementation pending (M7).")

add_library(BabylonLivePreviewMaya STATIC src/plugin_placeholder.cpp)
target_link_libraries(BabylonLivePreviewMaya PRIVATE BabylonLivePreviewCore)
set_property(TARGET BabylonLivePreviewMaya PROPERTY FOLDER "BabylonLivePreview/Plugins")
