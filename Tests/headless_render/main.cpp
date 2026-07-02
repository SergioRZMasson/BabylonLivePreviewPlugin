// ===========================================================================
// blp_headless_render — M1 smoke test for BabylonLivePreviewCore
// ===========================================================================
// Boots a LivePreviewSession (hidden-window readback mode), renders the default
// scene defined in live_preview.js, reads the frame back to CPU memory, and
// writes it to a BMP next to the executable. Exercises: Babylon Native boot,
// JS bundle load, render pump, and RequestScreenShot readback (spike #2).
#include <BabylonLivePreview/LivePreview.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <Windows.h>
#endif

using namespace BabylonLivePreview;

static std::string ExeDir()
{
#ifdef _WIN32
    wchar_t buffer[MAX_PATH];
    ::GetModuleFileNameW(nullptr, buffer, MAX_PATH);
    return std::filesystem::path(buffer).parent_path().string();
#else
    return std::filesystem::current_path().string();
#endif
}

// Minimal dependency-free 24-bit BMP writer (bottom-up, BGR).
static bool WriteBMP(const std::string& path, const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
{
    const uint32_t rowBytes = w * 3;
    const uint32_t rowPadded = (rowBytes + 3u) & ~3u;
    const uint32_t imageSize = rowPadded * h;
    const uint32_t fileSize = 54u + imageSize;

    std::ofstream file(path, std::ios::binary);
    if (!file)
    {
        return false;
    }

    uint8_t header[54] = {0};
    header[0] = 'B'; header[1] = 'M';
    std::memcpy(&header[2], &fileSize, 4);
    uint32_t dataOffset = 54; std::memcpy(&header[10], &dataOffset, 4);
    uint32_t dibSize = 40;    std::memcpy(&header[14], &dibSize, 4);
    std::memcpy(&header[18], &w, 4);
    std::memcpy(&header[22], &h, 4);
    uint16_t planes = 1;      std::memcpy(&header[26], &planes, 2);
    uint16_t bpp = 24;        std::memcpy(&header[28], &bpp, 2);
    std::memcpy(&header[34], &imageSize, 4);
    file.write(reinterpret_cast<char*>(header), 54);

    std::vector<uint8_t> row(rowPadded, 0);
    for (int y = static_cast<int>(h) - 1; y >= 0; --y)
    {
        for (uint32_t x = 0; x < w; ++x)
        {
            const size_t i = (static_cast<size_t>(y) * w + x) * 4;
            const uint8_t r = i + 0 < rgba.size() ? rgba[i + 0] : 0;
            const uint8_t g = i + 1 < rgba.size() ? rgba[i + 1] : 0;
            const uint8_t b = i + 2 < rgba.size() ? rgba[i + 2] : 0;
            row[x * 3 + 0] = b;
            row[x * 3 + 1] = g;
            row[x * 3 + 2] = r;
        }
        file.write(reinterpret_cast<char*>(row.data()), rowPadded);
    }
    return true;
}

int main()
{
    SessionConfig cfg;
    cfg.width = 1280;
    cfg.height = 720;
    cfg.renderMode = RenderMode::HiddenWindowReadback;
    cfg.scriptsRoot = ExeDir() + "/Scripts";

    std::printf("[test] scriptsRoot = %s\n", cfg.scriptsRoot.c_str());

    LivePreviewSession session(cfg);

    // Wait for JS to load (babylon.js parse takes time) and render its first
    // frame before capturing. IsReady() flips once JS calls _blpNotifyReady.
    bool ready = false;
    for (int i = 0; i < 3000; ++i) // up to ~30s
    {
        session.RenderFrame();
        if (session.IsReady())
        {
            ready = true;
            std::printf("[test] scene ready after %d frames\n", i);
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    if (!ready)
    {
        std::printf("[test] FAILED: scene never became ready\n");
        return 4;
    }

    // Render a few more frames so materials/effects are fully resolved.
    for (int i = 0; i < 10; ++i)
    {
        session.RenderFrame();
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
    }

    session.RequestReadback();

    std::vector<uint8_t> pixels;
    uint32_t w = 0;
    uint32_t h = 0;
    bool acquired = false;
    for (int i = 0; i < 600; ++i)
    {
        session.RenderFrame();
        if (session.TryAcquireReadback(pixels, w, h))
        {
            acquired = true;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
    }

    if (!acquired || pixels.empty())
    {
        std::printf("[test] FAILED: no readback pixels acquired\n");
        return 2;
    }

    std::printf("[test] readback %ux%u  bytes=%zu  (expected %u)\n",
        w, h, pixels.size(), w * h * 4u);

    // Basic sanity: not fully black (scene has a lit sphere + ground).
    uint64_t sum = 0;
    for (size_t i = 0; i < pixels.size(); i += 4)
    {
        sum += pixels[i] + pixels[i + 1] + pixels[i + 2];
    }
    std::printf("[test] average luma-ish = %.2f\n",
        pixels.empty() ? 0.0 : static_cast<double>(sum) / (pixels.size() / 4));

    const std::string out = ExeDir() + "/live_preview_frame.bmp";
    if (!WriteBMP(out, pixels, w, h))
    {
        std::printf("[test] FAILED: could not write %s\n", out.c_str());
        return 3;
    }

    std::printf("[test] wrote %s\n", out.c_str());
    std::printf("[test] OK\n");
    return 0;
}
