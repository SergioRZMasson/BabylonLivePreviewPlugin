// ===========================================================================
// blp_translator — unit test for the shared scene-translation library
// ===========================================================================
// Exercises CoordinateBasis (axis mapping + matrix decompose) and
// SceneTranslator (id assignment, incremental diffing, textures, removals)
// WITHOUT booting Babylon Native — proving the translation layer is a pure,
// reusable protocol producer that Max and Maya share.
#include <BabylonLivePreview/SceneProtocol.h>
#include <BabylonLivePreview/SceneTranslation.h>

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

using namespace BabylonLivePreview;

static int g_failures = 0;

static void Check(bool cond, const char* what)
{
    if (!cond)
    {
        std::printf("  FAIL: %s\n", what);
        ++g_failures;
    }
}

static bool Near(float a, float b, float eps = 1e-4f) { return std::fabs(a - b) <= eps; }

// ---------------------------------------------------------------------------
// Minimal command-buffer decoder for assertions (little-endian).
// ---------------------------------------------------------------------------
struct Record
{
    uint16_t type = 0;
    uint64_t id = 0;
    uint16_t channel = 0;    // UpsertMaterialTexture
    uint32_t texLen = 0;     // UpsertMaterialTexture byte length
    uint32_t vtx = 0;        // UpsertMeshGeometry
    uint16_t lightType = 0;  // UpsertLight
    uint8_t camMode = 0;     // SetCamera
    float f[10] = {0};       // small scratch (transform / material / clear)
};

struct Decoded
{
    uint16_t version = 0;
    std::vector<Record> records;
    bool ok = false;
};

static uint16_t RdU16(const uint8_t* p, size_t& o) { uint16_t v; std::memcpy(&v, p + o, 2); o += 2; return v; }
static uint32_t RdU32(const uint8_t* p, size_t& o) { uint32_t v; std::memcpy(&v, p + o, 4); o += 4; return v; }
static uint64_t RdU64(const uint8_t* p, size_t& o) { uint64_t v; std::memcpy(&v, p + o, 8); o += 8; return v; }
static uint8_t  RdU8 (const uint8_t* p, size_t& o) { return p[o++]; }
static float    RdF32(const uint8_t* p, size_t& o) { float v; std::memcpy(&v, p + o, 4); o += 4; return v; }

static Decoded Decode(const std::vector<uint8_t>& buf)
{
    Decoded d;
    size_t o = 0;
    if (buf.size() < 8) return d;
    uint32_t magic = RdU32(buf.data(), o);
    if (magic != kCommandMagic) return d;
    d.version = RdU16(buf.data(), o);
    uint16_t count = RdU16(buf.data(), o);
    const uint8_t* p = buf.data();
    for (uint16_t i = 0; i < count; ++i)
    {
        Record r;
        r.type = RdU16(p, o);
        switch (static_cast<CommandType>(r.type))
        {
        case CommandType::ResetScene:
            break;
        case CommandType::SetClearColor:
            for (int k = 0; k < 4; ++k) r.f[k] = RdF32(p, o);
            break;
        case CommandType::UpsertNode:
        {
            r.id = RdU64(p, o);
            RdU64(p, o);            // parentId
            RdU16(p, o);            // kind
            uint16_t nlen = RdU16(p, o);
            o += nlen;              // name bytes
            for (int k = 0; k < 10; ++k) r.f[k] = RdF32(p, o); // transform
            break;
        }
        case CommandType::RemoveNode:
            r.id = RdU64(p, o);
            break;
        case CommandType::SetTransform:
            r.id = RdU64(p, o);
            for (int k = 0; k < 10; ++k) r.f[k] = RdF32(p, o);
            break;
        case CommandType::UpsertMeshGeometry:
        {
            r.id = RdU64(p, o);
            r.vtx = RdU32(p, o);
            uint8_t hasN = RdU8(p, o);
            uint8_t hasUV = RdU8(p, o);
            uint32_t idx = RdU32(p, o);
            o += static_cast<size_t>(r.vtx) * 3 * 4;
            if (hasN) o += static_cast<size_t>(r.vtx) * 3 * 4;
            if (hasUV) o += static_cast<size_t>(r.vtx) * 2 * 4;
            o += static_cast<size_t>(idx) * 4;
            break;
        }
        case CommandType::UpsertMaterial:
            r.id = RdU64(p, o);
            for (int k = 0; k < 10; ++k) r.f[k] = RdF32(p, o); // rgba, m, r, e[3], strength
            break;
        case CommandType::UpsertMaterialTexture:
            r.id = RdU64(p, o);
            r.channel = RdU16(p, o);
            RdU8(p, o);             // encoding
            r.texLen = RdU32(p, o);
            o += r.texLen;
            break;
        case CommandType::UpsertLight:
            r.id = RdU64(p, o);
            r.lightType = RdU16(p, o);
            for (int k = 0; k < 7; ++k) r.f[k] = RdF32(p, o);
            break;
        case CommandType::SetCamera:
            r.camMode = RdU8(p, o);
            o += (r.camMode == 0) ? (6 * 4) : (32 * 4);
            break;
        default:
            d.records.push_back(r);
            return d; // unknown -> stop (records incomplete)
        }
        d.records.push_back(r);
    }
    d.ok = true;
    return d;
}

static int Count(const Decoded& d, CommandType t)
{
    int n = 0;
    for (const auto& r : d.records) if (r.type == static_cast<uint16_t>(t)) ++n;
    return n;
}

static const Record* First(const Decoded& d, CommandType t)
{
    for (const auto& r : d.records) if (r.type == static_cast<uint16_t>(t)) return &r;
    return nullptr;
}

// A unit cube in local space (Blender-ish), for geometry emission.
static MeshData MakeCube()
{
    MeshData m;
    const float s = 1.0f;
    const float v[8][3] = {
        {-s,-s,-s},{ s,-s,-s},{ s, s,-s},{-s, s,-s},
        {-s,-s, s},{ s,-s, s},{ s, s, s},{-s, s, s}};
    for (auto& c : v) { m.positions.insert(m.positions.end(), {c[0], c[1], c[2]}); }
    const uint32_t f[12][3] = {
        {0,1,2},{0,2,3},{4,6,5},{4,7,6},{0,4,5},{0,5,1},
        {1,5,6},{1,6,2},{2,6,7},{2,7,3},{3,7,4},{3,4,0}};
    for (auto& t : f) { m.indices.insert(m.indices.end(), {t[0], t[1], t[2]}); }
    // Flat normals along +Z placeholder + UVs so hasN/hasUV paths are covered.
    m.normals.resize(m.positions.size(), 0.0f);
    for (size_t i = 0; i < m.normals.size(); i += 3) m.normals[i + 2] = 1.0f;
    m.uvs.resize((m.positions.size() / 3) * 2, 0.25f);
    return m;
}

static void Identity16(float m[16])
{
    std::memset(m, 0, sizeof(float) * 16);
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

// ---------------------------------------------------------------------------
int main()
{
    std::printf("[translator] coordinate basis...\n");
    {
        CoordinateBasis z = CoordinateBasis::ZUpRightHanded();
        Vec3 p = z.Point(1.0f, 2.0f, 3.0f);
        Check(Near(p.x, 1.0f) && Near(p.y, 3.0f) && Near(p.z, -2.0f), "ZUp maps (1,2,3)->(1,3,-2)");
        Check(z.reverseWinding, "ZUp reverses winding (RH->LH)");

        CoordinateBasis y = CoordinateBasis::YUpRightHanded();
        Vec3 q = y.Point(1.0f, 2.0f, 3.0f);
        Check(Near(q.x, 1.0f) && Near(q.y, 2.0f) && Near(q.z, -3.0f), "YUp maps (1,2,3)->(1,2,-3)");
        Check(!y.reverseWinding, "YUp does not double-reverse winding");

        // Identity world matrix -> identity TRS.
        float I[16]; Identity16(I);
        Trs t = z.ConvertMatrix(I);
        Check(Near(t.pos[0], 0) && Near(t.pos[1], 0) && Near(t.pos[2], 0), "identity -> pos 0");
        Check(Near(t.scale[0], 1) && Near(t.scale[1], 1) && Near(t.scale[2], 1), "identity -> scale 1");
        Check(Near(t.quat[3], 1) && Near(t.quat[0], 0), "identity -> quat identity");

        // Pure translation (column-major: t at 12,13,14) in Z-up DCC space.
        float T[16]; Identity16(T);
        T[12] = 1.0f; T[13] = 2.0f; T[14] = 3.0f; // DCC (x=1,y=2,z=3)
        Trs tt = z.ConvertMatrix(T);
        Check(Near(tt.pos[0], 1) && Near(tt.pos[1], 3) && Near(tt.pos[2], -2), "translation basis-converted");

        // Uniform scale 2.
        float S[16]; Identity16(S);
        S[0] = 2.0f; S[5] = 2.0f; S[10] = 2.0f;
        Trs ts = z.ConvertMatrix(S);
        Check(Near(std::fabs(ts.scale[0]), 2) && Near(std::fabs(ts.scale[1]), 2) && Near(std::fabs(ts.scale[2]), 2),
            "uniform scale 2 recovered");
    }

    std::printf("[translator] snapshot mesh+material+texture...\n");
    {
        SceneTranslator tr(CoordinateBasis::ZUpRightHanded());
        CommandEncoder enc;
        float clear[4] = {0.05f, 0.06f, 0.09f, 1.0f};
        tr.BeginSnapshot(enc, clear);

        MeshData cube = MakeCube();
        MaterialData mat;
        mat.baseColor[0] = 1.0f; mat.baseColor[1] = 1.0f; mat.baseColor[2] = 1.0f;
        std::vector<uint8_t> png = {0x89, 'P', 'N', 'G', 1, 2, 3, 4};
        mat.textures[static_cast<size_t>(TexChannel::BaseColor)] = png;
        mat.textureIds[static_cast<size_t>(TexChannel::BaseColor)] = 0xABCDEF;

        float world[16]; Identity16(world);
        tr.SyncMesh(enc, "Cube", "Cube", world, &cube, mat);

        Decoded d = Decode(enc.Finish());
        Check(d.ok, "snapshot buffer decodes");
        Check(Count(d, CommandType::ResetScene) == 1, "1 ResetScene");
        Check(Count(d, CommandType::SetClearColor) == 1, "1 SetClearColor");
        Check(Count(d, CommandType::UpsertNode) == 1, "1 UpsertNode");
        Check(Count(d, CommandType::UpsertMeshGeometry) == 1, "1 UpsertMeshGeometry");
        Check(Count(d, CommandType::UpsertMaterial) == 1, "1 UpsertMaterial");
        Check(Count(d, CommandType::UpsertMaterialTexture) == 1, "1 UpsertMaterialTexture");
        const Record* geo = First(d, CommandType::UpsertMeshGeometry);
        Check(geo && geo->vtx == 8, "geometry has 8 verts");
        const Record* tex = First(d, CommandType::UpsertMaterialTexture);
        Check(tex && tex->channel == static_cast<uint16_t>(TexChannel::BaseColor) && tex->texLen == png.size(),
            "base-color texture bytes emitted");
    }

    std::printf("[translator] incremental: no-op / transform / material / texture clear...\n");
    {
        SceneTranslator tr(CoordinateBasis::ZUpRightHanded());
        CommandEncoder enc;
        float clear[4] = {0, 0, 0, 1};
        tr.BeginSnapshot(enc, clear);
        MeshData cube = MakeCube();
        MaterialData mat;
        std::vector<uint8_t> png = {0x89, 'P', 'N', 'G', 9};
        mat.textures[static_cast<size_t>(TexChannel::BaseColor)] = png;
        mat.textureIds[static_cast<size_t>(TexChannel::BaseColor)] = 7;
        float world[16]; Identity16(world);
        tr.SyncMesh(enc, "Cube", "Cube", world, &cube, mat);
        enc.Finish(); // discard snapshot

        // 1. Re-sync identical (no geometry pointer, same xform + material) -> nothing.
        tr.BeginSync();
        bool changed = tr.SyncMesh(enc, "Cube", "Cube", world, nullptr, mat);
        Check(!changed, "unchanged mesh emits nothing");
        Check(enc.Empty(), "encoder empty after no-op sync");
        enc.Finish();

        // 2. Move it -> exactly one SetTransform, no material/geometry.
        float moved[16]; Identity16(moved);
        moved[12] = 5.0f;
        tr.BeginSync();
        changed = tr.SyncMesh(enc, "Cube", "Cube", moved, nullptr, mat);
        Decoded d2 = Decode(enc.Finish());
        Check(changed, "moved mesh reports change");
        Check(Count(d2, CommandType::SetTransform) == 1, "1 SetTransform on move");
        Check(Count(d2, CommandType::UpsertMaterial) == 0, "no material re-emit on move");
        Check(Count(d2, CommandType::UpsertMeshGeometry) == 0, "no geometry re-emit on move");

        // 3. Change material color -> UpsertMaterial only.
        mat.baseColor[0] = 0.2f;
        tr.BeginSync();
        tr.SyncMesh(enc, "Cube", "Cube", moved, nullptr, mat);
        Decoded d3 = Decode(enc.Finish());
        Check(Count(d3, CommandType::UpsertMaterial) == 1, "material re-emit on color change");
        Check(Count(d3, CommandType::UpsertMaterialTexture) == 1, "texture re-sent with material (still present)");

        // 4. Remove the texture -> a clear (len 0) for base color.
        mat.textures[static_cast<size_t>(TexChannel::BaseColor)].clear();
        mat.textureIds[static_cast<size_t>(TexChannel::BaseColor)] = 0;
        tr.BeginSync();
        tr.SyncMesh(enc, "Cube", "Cube", moved, nullptr, mat);
        Decoded d4 = Decode(enc.Finish());
        Check(Count(d4, CommandType::UpsertMaterialTexture) == 1, "one texture command on clear");
        const Record* clr = First(d4, CommandType::UpsertMaterialTexture);
        Check(clr && clr->texLen == 0, "texture cleared with len 0");
    }

    std::printf("[translator] light + camera + removals...\n");
    {
        SceneTranslator tr(CoordinateBasis::ZUpRightHanded());
        CommandEncoder enc;
        float clear[4] = {0, 0, 0, 1};
        tr.BeginSnapshot(enc, clear);
        enc.Finish();

        MeshData cube = MakeCube();
        MaterialData mat;
        float w1[16]; Identity16(w1);
        float w2[16]; Identity16(w2); w2[12] = 3.0f;

        LightData light;
        light.type = LightType::Point;
        light.vec[0] = 1.0f; light.vec[1] = 4.0f; light.vec[2] = 2.0f;
        light.intensity = 2.0f;

        CameraData cam = CameraData::Arc(Vec3{6, 4, 6}, Vec3{0, 0, 0});

        // Sync two meshes + a light + camera.
        tr.BeginSync();
        tr.SyncMesh(enc, "A", "A", w1, &cube, mat);
        tr.SyncMesh(enc, "B", "B", w2, &cube, mat);
        tr.SyncLight(enc, "Lamp", light, w1);
        tr.SyncCamera(enc, cam);
        Decoded d = Decode(enc.Finish());
        Check(Count(d, CommandType::UpsertNode) == 2, "two mesh nodes");
        Check(Count(d, CommandType::UpsertLight) == 1, "one light");
        Check(Count(d, CommandType::SetCamera) == 1, "one camera");
        const Record* lr = First(d, CommandType::UpsertLight);
        Check(lr && lr->lightType == static_cast<uint16_t>(LightType::Point), "light type point");

        // Re-sync camera identical -> no camera command.
        tr.BeginSync();
        tr.SyncMesh(enc, "A", "A", w1, nullptr, mat);
        tr.SyncMesh(enc, "B", "B", w2, nullptr, mat);
        tr.SyncLight(enc, "Lamp", light, w1);
        bool camChanged = tr.SyncCamera(enc, cam);
        Check(!camChanged, "identical camera not re-emitted");
        enc.Finish();

        // Drop "B": BeginSync, only touch A + Lamp, then EmitRemovals -> RemoveNode(B).
        tr.BeginSync();
        tr.SyncMesh(enc, "A", "A", w1, nullptr, mat);
        tr.SyncLight(enc, "Lamp", light, w1);
        tr.EmitRemovals(enc);
        Decoded dr = Decode(enc.Finish());
        Check(Count(dr, CommandType::RemoveNode) == 1, "one RemoveNode for dropped mesh");
    }

    if (g_failures == 0)
    {
        std::printf("[translator] ALL PASS\n");
        return 0;
    }
    std::printf("[translator] %d FAILURE(S)\n", g_failures);
    return 1;
}
