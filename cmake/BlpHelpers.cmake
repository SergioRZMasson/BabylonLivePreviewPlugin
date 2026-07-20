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
    # NOTE: live_preview.js is NOT staged here — it is generated per-DCC from the
    # TypeScript project (Clients/ts) by blp_build_live_script().
    set(_pairs
        "${_babylon}|babylon.js"
        "${BLP_NODE_MODULES}/babylonjs-loaders/babylonjs.loaders.min.js|babylonjs.loaders.js"
        "${BLP_NODE_MODULES}/babylonjs-materials/babylonjs.materials.min.js|babylonjs.materials.js"
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

# Node is required to build the per-DCC live_preview.js from the TypeScript
# project (Clients/ts). Run `npm install` at the repo root once beforehand.
find_program(BLP_NODE_EXECUTABLE NAMES node node.exe)

# Builds "<target output>/Scripts/live_preview.js" from Clients/ts for the given
# DCC (embedded as the BLP_DCC define). Call AFTER blp_stage_scripts_for(target)
# so the generated bundle lands after the shared Babylon scripts are copied. This
# is how each plugin "creates its own" JS bundle from the shared TS source.
function(blp_build_live_script target dcc)
    if(NOT BLP_NODE_EXECUTABLE)
        message(WARNING
            "BLP: node not found — ${target} will ship without live_preview.js. "
            "Install Node.js and run 'npm install' at the repo root.")
        return()
    endif()
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "$<TARGET_FILE_DIR:${target}>/Scripts"
        COMMAND "${BLP_NODE_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/Clients/ts/build.mjs"
            --entry native --dcc ${dcc}
            --out "$<TARGET_FILE_DIR:${target}>/Scripts/live_preview.js"
        COMMENT "Building ${dcc} live_preview.js from Clients/ts (TypeScript)"
        VERBATIM)
endfunction()

# ---------------------------------------------------------------------------
# blp_package_blender_addon(target)
#
# Assembles an installable Blender add-on from the Python package in
# Plugins/Blender/addon/babylon_live_preview plus the freshly built native
# module and its staged Scripts/ folder, then zips it. The add-on's
# _default_dll_path() looks for the native module in "<package>/bin/", so the
# layout produced here is:
#
#   <package>/                 (the four .py files)
#   <package>/bin/<module>     (libbabylon_live_preview.dylib / .dll / .so)
#   <package>/bin/Scripts/     (babylon.js, live_preview.js, environment.env, ...)
#
# Output: ${CMAKE_BINARY_DIR}/babylon_live_preview-<platform>.zip
# ---------------------------------------------------------------------------
function(blp_package_blender_addon target)
    set(_addon_src "${CMAKE_CURRENT_SOURCE_DIR}/addon/babylon_live_preview")
    set(_stage "${CMAKE_BINARY_DIR}/blender-addon")
    set(_pkg "${_stage}/babylon_live_preview")

    # Ensure the staging root exists now so the POST_BUILD WORKING_DIRECTORY (the
    # `cd` into it) succeeds on the very first build.
    file(MAKE_DIRECTORY "${_stage}")

    string(TOLOWER "${CMAKE_SYSTEM_NAME}" _plat)
    if(CMAKE_OSX_ARCHITECTURES)
        set(_arch "${CMAKE_OSX_ARCHITECTURES}")
    else()
        set(_arch "${CMAKE_SYSTEM_PROCESSOR}")
    endif()
    set(_zip "${CMAKE_BINARY_DIR}/babylon_live_preview-${_plat}-${_arch}.zip")

    add_custom_command(TARGET ${target} POST_BUILD
        # Fresh staging tree.
        COMMAND ${CMAKE_COMMAND} -E rm -rf "${_pkg}"
        COMMAND ${CMAKE_COMMAND} -E make_directory "${_pkg}/bin"
        # Python package (copy the dir, then drop any __pycache__).
        COMMAND ${CMAKE_COMMAND} -E copy_directory "${_addon_src}" "${_pkg}"
        COMMAND ${CMAKE_COMMAND} -E rm -rf "${_pkg}/__pycache__"
        # Native module + its staged Scripts next to it.
        COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:${target}>" "${_pkg}/bin/"
        COMMAND ${CMAKE_COMMAND} -E copy_directory "$<TARGET_FILE_DIR:${target}>/Scripts" "${_pkg}/bin/Scripts"
        # Zip it (archive paths relative to the staging root → top-level babylon_live_preview/).
        COMMAND ${CMAKE_COMMAND} -E tar cf "${_zip}" --format=zip babylon_live_preview
        WORKING_DIRECTORY "${_stage}"
        COMMENT "Packaging Blender add-on -> ${_zip}"
        VERBATIM)
endfunction()
