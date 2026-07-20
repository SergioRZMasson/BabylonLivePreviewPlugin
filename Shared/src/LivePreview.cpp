// ===========================================================================
// BabylonLivePreview — LivePreviewSession implementation
// ===========================================================================
#include <BabylonLivePreview/LivePreview.h>

#include <Babylon/AppRuntime.h>
#include <Babylon/Graphics/Device.h>
#include <Babylon/Graphics/DeviceContext.h>
#include <Babylon/ScriptLoader.h>
#include <Babylon/Plugins/NativeEngine.h>
#include <Babylon/Plugins/NativeOptimizations.h>
#include <Babylon/Plugins/NativeInput.h>
#include <Babylon/Polyfills/Console.h>
#include <Babylon/Polyfills/Window.h>
#include <Babylon/Polyfills/XMLHttpRequest.h>
#include <Babylon/Polyfills/URL.h>
#include <Babylon/Polyfills/Canvas.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <fstream>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>

#ifdef _WIN32
#include <Windows.h>
#endif

#if defined(__APPLE__)
// Implemented in Platform_macOS.mm — creates/destroys the off-screen
// CAMetalLayer that backs the readable Metal swapchain.
extern "C" void* BlpCreateOffscreenMetalLayer(uint32_t width, uint32_t height);
extern "C" void BlpReleaseMetalLayer(void* layer);
#endif

namespace BabylonLivePreview
{
    namespace
    {
#ifdef _WIN32
        // A hidden top-level window used as the Babylon Native render surface for
        // the readback mode. It is never shown. bgfx still creates a swapchain on
        // it; RequestScreenShot reads the rendered frame back to CPU memory.
        HWND CreateHiddenWindow(uint32_t width, uint32_t height)
        {
            static const wchar_t* kClassName = L"BabylonLivePreviewHiddenWindow";
            HINSTANCE instance = ::GetModuleHandleW(nullptr);

            WNDCLASSEXW wc{};
            wc.cbSize = sizeof(wc);
            wc.lpfnWndProc = ::DefWindowProcW;
            wc.hInstance = instance;
            wc.lpszClassName = kClassName;
            ::RegisterClassExW(&wc); // ignore "already registered" on repeat

            return ::CreateWindowExW(
                0, kClassName, L"BabylonLivePreview", WS_OVERLAPPEDWINDOW,
                0, 0, static_cast<int>(width), static_cast<int>(height),
                nullptr, nullptr, instance, nullptr);
        }
#endif
    }

    // Readback state is heap-allocated so it can be co-owned by Babylon's
    // screenshot callback. If a readback completes after the session is
    // destroyed, the callback writes to this still-alive object rather than a
    // freed Impl (avoids a use-after-free crash on shutdown).
    struct ReadbackState
    {
        std::mutex mutex;
        std::vector<uint8_t> data;
        bool ready{false};
        bool pending{false};
    };

    struct LivePreviewSession::Impl
    {
        SessionConfig config{};

#ifdef _WIN32
        HWND hwnd{};
#endif

#ifdef __APPLE__
        void* metalLayer{}; // CAMetalLayer* — off-screen Metal render surface
#endif

        std::unique_ptr<Babylon::AppRuntime> runtime{};
        std::optional<Babylon::Graphics::Device> device{};
        std::optional<Babylon::Graphics::DeviceUpdate> update{};
        Babylon::Plugins::NativeInput* nativeInput{};
        std::unique_ptr<Babylon::Polyfills::Canvas> canvas{};

        // Readback state (co-owned with Babylon's screenshot callback).
        std::shared_ptr<ReadbackState> readback{std::make_shared<ReadbackState>()};

        // Set true by JS (_blpNotifyReady) after the first successful render.
        std::atomic<bool> sceneReady{false};

        // Trampoline for the _blpNotifyReady JS callback. The Impl pointer is
        // passed as the function's data so it targets the right session.
        static void NotifyReady(const Napi::CallbackInfo& info)
        {
            auto* impl = static_cast<Impl*>(info.Data());
            if (impl != nullptr)
            {
                impl->sceneReady.store(true);
            }
        }

        // Default environment (.env / IBL) bytes, loaded from disk in the ctor.
        // JS pulls these via _blpGetEnvironmentBytes (registered before scripts
        // run), avoiding ordering issues with the ScriptLoader eval queue.
        std::vector<uint8_t> envBytes{};

        static Napi::Value GetEnvironmentBytes(const Napi::CallbackInfo& info)
        {
            auto env = info.Env();
            auto* impl = static_cast<Impl*>(info.Data());
            if (impl == nullptr || impl->envBytes.empty())
            {
                return env.Null();
            }
            auto ab = Napi::ArrayBuffer::New(env, impl->envBytes.size());
            std::memcpy(ab.Data(), impl->envBytes.data(), impl->envBytes.size());
            return ab;
        }
    };

    LivePreviewSession::LivePreviewSession(const SessionConfig& config)
        : m_impl(std::make_unique<Impl>())
    {
        static const bool verbose = std::getenv("BLP_VERBOSE") != nullptr;
        auto chk = [](const char* s) { if (verbose) { std::fprintf(stderr, "[BLP-INIT] %s\n", s); std::fflush(stderr); } };
        m_impl->config = config;

        void* windowHandle = config.nativeWindow;
#ifdef _WIN32
        if (windowHandle == nullptr)
        {
            m_impl->hwnd = CreateHiddenWindow(config.width, config.height);
            windowHandle = m_impl->hwnd;
            if (verbose)
            {
                std::fprintf(stderr, "[BLP-INIT] hidden window hwnd=%p lastError=%lu\n",
                    (void*)m_impl->hwnd, (unsigned long)::GetLastError());
                std::fflush(stderr);
            }
        }
#elif defined(__APPLE__)
        if (windowHandle == nullptr)
        {
            m_impl->metalLayer = BlpCreateOffscreenMetalLayer(config.width, config.height);
            windowHandle = m_impl->metalLayer;
            if (verbose)
            {
                std::fprintf(stderr, "[BLP-INIT] offscreen CAMetalLayer=%p\n", windowHandle);
                std::fflush(stderr);
            }
        }
#endif
        chk("render surface created");

        Babylon::Graphics::Configuration graphicsConfig{};
        graphicsConfig.Window = reinterpret_cast<Babylon::Graphics::WindowT>(windowHandle);
        graphicsConfig.Width = static_cast<size_t>(config.width);
        graphicsConfig.Height = static_cast<size_t>(config.height);
        graphicsConfig.MSAASamples = config.msaaSamples;
#ifdef GRAPHICS_BACK_BUFFER_SUPPORT
        if (config.d3dDevice != nullptr)
        {
            graphicsConfig.Device = reinterpret_cast<Babylon::Graphics::DeviceT>(config.d3dDevice);
        }
#endif

        m_impl->device.emplace(graphicsConfig);
        chk("graphics device created");
        m_impl->update.emplace(m_impl->device->GetUpdate("update"));
        m_impl->device->StartRenderingCurrentFrame();
        m_impl->update->Start();
        chk("first frame started");

        Babylon::AppRuntime::Options runtimeOptions{};
        runtimeOptions.UnhandledExceptionHandler = [](const Napi::Error& error) {
            std::printf("[JS-EXCEPTION] %s\n", error.what());
            std::fflush(stdout);
        };
        m_impl->runtime = std::make_unique<Babylon::AppRuntime>(std::move(runtimeOptions));
        chk("app runtime created");

        // Load the default environment (IBL) asset now, before scripts run, so
        // the native getter registered below can hand it to JS on demand.
        {
            const std::string envPath = config.scriptsRoot + "/environment.env";
            std::ifstream envFile(envPath, std::ios::binary);
            if (envFile)
            {
                m_impl->envBytes.assign(
                    (std::istreambuf_iterator<char>(envFile)),
                    std::istreambuf_iterator<char>());
                if (verbose)
                {
                    std::fprintf(stderr, "[BLP-INIT] environment.env loaded (%zu bytes)\n",
                        m_impl->envBytes.size());
                    std::fflush(stderr);
                }
            }
            else if (verbose)
            {
                std::fprintf(stderr, "[BLP-INIT] no environment.env at %s\n", envPath.c_str());
            }
        }

        Impl* impl = m_impl.get();
        const bool enableLogging = config.enableLogging;

        m_impl->runtime->Dispatch([impl, enableLogging](Napi::Env env) {
            impl->device->AddToJavaScript(env);

            if (enableLogging)
            {
                Babylon::Polyfills::Console::Initialize(env, [](const char* message, auto) {
                    std::printf("[JS] %s\n", message);
                    std::fflush(stdout);
                });
            }

            Babylon::Polyfills::Window::Initialize(env);
            Babylon::Polyfills::XMLHttpRequest::Initialize(env);
            Babylon::Polyfills::URL::Initialize(env);

            impl->canvas = std::make_unique<Babylon::Polyfills::Canvas>(
                Babylon::Polyfills::Canvas::Initialize(env));

            Babylon::Plugins::NativeEngine::Initialize(env);
            Babylon::Plugins::NativeOptimizations::Initialize(env);
            impl->nativeInput = &Babylon::Plugins::NativeInput::CreateForJavaScript(env);

            // JS calls this once after the first frame renders (readiness signal).
            env.Global().Set("_blpNotifyReady",
                Napi::Function::New(env, &Impl::NotifyReady, "_blpNotifyReady", impl));

            // JS pulls the default environment (.env) bytes via this getter.
            env.Global().Set("_blpGetEnvironmentBytes",
                Napi::Function::New(env, &Impl::GetEnvironmentBytes, "_blpGetEnvironmentBytes", impl));
        });
        chk("init dispatched");

        // Load and evaluate the JS bundle. We read files ourselves (rather than
        // using app:///) so the same code works when hosted inside a DCC process
        // where the executable directory is not ours.
        Babylon::ScriptLoader loader{*m_impl->runtime};
        loader.Eval("document = {}", "");
        loader.Eval("console.log('[boot] js thread alive');", "boot");


        auto evalFile = [&](const std::string& name) {
            const std::string path = config.scriptsRoot + "/" + name;
            std::ifstream file(path, std::ios::binary);
            if (!file)
            {
                throw std::runtime_error("BabylonLivePreview: cannot open script: " + path);
            }
            std::stringstream ss;
            ss << file.rdbuf();
            loader.Eval(ss.str(), path);
        };

        evalFile("babylon.js");
        if (config.loadLoaders)
        {
            evalFile("babylonjs.loaders.js");
        }
        if (config.loadMaterials)
        {
            evalFile("babylonjs.materials.js");
        }
        evalFile("live_preview.js");
        chk("scripts queued; constructor done");
    }

    LivePreviewSession::~LivePreviewSession()
    {
        Impl* impl = m_impl.get();

        if (impl->device)
        {
            impl->update->Finish();
            impl->device->FinishRenderingCurrentFrame();
        }

        impl->nativeInput = nullptr;
        impl->runtime.reset();
        impl->canvas.reset();
        impl->update.reset();
        impl->device.reset();

#ifdef _WIN32
        if (impl->hwnd)
        {
            ::DestroyWindow(impl->hwnd);
            impl->hwnd = nullptr;
        }
#endif
#ifdef __APPLE__
        if (impl->metalLayer)
        {
            BlpReleaseMetalLayer(impl->metalLayer);
            impl->metalLayer = nullptr;
        }
#endif
    }

    void LivePreviewSession::Resize(uint32_t width, uint32_t height)
    {
        m_impl->config.width = width;
        m_impl->config.height = height;
        if (m_impl->device)
        {
            m_impl->device->UpdateSize(static_cast<size_t>(width), static_cast<size_t>(height));
        }
    }

    void LivePreviewSession::RenderFrame()
    {
        Impl* impl = m_impl.get();
        if (!impl->device)
        {
            return;
        }
        impl->update->Finish();
        impl->device->FinishRenderingCurrentFrame();
        impl->device->StartRenderingCurrentFrame();
        impl->update->Start();
    }

    void LivePreviewSession::SubmitCommands(const uint8_t* data, size_t size)
    {
        if (!m_impl->runtime || data == nullptr || size == 0)
        {
            return;
        }

        std::vector<uint8_t> buffer(data, data + size);
        m_impl->runtime->Dispatch([buffer = std::move(buffer)](Napi::Env env) {
            auto fn = env.Global().Get("applyCommands");
            if (fn.IsFunction())
            {
                auto arrayBuffer = Napi::ArrayBuffer::New(env, buffer.size());
                std::memcpy(arrayBuffer.Data(), buffer.data(), buffer.size());
                fn.As<Napi::Function>().Call({arrayBuffer});
            }
        });
    }

    void LivePreviewSession::Eval(const std::string& code)
    {
        if (!m_impl->runtime)
        {
            return;
        }
        m_impl->runtime->Dispatch([code](Napi::Env env) {
            auto fn = env.Global().Get("blpEval");
            if (fn.IsFunction())
            {
                fn.As<Napi::Function>().Call({Napi::String::New(env, code)});
            }
        });
    }

    void LivePreviewSession::RequestReadback()
    {
        Impl* impl = m_impl.get();
        if (!impl->runtime)
        {
            return;
        }

        auto rb = impl->readback; // shared_ptr copy captured by the callbacks
        {
            std::lock_guard<std::mutex> lock(rb->mutex);
            if (rb->pending)
            {
                return;
            }
            rb->pending = true;
            rb->ready = false;
        }

        impl->runtime->Dispatch([rb](Napi::Env env) {
            auto& context = Babylon::Graphics::DeviceContext::GetFromJavaScript(env);
            context.RequestScreenShot([rb](std::vector<uint8_t> data) {
                std::lock_guard<std::mutex> lock(rb->mutex);
                rb->data = std::move(data);
                rb->ready = true;
                rb->pending = false;
            });
        });
    }

    bool LivePreviewSession::TryAcquireReadback(std::vector<uint8_t>& outRGBA, uint32_t& width, uint32_t& height)
    {
        Impl* impl = m_impl.get();
        auto rb = impl->readback;
        std::lock_guard<std::mutex> lock(rb->mutex);
        if (!rb->ready)
        {
            return false;
        }
        outRGBA = std::move(rb->data);
        rb->data.clear();
        rb->ready = false;
        width = impl->config.width;
        height = impl->config.height;
        return true;
    }

    uint32_t LivePreviewSession::Width() const { return m_impl->config.width; }
    uint32_t LivePreviewSession::Height() const { return m_impl->config.height; }

    bool LivePreviewSession::IsReady() const { return m_impl->sceneReady.load(); }
}
