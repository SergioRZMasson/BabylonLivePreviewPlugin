// ===========================================================================
// BabylonLivePreview — C ABI implementation
// ===========================================================================
#include <BabylonLivePreview/c_api.h>
#include <BabylonLivePreview/LivePreview.h>

#include <vector>

using namespace BabylonLivePreview;

namespace
{
    // Owns the session plus a persistent readback buffer so the pointer returned
    // by blp_try_acquire_readback stays valid until the next acquire call.
    struct SessionWrapper
    {
        LivePreviewSession* session{};
        std::vector<uint8_t> lastReadback{};
        uint32_t width{};
        uint32_t height{};
    };
}

extern "C"
{
    BlpSession blp_create(const BlpConfig* config)
    {
        if (config == nullptr)
        {
            return nullptr;
        }

        SessionConfig cfg{};
        cfg.width = config->width ? config->width : 1280;
        cfg.height = config->height ? config->height : 720;
        cfg.renderMode = static_cast<RenderMode>(config->renderMode);
        cfg.scriptsRoot = config->scriptsRoot ? config->scriptsRoot : "";
        cfg.d3dDevice = config->d3dDevice;
        cfg.nativeWindow = config->nativeWindow;
        cfg.loadLoaders = config->loadLoaders != 0;
        cfg.loadMaterials = config->loadMaterials != 0;
        cfg.enableLogging = config->enableLogging != 0;
        cfg.msaaSamples = config->msaaSamples ? static_cast<uint8_t>(config->msaaSamples) : 4;

        auto* wrapper = new SessionWrapper();
        try
        {
            wrapper->session = new LivePreviewSession(cfg);
        }
        catch (...)
        {
            delete wrapper;
            return nullptr;
        }
        return wrapper;
    }

    void blp_destroy(BlpSession session)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper == nullptr)
        {
            return;
        }
        delete wrapper->session;
        delete wrapper;
    }

    void blp_resize(BlpSession session, uint32_t width, uint32_t height)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper && wrapper->session)
        {
            wrapper->session->Resize(width, height);
        }
    }

    void blp_render_frame(BlpSession session)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper && wrapper->session)
        {
            wrapper->session->RenderFrame();
        }
    }

    int32_t blp_is_ready(BlpSession session)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        return (wrapper && wrapper->session && wrapper->session->IsReady()) ? 1 : 0;
    }

    void blp_submit_commands(BlpSession session, const uint8_t* data, size_t size)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper && wrapper->session)
        {
            wrapper->session->SubmitCommands(data, size);
        }
    }

    void blp_eval(BlpSession session, const char* code)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper && wrapper->session && code)
        {
            wrapper->session->Eval(code);
        }
    }

    void blp_request_readback(BlpSession session)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (wrapper && wrapper->session)
        {
            wrapper->session->RequestReadback();
        }
    }

    int32_t blp_try_acquire_readback(BlpSession session,
        const uint8_t** outData, uint32_t* outWidth, uint32_t* outHeight, size_t* outSize)
    {
        auto* wrapper = static_cast<SessionWrapper*>(session);
        if (!wrapper || !wrapper->session)
        {
            return 0;
        }
        if (!wrapper->session->TryAcquireReadback(wrapper->lastReadback, wrapper->width, wrapper->height))
        {
            return 0;
        }
        if (outData) *outData = wrapper->lastReadback.data();
        if (outWidth) *outWidth = wrapper->width;
        if (outHeight) *outHeight = wrapper->height;
        if (outSize) *outSize = wrapper->lastReadback.size();
        return 1;
    }
}
