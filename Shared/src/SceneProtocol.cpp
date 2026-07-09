// ===========================================================================
// BabylonLivePreview — CommandEncoder implementation
// ===========================================================================
#include <BabylonLivePreview/SceneProtocol.h>

#include <cstring>

namespace BabylonLivePreview
{
    CommandEncoder::CommandEncoder() = default;

    void CommandEncoder::PutU8(uint8_t v)
    {
        m_body.push_back(v);
    }

    void CommandEncoder::PutU16(uint16_t v)
    {
        m_body.push_back(static_cast<uint8_t>(v & 0xFF));
        m_body.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    }

    void CommandEncoder::PutU32(uint32_t v)
    {
        for (int i = 0; i < 4; ++i)
        {
            m_body.push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
        }
    }

    void CommandEncoder::PutU64(uint64_t v)
    {
        for (int i = 0; i < 8; ++i)
        {
            m_body.push_back(static_cast<uint8_t>((v >> (8 * i)) & 0xFF));
        }
    }

    void CommandEncoder::PutF32(float v)
    {
        uint32_t bits;
        std::memcpy(&bits, &v, sizeof(bits));
        PutU32(bits);
    }

    void CommandEncoder::PutString(const std::string& s)
    {
        const uint16_t len = static_cast<uint16_t>(s.size() > 0xFFFF ? 0xFFFF : s.size());
        PutU16(len);
        m_body.insert(m_body.end(), s.begin(), s.begin() + len);
    }

    void CommandEncoder::PutTransform(float px, float py, float pz,
        float qx, float qy, float qz, float qw,
        float sx, float sy, float sz)
    {
        PutF32(px); PutF32(py); PutF32(pz);
        PutF32(qx); PutF32(qy); PutF32(qz); PutF32(qw);
        PutF32(sx); PutF32(sy); PutF32(sz);
    }

    void CommandEncoder::ResetScene()
    {
        PutU16(static_cast<uint16_t>(CommandType::ResetScene));
        ++m_count;
    }

    void CommandEncoder::SetClearColor(float r, float g, float b, float a)
    {
        PutU16(static_cast<uint16_t>(CommandType::SetClearColor));
        PutF32(r); PutF32(g); PutF32(b); PutF32(a);
        ++m_count;
    }

    void CommandEncoder::UpsertNode(uint64_t id, uint64_t parentId, NodeKind kind, const std::string& name,
        float px, float py, float pz,
        float qx, float qy, float qz, float qw,
        float sx, float sy, float sz)
    {
        PutU16(static_cast<uint16_t>(CommandType::UpsertNode));
        PutU64(id);
        PutU64(parentId);
        PutU16(static_cast<uint16_t>(kind));
        PutString(name);
        PutTransform(px, py, pz, qx, qy, qz, qw, sx, sy, sz);
        ++m_count;
    }

    void CommandEncoder::RemoveNode(uint64_t id)
    {
        PutU16(static_cast<uint16_t>(CommandType::RemoveNode));
        PutU64(id);
        ++m_count;
    }

    void CommandEncoder::BindNodePath(uint64_t id, const std::string& path)
    {
        PutU16(static_cast<uint16_t>(CommandType::BindNodePath));
        PutU64(id);
        PutString(path);
        ++m_count;
    }

    void CommandEncoder::SetTransform(uint64_t id,
        float px, float py, float pz,
        float qx, float qy, float qz, float qw,
        float sx, float sy, float sz)
    {
        PutU16(static_cast<uint16_t>(CommandType::SetTransform));
        PutU64(id);
        PutTransform(px, py, pz, qx, qy, qz, qw, sx, sy, sz);
        ++m_count;
    }

    void CommandEncoder::UpsertMeshGeometry(uint64_t id,
        const float* positions, uint32_t vtxCount,
        const float* normals, const float* uvs,
        const uint32_t* indices, uint32_t idxCount)
    {
        PutU16(static_cast<uint16_t>(CommandType::UpsertMeshGeometry));
        PutU64(id);
        PutU32(vtxCount);
        PutU8(normals ? 1 : 0);
        PutU8(uvs ? 1 : 0);
        PutU32(idxCount);
        for (uint32_t i = 0; i < vtxCount * 3; ++i) PutF32(positions[i]);
        if (normals)
        {
            for (uint32_t i = 0; i < vtxCount * 3; ++i) PutF32(normals[i]);
        }
        if (uvs)
        {
            for (uint32_t i = 0; i < vtxCount * 2; ++i) PutF32(uvs[i]);
        }
        for (uint32_t i = 0; i < idxCount; ++i) PutU32(indices[i]);
        ++m_count;
    }

    void CommandEncoder::UpsertMaterial(uint64_t nodeId,
        float r, float g, float b, float a,
        float metallic, float roughness,
        float emissiveR, float emissiveG, float emissiveB,
        float emissiveStrength)
    {
        PutU16(static_cast<uint16_t>(CommandType::UpsertMaterial));
        PutU64(nodeId);
        PutF32(r); PutF32(g); PutF32(b); PutF32(a);
        PutF32(metallic); PutF32(roughness);
        PutF32(emissiveR); PutF32(emissiveG); PutF32(emissiveB);
        PutF32(emissiveStrength);
        ++m_count;
    }

    void CommandEncoder::UpsertMaterialTexture(uint64_t nodeId, MaterialTextureChannel channel,
        TextureEncoding encoding, const uint8_t* data, uint32_t len)
    {
        PutU16(static_cast<uint16_t>(CommandType::UpsertMaterialTexture));
        PutU64(nodeId);
        PutU16(static_cast<uint16_t>(channel));
        PutU8(static_cast<uint8_t>(encoding));
        PutU32(len);
        if (data && len > 0)
        {
            m_body.insert(m_body.end(), data, data + len);
        }
        ++m_count;
    }

    void CommandEncoder::UpsertLight(uint64_t id, LightType type,
        float dx, float dy, float dz,
        float r, float g, float b,
        float intensity)
    {
        PutU16(static_cast<uint16_t>(CommandType::UpsertLight));
        PutU64(id);
        PutU16(static_cast<uint16_t>(type));
        PutF32(dx); PutF32(dy); PutF32(dz);
        PutF32(r); PutF32(g); PutF32(b);
        PutF32(intensity);
        ++m_count;
    }

    void CommandEncoder::SetCameraArcRotate(float alpha, float beta, float radius,
        float targetX, float targetY, float targetZ)
    {
        PutU16(static_cast<uint16_t>(CommandType::SetCamera));
        PutU8(static_cast<uint8_t>(CameraMode::ArcRotate));
        PutF32(alpha); PutF32(beta); PutF32(radius);
        PutF32(targetX); PutF32(targetY); PutF32(targetZ);
        ++m_count;
    }

    void CommandEncoder::SetCameraMatrices(const float view16[16], const float projection16[16])
    {
        PutU16(static_cast<uint16_t>(CommandType::SetCamera));
        PutU8(static_cast<uint8_t>(CameraMode::Matrices));
        for (int i = 0; i < 16; ++i) PutF32(view16[i]);
        for (int i = 0; i < 16; ++i) PutF32(projection16[i]);
        ++m_count;
    }

    std::vector<uint8_t> CommandEncoder::Finish()
    {
        std::vector<uint8_t> out;
        out.reserve(8 + m_body.size());

        // Header: magic (u32), version (u16), count (u16), little-endian.
        for (int i = 0; i < 4; ++i)
        {
            out.push_back(static_cast<uint8_t>((kCommandMagic >> (8 * i)) & 0xFF));
        }
        out.push_back(static_cast<uint8_t>(kCommandVersion & 0xFF));
        out.push_back(static_cast<uint8_t>((kCommandVersion >> 8) & 0xFF));
        out.push_back(static_cast<uint8_t>(m_count & 0xFF));
        out.push_back(static_cast<uint8_t>((m_count >> 8) & 0xFF));

        out.insert(out.end(), m_body.begin(), m_body.end());

        m_body.clear();
        m_count = 0;
        return out;
    }
}
