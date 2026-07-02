// ===========================================================================
// blp_protocol_scene — M2 test: build a scene entirely via protocol commands
// ===========================================================================
// Constructs a known scene (red box + green box, hemispheric light, arc-rotate
// camera, dark-blue clear color) by submitting a CommandEncoder buffer to a
// LivePreviewSession, then reads the frame back and asserts that it contains
// distinct red, green and background pixels. Proves upsert_node +
// upsert_mesh_geometry + upsert_material + upsert_light + set_camera round-trip.
#include <BabylonLivePreview/LivePreview.h>
#include <BabylonLivePreview/SceneProtocol.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
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

struct MeshData
{
    std::vector<float> positions;
    std::vector<float> normals;
    std::vector<uint32_t> indices;
};

// A unit cube centered at the origin, 24 verts (per-face normals), 36 indices.
static MeshData MakeBox(float size)
{
    const float h = size * 0.5f;
    struct Face { float n[3]; float v[4][3]; };
    const Face faces[6] = {
        {{ 1, 0, 0}, {{ h,-h,-h},{ h, h,-h},{ h, h, h},{ h,-h, h}}},
        {{-1, 0, 0}, {{-h,-h, h},{-h, h, h},{-h, h,-h},{-h,-h,-h}}},
        {{ 0, 1, 0}, {{-h, h,-h},{-h, h, h},{ h, h, h},{ h, h,-h}}},
        {{ 0,-1, 0}, {{-h,-h, h},{-h,-h,-h},{ h,-h,-h},{ h,-h, h}}},
        {{ 0, 0, 1}, {{ h,-h, h},{ h, h, h},{-h, h, h},{-h,-h, h}}},
        {{ 0, 0,-1}, {{-h,-h,-h},{-h, h,-h},{ h, h,-h},{ h,-h,-h}}},
    };
    MeshData m;
    for (const auto& f : faces)
    {
        const uint32_t base = static_cast<uint32_t>(m.positions.size() / 3);
        for (int i = 0; i < 4; ++i)
        {
            m.positions.insert(m.positions.end(), {f.v[i][0], f.v[i][1], f.v[i][2]});
            m.normals.insert(m.normals.end(), {f.n[0], f.n[1], f.n[2]});
        }
        m.indices.insert(m.indices.end(), {base + 0, base + 1, base + 2, base + 0, base + 2, base + 3});
    }
    return m;
}

static bool WriteBMP(const std::string& path, const std::vector<uint8_t>& rgba, uint32_t w, uint32_t h)
{
    const uint32_t rowPadded = ((w * 3) + 3u) & ~3u;
    const uint32_t imageSize = rowPadded * h;
    const uint32_t fileSize = 54u + imageSize;
    std::ofstream file(path, std::ios::binary);
    if (!file) return false;
    uint8_t hdr[54] = {0};
    hdr[0] = 'B'; hdr[1] = 'M';
    std::memcpy(&hdr[2], &fileSize, 4);
    uint32_t off = 54; std::memcpy(&hdr[10], &off, 4);
    uint32_t dib = 40; std::memcpy(&hdr[14], &dib, 4);
    std::memcpy(&hdr[18], &w, 4);
    std::memcpy(&hdr[22], &h, 4);
    uint16_t planes = 1; std::memcpy(&hdr[26], &planes, 2);
    uint16_t bpp = 24; std::memcpy(&hdr[28], &bpp, 2);
    std::memcpy(&hdr[34], &imageSize, 4);
    file.write(reinterpret_cast<char*>(hdr), 54);
    std::vector<uint8_t> row(rowPadded, 0);
    for (int y = static_cast<int>(h) - 1; y >= 0; --y)
    {
        for (uint32_t x = 0; x < w; ++x)
        {
            const size_t i = (static_cast<size_t>(y) * w + x) * 4;
            row[x * 3 + 0] = i + 2 < rgba.size() ? rgba[i + 2] : 0;
            row[x * 3 + 1] = i + 1 < rgba.size() ? rgba[i + 1] : 0;
            row[x * 3 + 2] = i + 0 < rgba.size() ? rgba[i + 0] : 0;
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

    LivePreviewSession session(cfg);

    // Wait for the JS engine + default scene to come up.
    bool ready = false;
    for (int i = 0; i < 3000; ++i)
    {
        session.RenderFrame();
        if (session.IsReady()) { ready = true; break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (!ready) { std::printf("[m2] FAILED: scene never ready\n"); return 4; }

    // ---- Build a known scene purely from protocol commands ----
    const MeshData box = MakeBox(1.4f);
    CommandEncoder enc;
    enc.ResetScene();
    enc.SetClearColor(0.05f, 0.06f, 0.12f, 1.0f); // dark blue (not red/green)
    enc.SetCameraArcRotate(-1.5707963f, 1.15f, 9.0f, 0.0f, 0.5f, 0.0f);
    enc.UpsertLight(100, LightType::Hemispheric, 0.3f, 1.0f, 0.2f, 1.0f, 1.0f, 1.0f, 1.2f);

    // Red box on the left.
    enc.UpsertNode(1, 0, NodeKind::Mesh, "leftBox",
        -2.0f, 0.5f, 0.0f, 0, 0, 0, 1, 1, 1, 1);
    enc.UpsertMeshGeometry(1, box.positions.data(), static_cast<uint32_t>(box.positions.size() / 3),
        box.normals.data(), nullptr, box.indices.data(), static_cast<uint32_t>(box.indices.size()));
    enc.UpsertMaterial(1, 0.90f, 0.08f, 0.08f, 1.0f, 0.0f, 0.6f);

    // Green box on the right.
    enc.UpsertNode(2, 0, NodeKind::Mesh, "rightBox",
        2.0f, 0.5f, 0.0f, 0, 0, 0, 1, 1, 1, 1);
    enc.UpsertMeshGeometry(2, box.positions.data(), static_cast<uint32_t>(box.positions.size() / 3),
        box.normals.data(), nullptr, box.indices.data(), static_cast<uint32_t>(box.indices.size()));
    enc.UpsertMaterial(2, 0.08f, 0.80f, 0.10f, 1.0f, 0.0f, 0.6f);

    const std::vector<uint8_t> commands = enc.Finish();
    std::printf("[m2] submitting %zu-byte command buffer\n", commands.size());
    session.SubmitCommands(commands.data(), commands.size());

    // Let the commands apply and render a few frames.
    for (int i = 0; i < 30; ++i)
    {
        session.RenderFrame();
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    session.RequestReadback();
    std::vector<uint8_t> pixels;
    uint32_t w = 0, h = 0;
    bool got = false;
    for (int i = 0; i < 600; ++i)
    {
        session.RenderFrame();
        if (session.TryAcquireReadback(pixels, w, h)) { got = true; break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
    }
    if (!got || pixels.empty()) { std::printf("[m2] FAILED: no readback\n"); return 2; }

    // ---- Analyse: expect distinct red, green and background pixels ----
    int red = 0, green = 0, bg = 0;
    for (size_t i = 0; i + 3 < pixels.size(); i += 4)
    {
        const int r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
        if (r > g + 30 && r > b + 30) ++red;
        else if (g > r + 30 && g > b + 30) ++green;
        else if (b >= r && b > g && r < 60 && g < 60) ++bg; // dark-blue clear color
    }
    std::printf("[m2] pixels: red=%d green=%d background=%d\n", red, green, bg);

    WriteBMP(ExeDir() + "/protocol_scene.bmp", pixels, w, h);

    const bool pass = red > 1500 && green > 1500 && bg > 10000;
    std::printf("[m2] %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : 5;
}
