# ---------------------------------------------------------------------------
# 3ds Max plugin (milestone M6)
#
# Requires the 3ds Max SDK. Enable with -DBLP_BUILD_MAX=ON and
# -DMAX_SDK_ROOT=<path to maxsdk>. Links the shared BabylonLivePreviewCore and
# renders into Max's D3D11 (Nitrous) viewport via the shared-texture path.
# ---------------------------------------------------------------------------

set(MAX_SDK_ROOT "" CACHE PATH "Path to the 3ds Max SDK (maxsdk)")

if(NOT MAX_SDK_ROOT)
    message(STATUS "BLP: 3ds Max plugin skipped (set MAX_SDK_ROOT to enable).")
    return()
endif()

message(STATUS "BLP: 3ds Max plugin scaffolding present, implementation pending (M6).")

# Placeholder target keeps the wiring in place; real SDK sources land in M6.
add_library(BabylonLivePreviewMax STATIC src/plugin_placeholder.cpp)
target_link_libraries(BabylonLivePreviewMax PRIVATE BabylonLivePreviewCore)
set_property(TARGET BabylonLivePreviewMax PROPERTY FOLDER "BabylonLivePreview/Plugins")
