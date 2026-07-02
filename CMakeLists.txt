cmake_minimum_required(VERSION 3.21)

project(BabylonLivePreview VERSION 0.1.0 LANGUAGES C CXX)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
option(BLP_BUILD_BLENDER "Build the Blender plugin (C-API DLL)" ON)
option(BLP_BUILD_MAX     "Build the 3ds Max plugin"             OFF)
option(BLP_BUILD_MAYA    "Build the Maya plugin"                OFF)
option(BLP_BUILD_TESTS   "Build headless test executables"      ON)

if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Babylon Native selects its JS engine through this variable (V8 on Windows).
if(NOT NAPI_JAVASCRIPT_ENGINE)
    set(NAPI_JAVASCRIPT_ENGINE "V8" CACHE STRING "JavaScript engine for Node-API (V8|JSCore|Chakra)")
endif()

# When this DLL is loaded into a host that ships an OLDER MSVC runtime (e.g.
# Blender bundles a pre-17.10 msvcp140.dll in blender.crt/), the VS 2022 17.10+
# constexpr std::mutex crashes on its first lock (std::mutex::lock derefs null in
# the older runtime). This define reverts std::mutex/condition_variable to the
# ABI compatible with older runtimes. It MUST apply to the whole build (Babylon
# Native included — the first crashing mutex is in its DeviceImpl), so it is set
# here before any add_subdirectory().
if(MSVC)
    add_compile_definitions(_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)
endif()

include(BlpHelpers)

add_subdirectory(Dependencies)
add_subdirectory(Shared)

if(BLP_BUILD_BLENDER)
    add_subdirectory(Plugins/Blender)
endif()
if(BLP_BUILD_MAX)
    add_subdirectory(Plugins/Max)
endif()
if(BLP_BUILD_MAYA)
    add_subdirectory(Plugins/Maya)
endif()
if(BLP_BUILD_TESTS)
    add_subdirectory(Tests/headless_render)
    add_subdirectory(Tests/protocol_scene)
endif()

if(MSVC)
    set_property(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR} PROPERTY VS_STARTUP_PROJECT blp_headless_render)
endif()
