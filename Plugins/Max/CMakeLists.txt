# ---------------------------------------------------------------------------
# 3ds Max plugin (milestone M6)
#
# Builds `BabylonLivePreview.dlu`, linking the shared BabylonLivePreviewCore and
# the shared SceneTranslator. Max is right-handed Z-up (same as Blender), so the
# translator uses CoordinateBasis::ZUpRightHanded().
#
# Requires the 3ds Max SDK. Enable with -DBLP_BUILD_MAX=ON and either set
# -DMAX_SDK_ROOT=<path to maxsdk>, or install the "3ds Max <ver> SDK" so it is
# auto-detected below. The installed 3ds Max application does NOT include the
# SDK — install the separate SDK component from the Max installer.
# ---------------------------------------------------------------------------

set(MAX_SDK_ROOT "" CACHE PATH "Path to the 3ds Max SDK (the 'maxsdk' folder)")

if(NOT MAX_SDK_ROOT)
    foreach(_ver 2026 2025 2024 2023)
        foreach(_cand
            "C:/Program Files/Autodesk/3ds Max ${_ver} SDK/maxsdk"
            "C:/Program Files/Autodesk/3ds Max ${_ver}/maxsdk"
            "C:/Autodesk/3ds Max ${_ver} SDK/maxsdk")
            if(EXISTS "${_cand}/include/max.h")
                set(MAX_SDK_ROOT "${_cand}")
                break()
            endif()
        endforeach()
        if(MAX_SDK_ROOT)
            break()
        endif()
    endforeach()
endif()

if(NOT MAX_SDK_ROOT OR NOT EXISTS "${MAX_SDK_ROOT}/include/max.h")
    message(STATUS "BLP: 3ds Max plugin skipped (set MAX_SDK_ROOT to a maxsdk with include/max.h).")
    return()
endif()

message(STATUS "BLP: 3ds Max plugin using SDK at ${MAX_SDK_ROOT}")

add_library(BabylonLivePreviewMax SHARED
    src/plugin.cpp
    src/MaxCapture.cpp
    src/MaxCapture.h)

target_include_directories(BabylonLivePreviewMax PRIVATE "${MAX_SDK_ROOT}/include")
target_link_directories(BabylonLivePreviewMax PRIVATE "${MAX_SDK_ROOT}/lib/x64/Release")

# Core Max SDK import libs for a scene-capture + utility plugin.
target_link_libraries(BabylonLivePreviewMax PRIVATE
    BabylonLivePreviewCore
    core maxutil geom mesh gfx bmm paramblk2 gup)

# 3ds Max plugins are DLLs; a Global Utility Plugin uses the .dlu extension.
set_target_properties(BabylonLivePreviewMax PROPERTIES
    OUTPUT_NAME "BabylonLivePreview"
    PREFIX ""
    SUFFIX ".dlu"
    FOLDER "BabylonLivePreview/Plugins")

target_compile_definitions(BabylonLivePreviewMax PRIVATE
    _UNICODE UNICODE ISOLATION_AWARE_ENABLED=1 NOMINMAX WIN32_LEAN_AND_MEAN)

# Ship the JS bundle + Babylon Native runtime DLLs next to the .dlu so the
# plugin's scriptsRoot ("<dlu dir>/Scripts") resolves.
blp_stage_scripts_for(BabylonLivePreviewMax)
blp_copy_runtime_dlls(BabylonLivePreviewMax)
