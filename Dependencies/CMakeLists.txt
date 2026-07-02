# ---------------------------------------------------------------------------
# Babylon Native
#
# Prefer the in-repo submodule (Dependencies/BabylonNative). If it is not
# initialised, allow an external checkout via -DBABYLON_NATIVE_DIR=<path>.
# Babylon Native fetches its own dependencies (arcana, bgfx, glslang,
# JsRuntimeHost, SPIRV-Cross, ...) via CMake FetchContent at configure time.
# ---------------------------------------------------------------------------

set(BABYLON_NATIVE_DIR "" CACHE PATH "External Babylon Native checkout (overrides the in-repo submodule)")

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/BabylonNative/CMakeLists.txt")
    set(_bn_dir "${CMAKE_CURRENT_SOURCE_DIR}/BabylonNative")
elseif(BABYLON_NATIVE_DIR AND EXISTS "${BABYLON_NATIVE_DIR}/CMakeLists.txt")
    set(_bn_dir "${BABYLON_NATIVE_DIR}")
else()
    message(FATAL_ERROR
        "Babylon Native source not found.\n"
        "Run:  git submodule update --init  (from the repo root)\n"
        "or pass -DBABYLON_NATIVE_DIR=<path-to-BabylonNative>.")
endif()

message(STATUS "Babylon Native source: ${_bn_dir}")

# Trim what we build — plugins/apps/tests we don't need.
set(BABYLON_NATIVE_BUILD_APPS         OFF CACHE BOOL "" FORCE)
set(BABYLON_NATIVE_PLUGIN_TESTUTILS   OFF CACHE BOOL "" FORCE)
set(BABYLON_NATIVE_PLUGIN_SHADERTOOL  OFF CACHE BOOL "" FORCE)
set(BABYLON_NATIVE_PLUGIN_NATIVEXR    OFF CACHE BOOL "" FORCE)
set(BABYLON_NATIVE_PLUGIN_NATIVECAMERA OFF CACHE BOOL "" FORCE)
set(BABYLON_NATIVE_PLUGIN_NATIVETRACING OFF CACHE BOOL "" FORCE)

add_subdirectory("${_bn_dir}" "${CMAKE_BINARY_DIR}/_deps/BabylonNative-build")
