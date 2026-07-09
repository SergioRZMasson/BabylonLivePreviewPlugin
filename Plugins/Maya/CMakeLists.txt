# ---------------------------------------------------------------------------
# Maya plugin (milestone M7)
#
# Builds `babylonLivePreview.mll`, linking the shared BabylonLivePreviewCore and
# the shared SceneTranslator. Enable with -DBLP_BUILD_MAYA=ON. The Maya SDK is
# auto-detected from a standard Autodesk install (Maya2024/2025/2023) or set
# -DMAYA_SDK_ROOT=<path with include/maya + lib>.
# ---------------------------------------------------------------------------

set(MAYA_SDK_ROOT "" CACHE PATH "Path to the Maya install/devkit (with include/maya + lib)")

if(NOT MAYA_SDK_ROOT)
    foreach(_ver 2024 2025 2023 2026)
        if(EXISTS "C:/Program Files/Autodesk/Maya${_ver}/include/maya/MFnPlugin.h")
            set(MAYA_SDK_ROOT "C:/Program Files/Autodesk/Maya${_ver}")
            break()
        endif()
    endforeach()
endif()

if(NOT MAYA_SDK_ROOT OR NOT EXISTS "${MAYA_SDK_ROOT}/include/maya/MFnPlugin.h")
    message(STATUS "BLP: Maya plugin skipped (set MAYA_SDK_ROOT to a Maya install with include/maya + lib).")
    return()
endif()

message(STATUS "BLP: Maya plugin using SDK at ${MAYA_SDK_ROOT}")

add_library(BabylonLivePreviewMaya SHARED
    src/plugin.cpp
    src/MayaCapture.cpp
    src/MayaCapture.h)

target_include_directories(BabylonLivePreviewMaya PRIVATE "${MAYA_SDK_ROOT}/include")

target_link_libraries(BabylonLivePreviewMaya PRIVATE
    BabylonLivePreviewCore
    "${MAYA_SDK_ROOT}/lib/OpenMaya.lib"
    "${MAYA_SDK_ROOT}/lib/OpenMayaUI.lib"
    "${MAYA_SDK_ROOT}/lib/OpenMayaRender.lib"
    "${MAYA_SDK_ROOT}/lib/OpenMayaAnim.lib"
    "${MAYA_SDK_ROOT}/lib/Foundation.lib")

# Maya loadable plugins are DLLs with a .mll extension exporting the two entry
# points, plus the standard Maya preprocessor defines.
set_target_properties(BabylonLivePreviewMaya PROPERTIES
    OUTPUT_NAME "babylonLivePreview"
    PREFIX ""
    SUFFIX ".mll"
    FOLDER "BabylonLivePreview/Plugins")

target_compile_definitions(BabylonLivePreviewMaya PRIVATE
    NT_PLUGIN REQUIRE_IOSTREAM _CRT_SECURE_NO_WARNINGS NOMINMAX WIN32_LEAN_AND_MEAN)

if(MSVC)
    # Maya's MFnPlugin does not auto-export the entry points; force them.
    target_link_options(BabylonLivePreviewMaya PRIVATE
        "/export:initializePlugin" "/export:uninitializePlugin")
endif()

# Ship the JS bundle + Babylon Native runtime DLLs next to the .mll so the
# plugin's scriptsRoot ("<mll dir>/Scripts") resolves.
blp_stage_scripts_for(BabylonLivePreviewMaya)
blp_build_live_script(BabylonLivePreviewMaya maya)
blp_copy_runtime_dlls(BabylonLivePreviewMaya)
