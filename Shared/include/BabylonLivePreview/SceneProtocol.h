// ===========================================================================
// BabylonLivePreview — scene-sync protocol (host -> Babylon)
// ===========================================================================
// Compact binary command buffer decoded by live_preview.js `applyCommands`.
// Replaces the reference project's WebSocket JSON transport with a direct
// in-process buffer, keeping a similar command vocabulary.
//
// Buffer layout (little-endian):
//   [u32 magic 'BLPC'][u16 version][u16 count]
//   then `count` records, each: [u16 type][... payload ...]
//
// String payloads are: [u16 byteLength][utf8 bytes] (ASCII-safe on the JS side).
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace BabylonLivePreview
{
    inline constexpr uint32_t kCommandMagic = 0x43504C42; // 'BLPC'
    inline constexpr uint16_t kCommandVersion = 2;

    enum class CommandType : uint16_t
    {
        UpsertNode = 1,         // id, parentId, kind, name, transform
        RemoveNode = 2,         // id
        SetTransform = 3,       // id, pos[3], quat[4], scale[3]
        UpsertMeshGeometry = 4, // id, vtxCount, hasNormals, hasUV, idxCount, arrays
        UpsertMaterial = 5,     // nodeId, rgba[4], metallic, roughness, emissive[3], emissiveStrength
        UpsertLight = 6,        // id, type, dir[3], color[3], intensity
        SetCamera = 7,          // mode + params (arcRotate) or view/proj matrices
        UpsertMaterialTexture = 8, // nodeId, channel, encoding, byteLength, bytes (byteLength 0 = clear)
        BindNodePath = 9,       // id, path (bind a pre-loaded node by stable path)
        ResetScene = 10,        // (none) — dispose current scene, start empty
        SetClearColor = 11,     // rgba[4]
    };

    // Texture channel of a PBRMetallicRoughnessMaterial (matches live_preview.js).
    enum class MaterialTextureChannel : uint16_t
    {
        BaseColor = 0,         // sRGB (gamma) — albedo
        MetallicRoughness = 1, // linear — glTF layout (G=roughness, B=metallic)
        Normal = 2,            // linear — tangent-space normal map
        Emissive = 3,          // sRGB (gamma)
        Occlusion = 4,         // linear — ambient occlusion (R)
    };

    // How a texture payload is encoded (matches live_preview.js).
    enum class TextureEncoding : uint8_t
    {
        EncodedImage = 0, // PNG/JPG/etc. file bytes, decoded natively via bimg
    };

    enum class NodeKind : uint16_t
    {
        TransformNode = 0,
        Mesh = 1,
    };

    enum class LightType : uint16_t
    {
        Hemispheric = 0,
        Directional = 1,
        Point = 2,
    };

    enum class CameraMode : uint8_t
    {
        ArcRotate = 0, // alpha, beta, radius, target[3]
        Matrices = 1,  // view[16], projection[16]
    };

    // Builds a command buffer decoded by live_preview.js. Reusable after Finish().
    class CommandEncoder
    {
    public:
        CommandEncoder();

        void ResetScene();
        void SetClearColor(float r, float g, float b, float a);

        void UpsertNode(uint64_t id, uint64_t parentId, NodeKind kind, const std::string& name,
            float px, float py, float pz,
            float qx, float qy, float qz, float qw,
            float sx, float sy, float sz);

        void RemoveNode(uint64_t id);

        // Bind an existing (pre-loaded, e.g. glTF-baked) scene node to `id` by
        // its stable path (glTF node name / USD PrimPath).
        void BindNodePath(uint64_t id, const std::string& path);

        void SetTransform(uint64_t id,
            float px, float py, float pz,
            float qx, float qy, float qz, float qw,
            float sx, float sy, float sz);

        // positions: vtxCount*3 floats. normals (nullable): vtxCount*3. uvs
        // (nullable): vtxCount*2. indices: idxCount uint32.
        void UpsertMeshGeometry(uint64_t id,
            const float* positions, uint32_t vtxCount,
            const float* normals, const float* uvs,
            const uint32_t* indices, uint32_t idxCount);

        void UpsertMaterial(uint64_t nodeId,
            float r, float g, float b, float a,
            float metallic, float roughness,
            float emissiveR, float emissiveG, float emissiveB,
            float emissiveStrength);

        // Encoded image bytes for one PBR channel. Pass len==0 to clear the
        // channel. `data` holds `len` bytes of an encoded image (PNG/JPG/etc).
        void UpsertMaterialTexture(uint64_t nodeId, MaterialTextureChannel channel,
            TextureEncoding encoding, const uint8_t* data, uint32_t len);

        void UpsertLight(uint64_t id, LightType type,
            float dx, float dy, float dz,
            float r, float g, float b,
            float intensity);

        void SetCameraArcRotate(float alpha, float beta, float radius,
            float targetX, float targetY, float targetZ);

        // Column-major 4x4 view and projection matrices (16 floats each).
        void SetCameraMatrices(const float view16[16], const float projection16[16]);

        // Finalise: writes the header, returns the buffer, and resets the encoder.
        std::vector<uint8_t> Finish();

        bool Empty() const { return m_count == 0; }

    private:
        void PutU8(uint8_t v);
        void PutU16(uint16_t v);
        void PutU32(uint32_t v);
        void PutU64(uint64_t v);
        void PutF32(float v);
        void PutString(const std::string& s);
        void PutTransform(float px, float py, float pz,
            float qx, float qy, float qz, float qw,
            float sx, float sy, float sz);

        std::vector<uint8_t> m_body;
        uint16_t m_count = 0;
    };
}
