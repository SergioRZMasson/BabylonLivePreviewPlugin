// ===========================================================================
// BabylonLivePreview — shared core public C++ API
// ===========================================================================
// A LivePreviewSession embeds Babylon Native, loads the Babylon.js + live
// preview JS bundle, renders the scene, and exposes the rendered frame plus a
// scene-sync channel. This type is DCC-agnostic; per-DCC plugins wrap it.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace BabylonLivePreview
{
    // How the rendered frame is produced / handed back to the host.
    enum class RenderMode : int
    {
        // M1 (safe, portable): hidden Win32 window + Babylon's RequestScreenShot
        // to read the frame back to CPU memory (RGBA8).
        HiddenWindowReadback = 0,

        // M5 (fast, Windows/D3D11 only): render into a shared ID3D11Texture2D and
        // hand the host a shared handle (no CPU copy). Not implemented yet.
        D3D11SharedTexture = 1,
    };

    struct SessionConfig
    {
        uint32_t width = 1280;
        uint32_t height = 720;
        RenderMode renderMode = RenderMode::HiddenWindowReadback;

        // Folder containing babylon.max.js and live_preview.js (+ optional
        // loaders/materials). Required — the core reads and evaluates these.
        std::string scriptsRoot;

        // Optional: an existing ID3D11Device to share with the DCC (D3D11SharedTexture).
        void* d3dDevice = nullptr;

        // Optional: an existing native window handle (HWND). If null and the mode
        // needs a window, the core creates a hidden one.
        void* nativeWindow = nullptr;

        bool loadLoaders = true;    // babylonjs.loaders.js (glTF/OBJ, ...)
        bool loadMaterials = true;  // babylonjs.materials.js
        bool enableLogging = true;  // pipe JS console to stdout
        uint8_t msaaSamples = 4;
    };

    class LivePreviewSession
    {
    public:
        explicit LivePreviewSession(const SessionConfig& config);
        ~LivePreviewSession();

        LivePreviewSession(const LivePreviewSession&) = delete;
        LivePreviewSession& operator=(const LivePreviewSession&) = delete;

        // Resize the render surface.
        void Resize(uint32_t width, uint32_t height);

        // Pump exactly one frame (finish previous, start next). Call from the
        // host's redraw/timer on a consistent thread.
        void RenderFrame();

        // --- Scene sync (host -> Babylon) ---------------------------------
        // Submit an encoded command buffer (see SceneProtocol.h) to mutate the
        // live scene. Thread-safe; applied on the JS thread.
        void SubmitCommands(const uint8_t* data, size_t size);

        // Debug/escape hatch: evaluate arbitrary JS in the scene context.
        void Eval(const std::string& code);

        // --- Readback (Babylon -> host) -----------------------------------
        // Ask Babylon to capture the next rendered frame. Non-blocking.
        void RequestReadback();

        // Poll for a completed readback. Returns true and fills `outRGBA`
        // (tightly packed RGBA8, width*height*4) once available.
        bool TryAcquireReadback(std::vector<uint8_t>& outRGBA, uint32_t& width, uint32_t& height);

        uint32_t Width() const;
        uint32_t Height() const;

        // True once JS has rendered at least one frame (scene is live).
        bool IsReady() const;

    private:
        struct Impl;
        std::unique_ptr<Impl> m_impl;
    };
}
