# ---------------------------------------------------------------------------
# BabylonLivePreviewCore
#
# DCC-agnostic reusable core: owns the Babylon Native lifecycle, JS bundle
# loading, the render-target / readback strategy, and the scene-sync protocol.
# Consumed as a STATIC library by each per-DCC plugin (Blender/Max/Maya) and by
# the headless tests.
# ---------------------------------------------------------------------------

add_library(BabylonLivePreviewCore STATIC
    src/LivePreview.cpp
    src/SceneProtocol.cpp
    src/c_api.cpp
    include/BabylonLivePreview/LivePreview.h
    include/BabylonLivePreview/SceneProtocol.h
    include/BabylonLivePreview/c_api.h)

target_include_directories(BabylonLivePreviewCore PUBLIC include)

target_compile_features(BabylonLivePreviewCore PUBLIC cxx_std_20)

# Babylon Native targets. GraphicsDeviceContext exposes the InternalInclude
# headers (DeviceContext.h) needed for RequestScreenShot-based readback.
target_link_libraries(BabylonLivePreviewCore
    PUBLIC AppRuntime
    PUBLIC GraphicsDevice
    PUBLIC GraphicsDeviceContext
    PUBLIC NativeEngine
    PUBLIC NativeOptimizations
    PUBLIC NativeInput
    PUBLIC Console
    PUBLIC Window
    PUBLIC ScriptLoader
    PUBLIC XMLHttpRequest
    PUBLIC URL
    PUBLIC Canvas)

if(WIN32)
    target_compile_definitions(BabylonLivePreviewCore PRIVATE
        NOMINMAX WIN32_LEAN_AND_MEAN UNICODE _UNICODE)
    target_link_libraries(BabylonLivePreviewCore PUBLIC d3d11 dxgi)
endif()

set_property(TARGET BabylonLivePreviewCore PROPERTY FOLDER "BabylonLivePreview")

# Assemble the JS bundle (babylon.max.js + live_preview.js) in the build tree.
blp_setup_scripts()
