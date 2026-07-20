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

set(BLP_BLENDER_SOURCES
    src/dllmain.cpp
    ${CMAKE_SOURCE_DIR}/Shared/src/crash_trace.cpp)
if(WIN32)
    # .def forces the blp_* exports from the DLL on MSVC.
    list(APPEND BLP_BLENDER_SOURCES exports.def)
endif()

add_library(BabylonLivePreviewBlender SHARED ${BLP_BLENDER_SOURCES})

target_link_libraries(BabylonLivePreviewBlender PRIVATE BabylonLivePreviewCore)

set_target_properties(BabylonLivePreviewBlender PROPERTIES
    OUTPUT_NAME "babylon_live_preview"
    FOLDER "BabylonLivePreview/Plugins")

if(WIN32)
    target_compile_definitions(BabylonLivePreviewBlender PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN)
endif()

if(APPLE)
    # macOS has no .def mechanism and won't pull the blp_* objects out of the
    # static core (nothing in this module references them). Force-load the core
    # archive so the C ABI objects are present, then restrict the dylib's exports
    # to the blp_* symbols via an exported-symbols list (the exports.def analogue).
    target_link_options(BabylonLivePreviewBlender PRIVATE
        "LINKER:-force_load,$<TARGET_FILE:BabylonLivePreviewCore>"
        "LINKER:-exported_symbols_list,${CMAKE_CURRENT_SOURCE_DIR}/exports.macos.txt")
endif()

# Ship the JS bundle + Babylon Native runtime DLLs next to the module so the
# add-on can point scriptsRoot at "<dll dir>/Scripts".
blp_stage_scripts_for(BabylonLivePreviewBlender)
blp_build_live_script(BabylonLivePreviewBlender blender)
blp_copy_runtime_dlls(BabylonLivePreviewBlender)

# Assemble an installable add-on (Python package + native module + Scripts) and
# zip it. Runs after the staging steps above so Scripts/ is populated.
blp_package_blender_addon(BabylonLivePreviewBlender)
