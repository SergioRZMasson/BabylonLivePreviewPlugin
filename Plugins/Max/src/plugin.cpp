// ===========================================================================
// BabylonLivePreview — 3ds Max plugin entry points + MAXScript interface
// ===========================================================================
// SDK-gated (needs MAX_SDK_ROOT). A Global Utility Plugin (GUP) hosts the live
// session; a FPStaticInterface exposes it to MAXScript:
//
//   BabylonLivePreview.start()
//   BabylonLivePreview.stop()
//   BabylonLivePreview.snapshot "C:/tmp/frame.bmp"
//   BabylonLivePreview.status()
//
// The functions drive the SHARED pipeline: MaxCapture (Max-specific extraction)
// -> SceneTranslator (shared) -> LivePreviewSession (shared Babylon Native host).
// Live display uses a Max Bitmap shown in its Virtual Frame Buffer (shader-free),
// updated by a Win32 timer that also pumps the render + incremental sync.
//
// This is a scaffold written against the documented 3ds Max SDK; it will build
// once MAX_SDK_ROOT points at a maxsdk, and may need minor per-version fixups.
#include "MaxCapture.h"

#include <BabylonLivePreview/LivePreview.h>
#include <BabylonLivePreview/SceneTranslation.h>

#include <max.h>
#include <iparamb2.h>
#include <gup.h>
#include <bitmap.h>

#include <chrono>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <Windows.h>

using namespace BabylonLivePreview;

// ---------------------------------------------------------------------------
// Class / interface ids. (Generated once; stable for this plugin.)
// ---------------------------------------------------------------------------
#define BLP_GUP_CLASS_ID   Class_ID(0x5f3a1c02, 0x2b7d4e11)
#define BLP_FP_INTERFACE_ID Interface_ID(0x5f3a1c03, 0x2b7d4e12)

extern HINSTANCE g_hInstance;
HINSTANCE g_hInstance = nullptr;

namespace
{
    // ------------------------------------------------------------------
    struct MaxLiveState
    {
        std::unique_ptr<LivePreviewSession> session;
        std::unique_ptr<SceneTranslator> translator;
        Bitmap* vfb = nullptr;
        BitmapInfo vfbInfo;
        UINT_PTR timer = 0;
        uint32_t width = 1280;
        uint32_t height = 720;
    };

    MaxLiveState g_state;

    std::string ModuleDir()
    {
        wchar_t buf[MAX_PATH];
        ::GetModuleFileNameW(g_hInstance, buf, MAX_PATH);
        std::wstring w(buf);
        size_t slash = w.find_last_of(L"\\/");
        std::wstring dir = (slash == std::wstring::npos) ? w : w.substr(0, slash);
        return std::string(dir.begin(), dir.end());
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
        // 3ds Max is right-handed Z-up (like Blender).
        g_state.translator = std::make_unique<SceneTranslator>(CoordinateBasis::ZUpRightHanded());
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
        Interface* ip = GetCOREInterface();
        std::vector<uint8_t> buf = MaxPlugin::CaptureScene(*g_state.translator, ip, incremental);
        g_state.session->SubmitCommands(buf.data(), buf.size());
    }

    // Show/refresh the readback in a Max Virtual Frame Buffer. RGBA8 top-to-bottom
    // -> BMM_Color_64 rows. Max's VFB origin is top-left, so no vertical flip.
    void DisplayReadback(const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
    {
        if (w == 0 || h == 0 || rgba.size() < static_cast<size_t>(w) * h * 4) return;

        if (!g_state.vfb || g_state.vfbInfo.Width() != static_cast<int>(w) ||
            g_state.vfbInfo.Height() != static_cast<int>(h))
        {
            if (g_state.vfb) { g_state.vfb->DeleteThis(); g_state.vfb = nullptr; }
            g_state.vfbInfo.SetName(_M("Babylon Live Preview"));
            g_state.vfbInfo.SetType(BMM_TRUE_32);
            g_state.vfbInfo.SetWidth(static_cast<WORD>(w));
            g_state.vfbInfo.SetHeight(static_cast<WORD>(h));
            g_state.vfbInfo.SetFlags(MAP_HAS_ALPHA);
            g_state.vfb = TheManager->Create(&g_state.vfbInfo);
            if (!g_state.vfb) return;
            g_state.vfb->Display(_M("Babylon Live Preview"));
        }

        std::vector<BMM_Color_64> line(w);
        for (uint32_t y = 0; y < h; ++y)
        {
            const uint8_t* src = &rgba[(static_cast<size_t>(y) * w) * 4];
            for (uint32_t x = 0; x < w; ++x)
            {
                // 8-bit -> 16-bit channel scale (v * 257 maps 255 -> 65535).
                line[x].r = static_cast<WORD>(src[x * 4 + 0] * 257);
                line[x].g = static_cast<WORD>(src[x * 4 + 1] * 257);
                line[x].b = static_cast<WORD>(src[x * 4 + 2] * 257);
                line[x].a = static_cast<WORD>(src[x * 4 + 3] * 257);
            }
            g_state.vfb->PutPixels(0, static_cast<int>(y), static_cast<int>(w), line.data());
        }
        g_state.vfb->RefreshWindow();
    }

    void CloseVfb()
    {
        if (g_state.vfb)
        {
            g_state.vfb->DeleteThis();
            g_state.vfb = nullptr;
        }
    }

    void CALLBACK TimerProc(HWND, UINT, UINT_PTR, DWORD)
    {
        if (!g_state.session || !g_state.translator) return;

        SyncScene(true);
        g_state.session->RenderFrame();

        std::vector<uint8_t> rgba;
        uint32_t rw = 0, rh = 0;
        if (g_state.session->TryAcquireReadback(rgba, rw, rh))
        {
            DisplayReadback(rgba, rw, rh);
        }
        g_state.session->RequestReadback();
    }

    // ------------------------------------------------------------------
    // Public operations (invoked by the MAXScript interface below).
    // ------------------------------------------------------------------
    bool Op_Start()
    {
        if (!EnsureSession()) return false;
        PumpUntilReady();
        SyncScene(false);
        for (int i = 0; i < 30; ++i)
        {
            g_state.session->RenderFrame();
            std::this_thread::sleep_for(std::chrono::milliseconds(8));
        }
        g_state.session->RequestReadback();
        if (g_state.timer == 0)
        {
            g_state.timer = ::SetTimer(nullptr, 0, 100, TimerProc); // ~10 Hz pump
        }
        return true;
    }

    void Op_Stop()
    {
        if (g_state.timer != 0)
        {
            ::KillTimer(nullptr, g_state.timer);
            g_state.timer = 0;
        }
        CloseVfb();
        g_state.translator.reset();
        g_state.session.reset();
    }

    void WriteBmp(const std::string& path, const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
    {
        const uint32_t row = ((w * 3) + 3) & ~3u;
        const uint32_t img = row * h;
        std::vector<uint8_t> file(54 + img, 0);
        auto put32 = [](uint8_t* p, uint32_t v) { p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF; p[2] = (v >> 16) & 0xFF; p[3] = (v >> 24) & 0xFF; };
        file[0] = 'B'; file[1] = 'M';
        put32(&file[2], 54 + img); put32(&file[10], 54); put32(&file[14], 40);
        put32(&file[18], w); put32(&file[22], h);
        file[26] = 1; file[28] = 24; put32(&file[34], img);
        for (uint32_t y = 0; y < h; ++y)
        {
            const uint32_t srcRow = h - 1 - y;
            uint8_t* dst = &file[54 + y * row];
            for (uint32_t x = 0; x < w; ++x)
            {
                const uint8_t* s = &rgba[(static_cast<size_t>(srcRow) * w + x) * 4];
                dst[x * 3 + 0] = s[2]; dst[x * 3 + 1] = s[1]; dst[x * 3 + 2] = s[0];
            }
        }
        std::ofstream f(path, std::ios::binary);
        if (f) f.write(reinterpret_cast<const char*>(file.data()), file.size());
    }

    bool Op_Snapshot(const std::string& path)
    {
        if (!EnsureSession()) return false;
        PumpUntilReady();
        SyncScene(false);
        for (int i = 0; i < 40; ++i)
        {
            g_state.session->RenderFrame();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        g_state.session->RequestReadback();
        std::vector<uint8_t> rgba;
        uint32_t rw = 0, rh = 0;
        for (int i = 0; i < 800; ++i)
        {
            g_state.session->RenderFrame();
            if (g_state.session->TryAcquireReadback(rgba, rw, rh)) { WriteBmp(path, rgba, rw, rh); return true; }
            std::this_thread::sleep_for(std::chrono::milliseconds(8));
        }
        return false;
    }
} // namespace

// ---------------------------------------------------------------------------
// MAXScript static interface: BabylonLivePreview.{start,stop,snapshot,status}
// ---------------------------------------------------------------------------
enum { blp_start, blp_stop, blp_snapshot, blp_status };

class BlpStaticInterface : public FPStaticInterface
{
public:
    DECLARE_DESCRIPTOR(BlpStaticInterface)

    BEGIN_FUNCTION_MAP
        FN_0(blp_start, TYPE_BOOL, StartFn)
        VFN_0(blp_stop, StopFn)
        FN_1(blp_snapshot, TYPE_BOOL, SnapshotFn, TYPE_STRING)
        FN_0(blp_status, TYPE_BOOL, StatusFn)
    END_FUNCTION_MAP

    bool StartFn() { return Op_Start(); }
    void StopFn() { Op_Stop(); }
    bool SnapshotFn(const MCHAR* path)
    {
#ifdef UNICODE
        int len = ::WideCharToMultiByte(CP_UTF8, 0, path, -1, nullptr, 0, nullptr, nullptr);
        std::string p(len > 0 ? len - 1 : 0, '\0');
        if (len > 0) ::WideCharToMultiByte(CP_UTF8, 0, path, -1, p.data(), len, nullptr, nullptr);
#else
        std::string p(path ? path : "");
#endif
        return Op_Snapshot(p);
    }
    bool StatusFn() { return g_state.session != nullptr; }
};

static BlpStaticInterface g_blpInterface(
    BLP_FP_INTERFACE_ID, _M("BabylonLivePreview"), 0, nullptr, FP_CORE,
    blp_start, _M("start"), 0, TYPE_BOOL, 0, 0,
    blp_stop, _M("stop"), 0, TYPE_VOID, 0, 0,
    blp_snapshot, _M("snapshot"), 0, TYPE_BOOL, 0, 1,
        _M("path"), 0, TYPE_STRING,
    blp_status, _M("status"), 0, TYPE_BOOL, 0, 0,
    p_end);

// ---------------------------------------------------------------------------
// GUP: keeps the plugin resident and cleans up on shutdown.
// ---------------------------------------------------------------------------
class BlpGup : public GUP
{
public:
    DWORD Start() override { return GUPRESULT_KEEP; }
    void Stop() override { Op_Stop(); }
    void DeleteThis() override {}
};

class BlpGupClassDesc : public ClassDesc2
{
public:
    int IsPublic() override { return TRUE; }
    void* Create(BOOL) override { static BlpGup gup; return &gup; }
    const MCHAR* ClassName() override { return _M("BabylonLivePreview"); }
    const MCHAR* NonLocalizedClassName() override { return _M("BabylonLivePreview"); }
    SClass_ID SuperClassID() override { return GUP_CLASS_ID; }
    Class_ID ClassID() override { return BLP_GUP_CLASS_ID; }
    const MCHAR* Category() override { return _M(""); }
};

static BlpGupClassDesc g_gupClassDesc;

// ---------------------------------------------------------------------------
// DLL entry points.
// ---------------------------------------------------------------------------
BOOL WINAPI DllMain(HINSTANCE hinstDLL, ULONG fdwReason, LPVOID)
{
    if (fdwReason == DLL_PROCESS_ATTACH)
    {
        g_hInstance = hinstDLL;
        ::DisableThreadLibraryCalls(hinstDLL);
    }
    return TRUE;
}

extern "C" __declspec(dllexport) const MCHAR* LibDescription()
{
    return _M("Babylon Live Preview for 3ds Max");
}

extern "C" __declspec(dllexport) int LibNumberClasses() { return 1; }

extern "C" __declspec(dllexport) ClassDesc* LibClassDesc(int i)
{
    return (i == 0) ? &g_gupClassDesc : nullptr;
}

extern "C" __declspec(dllexport) ULONG LibVersion() { return VERSION_3DSMAX; }

extern "C" __declspec(dllexport) int LibInitialize() { return TRUE; }

extern "C" __declspec(dllexport) int LibShutdown()
{
    Op_Stop();
    return TRUE;
}
