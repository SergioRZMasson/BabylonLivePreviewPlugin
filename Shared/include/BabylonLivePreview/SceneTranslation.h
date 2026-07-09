// ===========================================================================
// BabylonLivePreview — shared scene translation (DCC graph -> protocol)
// ===========================================================================
// DCC-agnostic C++ equivalent of the Blender add-on's `capture.py` SceneSync:
// coordinate conversion, incremental diffing, and command emission. The Max and
// Maya plugins (both C++) share this; each supplies only the SDK-specific leaf
// extraction that fills the POD structs below. (Blender keeps its own Python
// port because bpy is Python-only.)
//
// Pipeline per object, driven by the plugin:
//   translator.BeginSync();
//   for each mesh:   translator.SyncMesh(enc, key, name, world, geoOrNull, mat);
//   for each light:  translator.SyncLight(enc, key, light, world);
//   translator.SyncCamera(enc, camera);
//   translator.EmitRemovals(enc);           // nodes gone since last sync
//   session.SubmitCommands(enc.Finish());
#pragma once

#include <BabylonLivePreview/SceneProtocol.h>

#include <array>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace BabylonLivePreview
{
    struct Vec3 { float x = 0.0f, y = 0.0f, z = 0.0f; };

    // Position + orientation + scale in Babylon (Y-up, left-handed) space.
    struct Trs
    {
        float pos[3] = {0.0f, 0.0f, 0.0f};
        float quat[4] = {0.0f, 0.0f, 0.0f, 1.0f}; // x, y, z, w
        float scale[3] = {1.0f, 1.0f, 1.0f};
    };

    // ------------------------------------------------------------------
    // Coordinate basis: maps a DCC coordinate system into Babylon's Y-up
    // left-handed space. `m` is a row-major 3x3 orthogonal matrix applied as
    // out_i = sum_j m[i*3+j] * v[j]. `reverseWinding` flips triangle winding
    // when the DCC is right-handed and Babylon is left-handed AND the basis is
    // orientation-preserving (det +1). Presets below encode the verified values.
    // ------------------------------------------------------------------
    struct CoordinateBasis
    {
        float m[9] = {1, 0, 0, 0, 1, 0, 0, 0, 1};
        bool reverseWinding = false;

        // Blender / 3ds Max: right-handed Z-up. (x,y,z) -> (x, z, -y); reverse
        // winding for RH->LH. (Verified against capture.py for Blender.)
        static CoordinateBasis ZUpRightHanded();

        // Maya: right-handed Y-up. (x,y,z) -> (x, y, -z) (negate Z reflection
        // converts RH->LH and flips face orientation, so winding is NOT reversed
        // again). Needs in-Maya visual confirmation.
        static CoordinateBasis YUpRightHanded();

        Vec3 Point(float x, float y, float z) const;
        Vec3 Dir(float x, float y, float z) const; // same as Point (no translation)

        // Convert a DCC world matrix (column-major float[16], translation in
        // 12,13,14) into a Babylon-space TRS via B * M * B^-1 + decompose.
        Trs ConvertMatrix(const float world[16]) const;
    };

    // ------------------------------------------------------------------
    // POD scene data filled by the per-DCC extraction layer. Geometry arrays are
    // in DCC LOCAL space; SceneTranslator applies the basis + winding.
    // ------------------------------------------------------------------
    struct MeshData
    {
        std::vector<float> positions;   // vtx*3, local space
        std::vector<float> normals;     // vtx*3 (optional; empty = recompute in JS)
        std::vector<float> uvs;         // vtx*2 (optional). V is flipped by the plugin
        std::vector<uint32_t> indices;  // triangle list
    };

    enum class TexChannel : uint32_t
    {
        BaseColor = 0,          // sRGB
        MetallicRoughness = 1,  // linear (glTF G=rough, B=metal)
        Normal = 2,             // linear
        Emissive = 3,           // sRGB
        Occlusion = 4,          // linear
        Count = 5,
    };

    struct MaterialData
    {
        float baseColor[4] = {0.8f, 0.8f, 0.8f, 1.0f};
        float metallic = 0.0f;
        float roughness = 0.6f;
        float emissive[3] = {0.0f, 0.0f, 0.0f};
        float emissiveStrength = 0.0f;

        // Encoded image bytes per channel (PNG/JPG/...); empty = no texture.
        std::array<std::vector<uint8_t>, static_cast<size_t>(TexChannel::Count)> textures;
        // Cheap per-channel identity for change detection (0 = none). Set even
        // when `textures` is left empty for a diff-only pass.
        std::array<uint64_t, static_cast<size_t>(TexChannel::Count)> textureIds{};
    };

    struct LightData
    {
        LightType type = LightType::Point;
        // Direction (directional/hemispheric) or world position (point), already
        // converted to Babylon space by the plugin via CoordinateBasis.
        float vec[3] = {0.0f, 0.0f, 0.0f};
        float color[3] = {1.0f, 1.0f, 1.0f};
        float intensity = 1.0f;
    };

    struct CameraData
    {
        bool useMatrices = false;
        // ArcRotate (default): alpha/beta/radius around target.
        float alpha = 0.0f, beta = 0.0f, radius = 10.0f;
        float target[3] = {0.0f, 0.0f, 0.0f};
        // Or explicit view/projection (column-major), when useMatrices = true.
        float view[16] = {0};
        float projection[16] = {0};

        // Build an ArcRotate camera from Babylon-space eye + target positions
        // (mirrors capture.py `_camera_arc`).
        static CameraData Arc(const Vec3& eyeBabylon, const Vec3& targetBabylon);
    };

    // ------------------------------------------------------------------
    // Incremental translator. Owns node-id assignment and per-node signatures so
    // only changed data is emitted (mirrors capture.py `SceneSync`).
    // ------------------------------------------------------------------
    class SceneTranslator
    {
    public:
        explicit SceneTranslator(CoordinateBasis basis);

        const CoordinateBasis& Basis() const { return m_basis; }

        // Full reset: clears ids/state and emits ResetScene + clear color. Use on
        // (re)start or when the plugin can't diff (e.g. full-scene reload).
        void BeginSnapshot(CommandEncoder& enc, const float clearColor[4]);

        // Begin an incremental pass; call MarkVisible per present node, then
        // EmitRemovals at the end to drop nodes that disappeared.
        void BeginSync();
        void MarkVisible(const std::string& key);
        void EmitRemovals(CommandEncoder& enc);

        // Stable id for a node key (name/handle). Allocates on first use.
        uint64_t IdFor(const std::string& key);

        // Mesh: upserts the node on first sight, emits geometry when `geometry`
        // is non-null, and emits material when its signature changed. Pass
        // geometry only when the plugin knows topology/vertices changed (or on
        // add). Returns true if anything was emitted. Also marks the key visible.
        bool SyncMesh(CommandEncoder& enc,
            const std::string& key, const std::string& name,
            const float world[16],
            const MeshData* geometry,
            const MaterialData& material);

        // Light: upserts/updates on change (type, vec, color, intensity, xform).
        bool SyncLight(CommandEncoder& enc,
            const std::string& key, const LightData& light, const float world[16]);

        // Camera: emits SetCamera when the parameters changed.
        bool SyncCamera(CommandEncoder& enc, const CameraData& camera);

        // Convenience: add a hemispheric fill light only if the scene has no
        // real lights (matches the Blender default look). id is fixed/high.
        void EmitDefaultFill(CommandEncoder& enc, bool sceneHasLights);

    private:
        struct NodeState
        {
            uint64_t id = 0;
            char kind = 0; // 'M' mesh, 'L' light, 'C' camera
            uint64_t xformHash = 0;
            uint64_t materialHash = 0;
            uint32_t activeTexChannels = 0; // bitmask of TexChannel currently set
            uint64_t lightHash = 0;
        };

        void EmitGeometry(CommandEncoder& enc, uint64_t id, const MeshData& mesh);
        void EmitMaterial(CommandEncoder& enc, uint64_t id, NodeState& st, const MaterialData& mat);

        CoordinateBasis m_basis;
        std::unordered_map<std::string, NodeState> m_nodes;
        std::unordered_set<std::string> m_visible;
        uint64_t m_nextId = 1;
        uint64_t m_cameraKeyHash = 0;
        bool m_haveCamera = false;
    };

    // Fixed id used for the synthetic default hemispheric fill light.
    inline constexpr uint64_t kDefaultFillLightId = 1000000ull;
}
