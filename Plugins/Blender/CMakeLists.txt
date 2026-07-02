# ---------------------------------------------------------------------------
# BabylonLivePreviewBlender
#
# A SHARED library (DLL) that links the static core and exports the stable C
# ABI (see Shared/include/BabylonLivePreview/c_api.h). The Blender Python add-on
# in addon/ loads this DLL via ctypes.
#
# The blp_* symbols live in the static core (c_api.obj); exports.def forces the
# linker to export them from this DLL without duplicate definitions.
# ---------------------------------------------------------------------------

add_library(BabylonLivePreviewBlender SHARED
    src/dllmain.cpp
    ${CMAKE_SOURCE_DIR}/Shared/src/crash_trace.cpp
    exports.def)

target_link_libraries(BabylonLivePreviewBlender PRIVATE BabylonLivePreviewCore)

set_target_properties(BabylonLivePreviewBlender PROPERTIES
    OUTPUT_NAME "babylon_live_preview"
    FOLDER "BabylonLivePreview/Plugins")

if(WIN32)
    target_compile_definitions(BabylonLivePreviewBlender PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

# Ship the JS bundle + Babylon Native runtime DLLs next to the module so the
# add-on can point scriptsRoot at "<dll dir>/Scripts".
blp_stage_scripts_for(BabylonLivePreviewBlender)
blp_copy_runtime_dlls(BabylonLivePreviewBlender)
