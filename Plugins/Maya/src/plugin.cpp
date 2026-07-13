// ===========================================================================
// BabylonLivePreview — Maya plugin entry points + command
// ===========================================================================
// Registers the `babylonLivePreview` MPxCommand. Flags:
//   -start / -stop            : create/destroy a persistent live-preview session
//   -snapshot <filepath>      : capture the scene, render one frame, write a BMP
//   -dumpbuffer <filepath>    : capture the scene, write the raw protocol buffer
//   -width <n> / -height <n>  : render resolution (default 1280x720)
//   -status                   : print whether a session is live
//
// The command drives the SHARED pipeline: MayaCapture (Maya-specific extraction)
// -> SceneTranslator (shared) -> LivePreviewSession (shared Babylon Native host).
// Live in-viewport display (MRenderOverride) is the next milestone; -snapshot
// validates the whole pipeline inside Maya today.
#include "MayaCapture.h"

#include <BabylonLivePreview/LivePreview.h>
#include <BabylonLivePreview/SceneTranslation.h>

#include <maya/MArgDatabase.h>
#include <maya/MFnPlugin.h>
#include <maya/MGlobal.h>
#include <maya/MPxCommand.h>
#include <maya/MRenderView.h>
#include <maya/MSyntax.h>
#include <maya/MTimerMessage.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <Windows.h>
#endif

using namespace BabylonLivePreview;

namespace
{
    // ------------------------------------------------------------------
    // Persistent plugin state (single active session for now).
    // ------------------------------------------------------------------
    struct PluginState
    {
        std::unique_ptr<LivePreviewSession> session;
        std::unique_ptr<SceneTranslator> translator;
        MCallbackId timerId = 0;
        uint32_t width = 1280;
        uint32_t height = 720;
        // Live display via Maya's Render View (shader-free; absent in batch mode).
        bool renderViewActive = false;
        uint32_t rvWidth = 0;
        uint32_t rvHeight = 0;
    };

    PluginState g_state;

    std::string ModuleDir()
    {
#ifdef _WIN32
        HMODULE mod = nullptr;
        ::GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&ModuleDir), &mod);
        wchar_t buf[MAX_PATH];
        ::GetModuleFileNameW(mod, buf, MAX_PATH);
        std::wstring w(buf);
        size_t slash = w.find_last_of(L"\\/");
        std::wstring dir = (slash == std::wstring::npos) ? w : w.substr(0, slash);
        std::string out(dir.begin(), dir.end());
        return out;
#else
        return ".";
#endif
    }

    void WriteBmp(const std::string& path, const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
    {
        const uint32_t row = ((w * 3) + 3) & ~3u;
        const uint32_t img = row * h;
        std::ofstream f(path, std::ios::binary);
        if (!f) return;
        auto u32 = [&](uint32_t v) { f.put(v & 0xFF).put((v >> 8) & 0xFF).put((v >> 16) & 0xFF).put((v >> 24) & 0xFF); };
        auto u16 = [&](uint16_t v) { f.put(v & 0xFF).put((v >> 8) & 0xFF); };
        f.put('B').put('M'); u32(54 + img); u16(0); u16(0); u32(54);
        u32(40); u32(w); u32(h); u16(1); u16(24); u32(0); u32(img); u32(0); u32(0); u32(0); u32(0);
        std::vector<uint8_t> line(row, 0);
        for (int y = static_cast<int>(h) - 1; y >= 0; --y)
        {
            for (uint32_t x = 0; x < w; ++x)
            {
                size_t i = (static_cast<size_t>(y) * w + x) * 4;
                line[x * 3 + 0] = rgba[i + 2];
                line[x * 3 + 1] = rgba[i + 1];
                line[x * 3 + 2] = rgba[i + 0];
            }
            f.write(reinterpret_cast<const char*>(line.data()), row);
        }
    }

    bool EnsureSession()
    {
        if (g_state.session) return true;
        SessionConfig cfg;
        cfg.width = g_state.width;
        cfg.height = g_state.height;
        cfg.renderMode = RenderMode::HiddenWindowReadback;
        cfg.scriptsRoot = ModuleDir() + "\\Scripts";
        cfg.enableLogging = true;
        try
        {
            g_state.session = std::make_unique<LivePreviewSession>(cfg);
        }
        catch (...)
        {
            g_state.session.reset();
            return false;
        }
        // Maya is right-handed Y-up.
        g_state.translator = std::make_unique<SceneTranslator>(CoordinateBasis::YUpRightHanded());
        return true;
    }

    void PumpUntilReady()
    {
        for (int i = 0; i < 4000 && !g_state.session->IsReady(); ++i)
        {
            g_state.session->RenderFrame();
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }

    void SyncScene(bool incremental)
    {
        std::vector<uint8_t> buf = MayaPlugin::CaptureScene(
            *g_state.translator, g_state.width, g_state.height, incremental);
        g_state.session->SubmitCommands(buf.data(), buf.size());
    }

    // Push a CPU readback (tightly-packed RGBA8, top-to-bottom) to Maya's Render
    // View. RV_PIXEL is float RGBA in 0..255; the Render View origin is bottom-
    // left, so rows are flipped. No-op in batch mode (no render editor).
    void PushToRenderView(const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
    {
        if (w == 0 || h == 0 || rgba.size() < static_cast<size_t>(w) * h * 4) return;
        if (!MRenderView::doesRenderEditorExist()) return;

        if (!g_state.renderViewActive || w != g_state.rvWidth || h != g_state.rvHeight)
        {
            if (MRenderView::startRender(w, h, false, true) != MS::kSuccess) return;
            g_state.rvWidth = w;
            g_state.rvHeight = h;
            g_state.renderViewActive = true;
        }

        std::vector<RV_PIXEL> pixels(static_cast<size_t>(w) * h);
        for (uint32_t y = 0; y < h; ++y)
        {
            const uint32_t srcRow = h - 1 - y; // flip vertically for bottom-left origin
            for (uint32_t x = 0; x < w; ++x)
            {
                const uint8_t* s = &rgba[(static_cast<size_t>(srcRow) * w + x) * 4];
                RV_PIXEL& d = pixels[static_cast<size_t>(y) * w + x];
                d.r = static_cast<float>(s[0]);
                d.g = static_cast<float>(s[1]);
                d.b = static_cast<float>(s[2]);
                d.a = static_cast<float>(s[3]);
            }
        }
        MRenderView::updatePixels(0, w - 1, 0, h - 1, pixels.data());
        MRenderView::refresh(0, w - 1, 0, h - 1);
    }

    void StopRenderView()
    {
        if (g_state.renderViewActive && MRenderView::doesRenderEditorExist())
        {
            MRenderView::endRender();
        }
        g_state.renderViewActive = false;
        g_state.rvWidth = 0;
        g_state.rvHeight = 0;
    }

    void TimerCallback(float, float, void*)
    {
        if (!g_state.session || !g_state.translator) return;

        // Push scene edits, advance a frame, and display the previous readback.
        SyncScene(true);
        g_state.session->RenderFrame();

        // Acquire the frame requested last tick BEFORE requesting the next one
        // (RequestReadback clears the ready flag), then display it.
        std::vector<uint8_t> rgba;
        uint32_t rw = 0, rh = 0;
        if (g_state.session->TryAcquireReadback(rgba, rw, rh))
        {
            PushToRenderView(rgba, rw, rh);
        }
        g_state.session->RequestReadback();
    }

    // ------------------------------------------------------------------
    class LivePreviewCommand : public MPxCommand
    {
    public:
        static void* Creator() { return new LivePreviewCommand(); }

        static MSyntax NewSyntax()
        {
            MSyntax s;
            s.addFlag("-s", "-start");
            s.addFlag("-e", "-stop");
            s.addFlag("-st", "-status");
            s.addFlag("-snp", "-snapshot", MSyntax::kString);
            s.addFlag("-db", "-dumpbuffer", MSyntax::kString);
            s.addFlag("-w", "-width", MSyntax::kUnsigned);
            s.addFlag("-h", "-height", MSyntax::kUnsigned);
            return s;
        }

        MStatus doIt(const MArgList& args) override
        {
            MStatus st;
            MArgDatabase db(syntax(), args, &st);
            if (!st) return st;

            if (db.isFlagSet("-w")) db.getFlagArgument("-w", 0, g_state.width);
            if (db.isFlagSet("-h")) db.getFlagArgument("-h", 0, g_state.height);

            if (db.isFlagSet("-st"))
            {
                MGlobal::displayInfo(g_state.session ? "BabylonLivePreview: session ACTIVE"
                                                     : "BabylonLivePreview: no session");
                return MS::kSuccess;
            }

            if (db.isFlagSet("-e"))
            {
                Stop();
                MGlobal::displayInfo("BabylonLivePreview: stopped");
                return MS::kSuccess;
            }

            if (db.isFlagSet("-snp"))
            {
                MString path;
                db.getFlagArgument("-snp", 0, path);
                return Snapshot(path.asChar());
            }

            if (db.isFlagSet("-db"))
            {
                MString path;
                db.getFlagArgument("-db", 0, path);
                return DumpBuffer(path.asChar());
            }

            if (db.isFlagSet("-s"))
            {
                return Start();
            }

            MGlobal::displayInfo("babylonLivePreview: use -start | -stop | -snapshot <path> | -status");
            return MS::kSuccess;
        }

    private:
        MStatus Start()
        {
            if (!EnsureSession())
            {
                displayError("BabylonLivePreview: failed to create session (check Scripts/ next to the .mll)");
                return MS::kFailure;
            }
            PumpUntilReady();
            SyncScene(false);
            for (int i = 0; i < 30; ++i) { g_state.session->RenderFrame(); std::this_thread::sleep_for(std::chrono::milliseconds(8)); }

            // Prime the readback pipeline so the first timer tick has a frame to
            // display in the Render View.
            g_state.session->RequestReadback();

            if (g_state.timerId == 0)
            {
                MStatus st;
                g_state.timerId = MTimerMessage::addTimerCallback(0.1f, TimerCallback, nullptr, &st);
            }
            MGlobal::displayInfo("BabylonLivePreview: started. Open the Render View (Windows > "
                "Rendering Editors > Render View) to see the live Babylon preview.");
            return MS::kSuccess;
        }

        void Stop()
        {
            if (g_state.timerId != 0)
            {
                MMessage::removeCallback(g_state.timerId);
                g_state.timerId = 0;
            }
            StopRenderView();
            g_state.translator.reset();
            g_state.session.reset();
        }

        // Diagnostic: capture the scene into a protocol buffer and write it to
        // disk WITHOUT booting a Babylon session. Lets headless tests decode the
        // exact bytes (geometry streams, texture channels) the producer emits.
        MStatus DumpBuffer(const std::string& path)
        {
            SceneTranslator tr(CoordinateBasis::YUpRightHanded());
            std::vector<uint8_t> buf =
                MayaPlugin::CaptureScene(tr, g_state.width, g_state.height, false);
            std::ofstream f(path, std::ios::binary);
            if (!f)
            {
                displayError(MString("BabylonLivePreview: cannot write ") + path.c_str());
                return MS::kFailure;
            }
            f.write(reinterpret_cast<const char*>(buf.data()), static_cast<std::streamsize>(buf.size()));
            MGlobal::displayInfo(MString("BabylonLivePreview: dumped ") + path.c_str());
            return MS::kSuccess;
        }

        MStatus Snapshot(const std::string& path)
        {
            if (!EnsureSession())
            {
                displayError("BabylonLivePreview: failed to create session");
                return MS::kFailure;
            }
            PumpUntilReady();
            SyncScene(false);
            for (int i = 0; i < 40; ++i) { g_state.session->RenderFrame(); std::this_thread::sleep_for(std::chrono::milliseconds(10)); }

            g_state.session->RequestReadback();
            std::vector<uint8_t> rgba;
            uint32_t rw = 0, rh = 0;
            bool got = false;
            for (int i = 0; i < 800; ++i)
            {
                g_state.session->RenderFrame();
                if (g_state.session->TryAcquireReadback(rgba, rw, rh)) { got = true; break; }
                std::this_thread::sleep_for(std::chrono::milliseconds(8));
            }
            if (!got)
            {
                displayError("BabylonLivePreview: readback timed out");
                return MS::kFailure;
            }
            WriteBmp(path, rgba, rw, rh);
            MGlobal::displayInfo(MString("BabylonLivePreview: wrote ") + path.c_str());
            return MS::kSuccess;
        }
    };
} // namespace

// ---------------------------------------------------------------------------
MStatus initializePlugin(MObject obj)
{
    MFnPlugin plugin(obj, "BabylonLivePreview", "0.1.0", "Any");
    return plugin.registerCommand("babylonLivePreview",
        LivePreviewCommand::Creator, LivePreviewCommand::NewSyntax);
}

MStatus uninitializePlugin(MObject obj)
{
    if (g_state.timerId != 0)
    {
        MMessage::removeCallback(g_state.timerId);
        g_state.timerId = 0;
    }
    if (g_state.renderViewActive && MRenderView::doesRenderEditorExist())
    {
        MRenderView::endRender();
    }
    g_state.renderViewActive = false;
    g_state.translator.reset();
    g_state.session.reset();
    MFnPlugin plugin(obj);
    return plugin.deregisterCommand("babylonLivePreview");
}
