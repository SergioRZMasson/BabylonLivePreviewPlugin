# ---------------------------------------------------------------------------
# BlpHelpers.cmake
# Utilities for staging the Babylon.js + live-preview JS next to consumers.
#
# The shared core loads its scripts from an explicit folder path at runtime
# (SessionConfig::scriptsRoot) rather than relying on Babylon Native's app:///
# scheme, because for an in-process DCC plugin the host executable directory is
# the DCC (e.g. blender.exe), not our module. Each consumer therefore copies the
# staged scripts into "<its output dir>/Scripts" and passes that path in.
# ---------------------------------------------------------------------------

set(BLP_NODE_MODULES "${CMAKE_SOURCE_DIR}/node_modules" CACHE PATH "Path to node_modules containing babylonjs")
set(BLP_SCRIPTS_STAGE "${CMAKE_BINARY_DIR}/BlpScripts" CACHE INTERNAL "Staged scripts dir")

# Creates the 'blp_scripts' target that assembles the JS bundle in BLP_SCRIPTS_STAGE.
# Call exactly once (from Shared/CMakeLists.txt).
function(blp_setup_scripts)
    # Prefer the minified engine (~6 MB) over babylon.max.js (~45 MB): the
    # unminified bundle takes seconds to parse in V8 and delays scene readiness.
    set(_babylon "${BLP_NODE_MODULES}/babylonjs/babylon.js")
    if(NOT EXISTS "${_babylon}")
        message(FATAL_ERROR
            "babylon.js not found at:\n  ${_babylon}\n"
            "Run 'npm install' in ${CMAKE_SOURCE_DIR} before configuring.")
    endif()

    file(MAKE_DIRECTORY "${BLP_SCRIPTS_STAGE}")

    # "source|destination-name" pairs. Missing optional sources are skipped.
    set(_pairs
        "${_babylon}|babylon.js"
        "${BLP_NODE_MODULES}/babylonjs-loaders/babylonjs.loaders.min.js|babylonjs.loaders.js"
        "${BLP_NODE_MODULES}/babylonjs-materials/babylonjs.materials.min.js|babylonjs.materials.js"
        "${CMAKE_SOURCE_DIR}/Shared/Scripts/live_preview.js|live_preview.js"
        "${CMAKE_SOURCE_DIR}/Shared/Assets/environment.env|environment.env")

    set(_outputs "")
    foreach(_pair ${_pairs})
        string(REPLACE "|" ";" _p "${_pair}")
        list(GET _p 0 _src)
        list(GET _p 1 _name)
        if(EXISTS "${_src}")
            add_custom_command(
                OUTPUT "${BLP_SCRIPTS_STAGE}/${_name}"
                COMMAND ${CMAKE_COMMAND} -E copy_if_different "${_src}" "${BLP_SCRIPTS_STAGE}/${_name}"
                DEPENDS "${_src}"
                COMMENT "Staging JS: ${_name}")
            list(APPEND _outputs "${BLP_SCRIPTS_STAGE}/${_name}")
        endif()
    endforeach()

    add_custom_target(blp_scripts ALL DEPENDS ${_outputs})
    set_property(TARGET blp_scripts PROPERTY FOLDER "BabylonLivePreview")
endfunction()

# Copies the staged scripts into "<target output dir>/Scripts" after building `target`.
function(blp_stage_scripts_for target)
    add_dependencies(${target} blp_scripts)
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:${target}>/Scripts"
        COMMAND ${CMAKE_COMMAND} -E copy_directory "${BLP_SCRIPTS_STAGE}" "$<TARGET_FILE_DIR:${target}>/Scripts"
        COMMENT "Copying Babylon scripts next to ${target}")
endfunction()

# Copies Babylon Native / V8 runtime DLLs next to a target on Windows.
function(blp_copy_runtime_dlls target)
    if(WIN32)
        add_custom_command(TARGET ${target} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E $<IF:$<BOOL:$<TARGET_RUNTIME_DLLS:${target}>>,copy,true>
                $<TARGET_RUNTIME_DLLS:${target}> $<TARGET_FILE_DIR:${target}>
            COMMAND_EXPAND_LISTS)
    endif()
endfunction()
