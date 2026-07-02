// ===========================================================================
// BabylonLivePreview — stable C ABI
// ===========================================================================
// A thin extern "C" wrapper over LivePreviewSession so hosts that cannot
// consume C++ directly (notably the Blender Python add-on via ctypes/pybind11)
// can drive the core. Max/Maya use the C++ API directly.
#pragma once

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32) && defined(BLP_BUILD_DLL)
#define BLP_API __declspec(dllexport)
#elif defined(_WIN32) && defined(BLP_USE_DLL)
#define BLP_API __declspec(dllimport)
#else
#define BLP_API
#endif

#ifdef __cplusplus
extern "C"
{
#endif

    typedef void* BlpSession;

    typedef struct BlpConfig
    {
        uint32_t width;
        uint32_t height;
        int32_t renderMode;      // matches BabylonLivePreview::RenderMode
        const char* scriptsRoot; // UTF-8, folder with babylon.max.js + live_preview.js
        void* d3dDevice;         // optional ID3D11Device*
        void* nativeWindow;      // optional HWND
        int32_t loadLoaders;     // bool
        int32_t loadMaterials;   // bool
        int32_t enableLogging;   // bool
        uint32_t msaaSamples;
    } BlpConfig;

    // Lifecycle
    BLP_API BlpSession blp_create(const BlpConfig* config);
    BLP_API void blp_destroy(BlpSession session);
    BLP_API void blp_resize(BlpSession session, uint32_t width, uint32_t height);
    BLP_API void blp_render_frame(BlpSession session);

    // True (1) once JS has rendered its first frame (scene is live).
    BLP_API int32_t blp_is_ready(BlpSession session);

    // Scene sync (host -> Babylon)
    BLP_API void blp_submit_commands(BlpSession session, const uint8_t* data, size_t size);
    BLP_API void blp_eval(BlpSession session, const char* code);

    // Readback (Babylon -> host). Request, then poll try_acquire each frame.
    // On success returns 1 and sets *outData to an internal buffer valid until
    // the next call to blp_try_acquire_readback on the same session.
    BLP_API void blp_request_readback(BlpSession session);
    BLP_API int32_t blp_try_acquire_readback(BlpSession session,
        const uint8_t** outData, uint32_t* outWidth, uint32_t* outHeight, size_t* outSize);

#ifdef __cplusplus
}
#endif
