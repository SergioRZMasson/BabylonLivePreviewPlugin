// ===========================================================================
// BabylonLivePreview — shared scene translation implementation
// ===========================================================================
#include <BabylonLivePreview/SceneTranslation.h>

#include <cmath>
#include <cstring>

namespace BabylonLivePreview
{
    namespace
    {
        // FNV-1a over raw bytes, for cheap change-detection signatures.
        uint64_t HashBytes(const void* data, size_t size, uint64_t seed = 1469598103934665603ull)
        {
            const auto* p = static_cast<const uint8_t*>(data);
            uint64_t h = seed;
            for (size_t i = 0; i < size; ++i)
            {
                h ^= p[i];
                h *= 1099511628211ull;
            }
            return h;
        }

        uint64_t HashFloats(const float* v, size_t count, uint64_t seed = 1469598103934665603ull)
        {
            // Quantize so tiny float noise doesn't churn the diff.
            uint64_t h = seed;
            for (size_t i = 0; i < count; ++i)
            {
                float q = std::round(v[i] * 100000.0f) / 100000.0f;
                if (q == 0.0f) q = 0.0f; // normalize -0
                h = HashBytes(&q, sizeof(q), h);
            }
            return h;
        }

        // Multiply row-major 3x3 (a) by column-major-from-world 3x3 rotation part.
        // We keep everything as plain 3x3 row-major here for clarity.
        struct Mat3 { float m[9]; };

        Mat3 Mul3(const Mat3& a, const Mat3& b)
        {
            Mat3 r{};
            for (int i = 0; i < 3; ++i)
                for (int j = 0; j < 3; ++j)
                {
                    float s = 0.0f;
                    for (int k = 0; k < 3; ++k) s += a.m[i * 3 + k] * b.m[k * 3 + j];
                    r.m[i * 3 + j] = s;
                }
            return r;
        }

        Mat3 Transpose3(const Mat3& a)
        {
            Mat3 r{};
            for (int i = 0; i < 3; ++i)
                for (int j = 0; j < 3; ++j)
                    r.m[i * 3 + j] = a.m[j * 3 + i];
            return r;
        }

        // Quaternion (x,y,z,w) from a pure-rotation row-major 3x3.
        void QuatFromMat3(const float m[9], float q[4])
        {
            const float trace = m[0] + m[4] + m[8];
            if (trace > 0.0f)
            {
                float s = std::sqrt(trace + 1.0f) * 2.0f;
                q[3] = 0.25f * s;
                q[0] = (m[7] - m[5]) / s;
                q[1] = (m[2] - m[6]) / s;
                q[2] = (m[3] - m[1]) / s;
            }
            else if (m[0] > m[4] && m[0] > m[8])
            {
                float s = std::sqrt(1.0f + m[0] - m[4] - m[8]) * 2.0f;
                q[3] = (m[7] - m[5]) / s;
                q[0] = 0.25f * s;
                q[1] = (m[1] + m[3]) / s;
                q[2] = (m[2] + m[6]) / s;
            }
            else if (m[4] > m[8])
            {
                float s = std::sqrt(1.0f + m[4] - m[0] - m[8]) * 2.0f;
                q[3] = (m[2] - m[6]) / s;
                q[0] = (m[1] + m[3]) / s;
                q[1] = 0.25f * s;
                q[2] = (m[5] + m[7]) / s;
            }
            else
            {
                float s = std::sqrt(1.0f + m[8] - m[0] - m[4]) * 2.0f;
                q[3] = (m[3] - m[1]) / s;
                q[0] = (m[2] + m[6]) / s;
                q[1] = (m[5] + m[7]) / s;
                q[2] = 0.25f * s;
            }
            // Normalize.
            float n = std::sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            if (n > 1e-8f) { q[0] /= n; q[1] /= n; q[2] /= n; q[3] /= n; }
            else { q[0] = q[1] = q[2] = 0.0f; q[3] = 1.0f; }
        }
    } // namespace

    // ----------------------------------------------------------------------
    CoordinateBasis CoordinateBasis::ZUpRightHanded()
    {
        // (x,y,z) -> (x, z, -y): row-major rows [1,0,0],[0,0,1],[0,-1,0].
        CoordinateBasis b;
        b.m[0] = 1; b.m[1] = 0; b.m[2] = 0;
        b.m[3] = 0; b.m[4] = 0; b.m[5] = 1;
        b.m[6] = 0; b.m[7] = -1; b.m[8] = 0;
        b.reverseWinding = true;
        return b;
    }

    CoordinateBasis CoordinateBasis::YUpRightHanded()
    {
        // (x,y,z) -> (x, y, -z): negate Z (RH->LH reflection).
        CoordinateBasis b;
        b.m[0] = 1; b.m[1] = 0; b.m[2] = 0;
        b.m[3] = 0; b.m[4] = 1; b.m[5] = 0;
        b.m[6] = 0; b.m[7] = 0; b.m[8] = -1;
        b.reverseWinding = false;
        return b;
    }

    Vec3 CoordinateBasis::Point(float x, float y, float z) const
    {
        return Vec3{
            m[0] * x + m[1] * y + m[2] * z,
            m[3] * x + m[4] * y + m[5] * z,
            m[6] * x + m[7] * y + m[8] * z};
    }

    Vec3 CoordinateBasis::Dir(float x, float y, float z) const
    {
        return Point(x, y, z);
    }

    Trs CoordinateBasis::ConvertMatrix(const float world[16]) const
    {
        // Extract translation (column-major: 12,13,14) and 3x3 linear part.
        // Column-major element (row r, col c) = world[c*4 + r].
        float t[3] = {world[12], world[13], world[14]};
        Mat3 R{};
        for (int c = 0; c < 3; ++c)
            for (int r = 0; r < 3; ++r)
                R.m[r * 3 + c] = world[c * 4 + r];

        Mat3 B{}; std::memcpy(B.m, m, sizeof(B.m));
        Mat3 Bt = Transpose3(B); // orthogonal basis => inverse == transpose

        // Linear part conjugated into Babylon space: B * R * B^-1.
        Mat3 Rp = Mul3(Mul3(B, R), Bt);
        // Translation into Babylon space: B * t.
        Vec3 tp = Point(t[0], t[1], t[2]);

        Trs out;
        out.pos[0] = tp.x; out.pos[1] = tp.y; out.pos[2] = tp.z;

        // Decompose Rp into scale (column lengths) + pure rotation.
        float sx = std::sqrt(Rp.m[0] * Rp.m[0] + Rp.m[3] * Rp.m[3] + Rp.m[6] * Rp.m[6]);
        float sy = std::sqrt(Rp.m[1] * Rp.m[1] + Rp.m[4] * Rp.m[4] + Rp.m[7] * Rp.m[7]);
        float sz = std::sqrt(Rp.m[2] * Rp.m[2] + Rp.m[5] * Rp.m[5] + Rp.m[8] * Rp.m[8]);

        // Negative determinant => a flipped axis; fold the flip into X scale so
        // the rotation stays a proper rotation for the quaternion extraction.
        float det = Rp.m[0] * (Rp.m[4] * Rp.m[8] - Rp.m[5] * Rp.m[7])
                  - Rp.m[1] * (Rp.m[3] * Rp.m[8] - Rp.m[5] * Rp.m[6])
                  + Rp.m[2] * (Rp.m[3] * Rp.m[7] - Rp.m[4] * Rp.m[6]);
        if (det < 0.0f) sx = -sx;

        out.scale[0] = sx; out.scale[1] = sy; out.scale[2] = sz;

        float rot[9];
        float ix = (std::fabs(sx) > 1e-8f) ? 1.0f / sx : 0.0f;
        float iy = (std::fabs(sy) > 1e-8f) ? 1.0f / sy : 0.0f;
        float iz = (std::fabs(sz) > 1e-8f) ? 1.0f / sz : 0.0f;
        rot[0] = Rp.m[0] * ix; rot[1] = Rp.m[1] * iy; rot[2] = Rp.m[2] * iz;
        rot[3] = Rp.m[3] * ix; rot[4] = Rp.m[4] * iy; rot[5] = Rp.m[5] * iz;
        rot[6] = Rp.m[6] * ix; rot[7] = Rp.m[7] * iy; rot[8] = Rp.m[8] * iz;
        QuatFromMat3(rot, out.quat);
        return out;
    }

    // ----------------------------------------------------------------------
    CameraData CameraData::Arc(const Vec3& eye, const Vec3& target)
    {
        CameraData c;
        c.useMatrices = false;
        c.target[0] = target.x; c.target[1] = target.y; c.target[2] = target.z;
        float dx = eye.x - target.x, dy = eye.y - target.y, dz = eye.z - target.z;
        float radius = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (radius < 0.1f) radius = 0.1f;
        c.radius = radius;
        c.beta = std::acos(std::fmax(-1.0f, std::fmin(1.0f, dy / radius)));
        c.alpha = std::atan2(dz, dx);
        return c;
    }

    // ----------------------------------------------------------------------
    SceneTranslator::SceneTranslator(CoordinateBasis basis)
        : m_basis(basis) {}

    void SceneTranslator::BeginSnapshot(CommandEncoder& enc, const float clearColor[4])
    {
        m_nodes.clear();
        m_visible.clear();
        m_nextId = 1;
        m_haveCamera = false;
        m_cameraKeyHash = 0;
        enc.ResetScene();
        if (clearColor)
        {
            enc.SetClearColor(clearColor[0], clearColor[1], clearColor[2], clearColor[3]);
        }
    }

    void SceneTranslator::BeginSync()
    {
        m_visible.clear();
    }

    void SceneTranslator::MarkVisible(const std::string& key)
    {
        m_visible.insert(key);
    }

    void SceneTranslator::EmitRemovals(CommandEncoder& enc)
    {
        for (auto it = m_nodes.begin(); it != m_nodes.end();)
        {
            if (m_visible.find(it->first) == m_visible.end())
            {
                enc.RemoveNode(it->second.id);
                it = m_nodes.erase(it);
            }
            else
            {
                ++it;
            }
        }
    }

    uint64_t SceneTranslator::IdFor(const std::string& key)
    {
        auto it = m_nodes.find(key);
        if (it != m_nodes.end()) return it->second.id;
        NodeState st;
        st.id = m_nextId++;
        m_nodes.emplace(key, st);
        return st.id;
    }

    void SceneTranslator::EmitGeometry(CommandEncoder& enc, uint64_t id, const MeshData& mesh)
    {
        const uint32_t vtx = static_cast<uint32_t>(mesh.positions.size() / 3);
        const bool hasN = !mesh.normals.empty() && mesh.normals.size() == mesh.positions.size();
        const bool hasUV = !mesh.uvs.empty() && mesh.uvs.size() == vtx * 2;

        // Convert local positions/normals into Babylon space via the basis.
        std::vector<float> pos(mesh.positions.size());
        for (uint32_t i = 0; i < vtx; ++i)
        {
            Vec3 p = m_basis.Point(mesh.positions[i * 3], mesh.positions[i * 3 + 1], mesh.positions[i * 3 + 2]);
            pos[i * 3] = p.x; pos[i * 3 + 1] = p.y; pos[i * 3 + 2] = p.z;
        }
        std::vector<float> nrm;
        if (hasN)
        {
            nrm.resize(mesh.normals.size());
            for (uint32_t i = 0; i < vtx; ++i)
            {
                Vec3 n = m_basis.Dir(mesh.normals[i * 3], mesh.normals[i * 3 + 1], mesh.normals[i * 3 + 2]);
                nrm[i * 3] = n.x; nrm[i * 3 + 1] = n.y; nrm[i * 3 + 2] = n.z;
            }
        }

        // Copy + optionally reverse winding (swap the 2nd/3rd index of each tri).
        std::vector<uint32_t> idx(mesh.indices);
        if (m_basis.reverseWinding)
        {
            for (size_t t = 0; t + 2 < idx.size(); t += 3)
            {
                std::swap(idx[t + 1], idx[t + 2]);
            }
        }

        enc.UpsertMeshGeometry(id,
            pos.data(), vtx,
            hasN ? nrm.data() : nullptr,
            hasUV ? mesh.uvs.data() : nullptr,
            idx.data(), static_cast<uint32_t>(idx.size()));
    }

    void SceneTranslator::EmitMaterial(CommandEncoder& enc, uint64_t id, NodeState& st, const MaterialData& mat)
    {
        enc.UpsertMaterial(id,
            mat.baseColor[0], mat.baseColor[1], mat.baseColor[2], mat.baseColor[3],
            mat.metallic, mat.roughness,
            mat.emissive[0], mat.emissive[1], mat.emissive[2], mat.emissiveStrength);

        uint32_t active = 0;
        for (uint32_t ch = 0; ch < static_cast<uint32_t>(TexChannel::Count); ++ch)
        {
            const auto& bytes = mat.textures[ch];
            if (mat.textureIds[ch] != 0 && !bytes.empty())
            {
                enc.UpsertMaterialTexture(id, static_cast<MaterialTextureChannel>(ch),
                    TextureEncoding::EncodedImage, bytes.data(), static_cast<uint32_t>(bytes.size()));
                active |= (1u << ch);
            }
        }
        // Clear channels that were set before but are gone now.
        uint32_t removed = st.activeTexChannels & ~active;
        for (uint32_t ch = 0; ch < static_cast<uint32_t>(TexChannel::Count); ++ch)
        {
            if (removed & (1u << ch))
            {
                enc.UpsertMaterialTexture(id, static_cast<MaterialTextureChannel>(ch),
                    TextureEncoding::EncodedImage, nullptr, 0);
            }
        }
        st.activeTexChannels = active;
    }

    bool SceneTranslator::SyncMesh(CommandEncoder& enc,
        const std::string& key, const std::string& name,
        const float world[16],
        const MeshData* geometry,
        const MaterialData& material)
    {
        MarkVisible(key);
        auto it = m_nodes.find(key);
        const bool isNew = (it == m_nodes.end());
        if (isNew)
        {
            NodeState st;
            st.id = m_nextId++;
            st.kind = 'M';
            it = m_nodes.emplace(key, st).first;
        }
        NodeState& st = it->second;
        bool changed = false;

        Trs trs = m_basis.ConvertMatrix(world);
        uint64_t xh = HashFloats(trs.pos, 3);
        xh = HashFloats(trs.quat, 4, xh);
        xh = HashFloats(trs.scale, 3, xh);

        if (isNew)
        {
            enc.UpsertNode(st.id, 0, NodeKind::Mesh, name,
                trs.pos[0], trs.pos[1], trs.pos[2],
                trs.quat[0], trs.quat[1], trs.quat[2], trs.quat[3],
                trs.scale[0], trs.scale[1], trs.scale[2]);
            st.xformHash = xh;
            changed = true;
        }
        else if (xh != st.xformHash)
        {
            enc.SetTransform(st.id,
                trs.pos[0], trs.pos[1], trs.pos[2],
                trs.quat[0], trs.quat[1], trs.quat[2], trs.quat[3],
                trs.scale[0], trs.scale[1], trs.scale[2]);
            st.xformHash = xh;
            changed = true;
        }

        if (geometry != nullptr)
        {
            EmitGeometry(enc, st.id, *geometry);
            changed = true;
        }

        // Material signature: scalars + per-channel texture ids.
        uint64_t mh = HashFloats(material.baseColor, 4);
        mh = HashFloats(&material.metallic, 1, mh);
        mh = HashFloats(&material.roughness, 1, mh);
        mh = HashFloats(material.emissive, 3, mh);
        mh = HashFloats(&material.emissiveStrength, 1, mh);
        mh = HashBytes(material.textureIds.data(),
            material.textureIds.size() * sizeof(uint64_t), mh);
        if (isNew || mh != st.materialHash)
        {
            EmitMaterial(enc, st.id, st, material);
            st.materialHash = mh;
            changed = true;
        }
        return changed;
    }

    bool SceneTranslator::SyncLight(CommandEncoder& enc,
        const std::string& key, const LightData& light, const float world[16])
    {
        MarkVisible(key);
        auto it = m_nodes.find(key);
        const bool isNew = (it == m_nodes.end());
        if (isNew)
        {
            NodeState st;
            st.id = m_nextId++;
            st.kind = 'L';
            it = m_nodes.emplace(key, st).first;
        }
        NodeState& st = it->second;

        uint64_t lh = HashBytes(&light.type, sizeof(light.type));
        lh = HashFloats(light.vec, 3, lh);
        lh = HashFloats(light.color, 3, lh);
        lh = HashFloats(&light.intensity, 1, lh);
        if (world) lh = HashBytes(world, sizeof(float) * 16, lh);

        if (!isNew && lh == st.lightHash)
        {
            return false;
        }
        enc.UpsertLight(st.id, light.type,
            light.vec[0], light.vec[1], light.vec[2],
            light.color[0], light.color[1], light.color[2],
            light.intensity);
        st.lightHash = lh;
        return true;
    }

    bool SceneTranslator::SyncCamera(CommandEncoder& enc, const CameraData& cam)
    {
        uint64_t h;
        if (cam.useMatrices)
        {
            h = HashFloats(cam.view, 16);
            h = HashFloats(cam.projection, 16, h);
        }
        else
        {
            float p[6] = {cam.alpha, cam.beta, cam.radius, cam.target[0], cam.target[1], cam.target[2]};
            h = HashFloats(p, 6);
        }
        if (m_haveCamera && h == m_cameraKeyHash)
        {
            return false;
        }
        if (cam.useMatrices)
        {
            enc.SetCameraMatrices(cam.view, cam.projection);
        }
        else
        {
            enc.SetCameraArcRotate(cam.alpha, cam.beta, cam.radius,
                cam.target[0], cam.target[1], cam.target[2]);
        }
        m_cameraKeyHash = h;
        m_haveCamera = true;
        return true;
    }

    void SceneTranslator::EmitDefaultFill(CommandEncoder& enc, bool sceneHasLights)
    {
        if (sceneHasLights) return;
        enc.UpsertLight(kDefaultFillLightId, LightType::Hemispheric,
            0.2f, 1.0f, 0.3f, 1.0f, 1.0f, 1.0f, 0.7f);
    }
}
