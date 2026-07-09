// ===========================================================================
// BabylonLivePreview — 3ds Max scene capture implementation
// ===========================================================================
// SDK-gated. Mirrors MayaCapture.cpp: fills POD structs from the Max node graph
// and hands them to the SHARED SceneTranslator. Only this file differs between
// Max and Maya; the translation + protocol are shared.
#include "MaxCapture.h"

#include <max.h>
#include <triobj.h>
#include <iparamb2.h>
#include <imtl.h>
#include <bitmap.h>
#include <stdmat.h>

#include <cstdio>
#include <fstream>
#include <functional>
#include <string>

namespace BabylonLivePreview::MaxPlugin
{
    namespace
    {
        // Max Matrix3 is a 4x3 (rows are basis vectors + translation), row-vector
        // convention (v' = v * M). Our translator wants a column-major float[16]
        // (column-vector), i.e. the transpose with the row vectors placed in
        // columns. world[c*4+r]: column c, row r.
        void ToWorld16(const Matrix3& m, float out[16])
        {
            for (int i = 0; i < 16; ++i) out[i] = 0.0f;
            for (int c = 0; c < 3; ++c)
            {
                const Point3 row = m.GetRow(c); // basis vector c (x,y,z of column c in col-major)
                out[c * 4 + 0] = row.x;
                out[c * 4 + 1] = row.y;
                out[c * 4 + 2] = row.z;
            }
            const Point3 t = m.GetTrans();
            out[12] = t.x; out[13] = t.y; out[14] = t.z;
            out[15] = 1.0f;
        }

        std::string WideToUtf8(const MCHAR* s)
        {
#ifdef UNICODE
            if (!s) return {};
            int len = ::WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0, nullptr, nullptr);
            if (len <= 1) return {};
            std::string out(static_cast<size_t>(len - 1), '\0');
            ::WideCharToMultiByte(CP_UTF8, 0, s, -1, out.data(), len, nullptr, nullptr);
            return out;
#else
            return s ? std::string(s) : std::string{};
#endif
        }

        bool ReadFileBytes(const MCHAR* path, std::vector<uint8_t>& out)
        {
            const std::string p = WideToUtf8(path);
            if (p.empty()) return false;
            std::ifstream f(p, std::ios::binary);
            if (!f) return false;
            out.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
            return !out.empty();
        }

        // Extract a Max material into MaterialData. Uses the generic Mtl color +
        // a diffuse BitmapTex file for the base-colour channel. Physical-material
        // metalness/roughness param access is left as a TODO.
        void ExtractMaterial(Mtl* mtl, TimeValue t, MaterialData& mat)
        {
            if (!mtl) return;

            const Color diff = mtl->GetDiffuse(0);
            mat.baseColor[0] = diff.r;
            mat.baseColor[1] = diff.g;
            mat.baseColor[2] = diff.b;

            const float shininess = mtl->GetShininess(0); // 0..1 glossiness-ish
            mat.roughness = 1.0f - (shininess > 0.0f ? shininess : 0.0f);

            const Color self = mtl->GetSelfIllumColor(0);
            mat.emissive[0] = self.r; mat.emissive[1] = self.g; mat.emissive[2] = self.b;
            if (self.r + self.g + self.b > 0.0f) mat.emissiveStrength = 1.0f;

            // Diffuse map -> base-colour texture.
            Texmap* tex = mtl->GetSubTexmap(ID_DI);
            if (tex && tex->ClassID() == Class_ID(BMTEX_CLASS_ID, 0))
            {
                BitmapTex* bmt = static_cast<BitmapTex*>(tex);
                std::vector<uint8_t> bytes;
                if (ReadFileBytes(bmt->GetMapName(), bytes))
                {
                    const size_t ch = static_cast<size_t>(TexChannel::BaseColor);
                    mat.textureIds[ch] = std::hash<std::string>{}(WideToUtf8(bmt->GetMapName())) ^ bytes.size();
                    mat.textures[ch] = std::move(bytes);
                    mat.baseColor[0] = mat.baseColor[1] = mat.baseColor[2] = 1.0f;
                }
            }
        }

        void CaptureMeshNode(SceneTranslator& tr, CommandEncoder& enc, INode* node, TimeValue t)
        {
            const ObjectState os = node->EvalWorldState(t);
            Object* obj = os.obj;
            if (!obj || obj->SuperClassID() != GEOMOBJECT_CLASS_ID) return;
            if (!obj->CanConvertToType(triObjectClassID)) return;

            TriObject* tri = static_cast<TriObject*>(obj->ConvertToType(t, triObjectClassID));
            if (!tri) return;
            const bool deleteTri = (tri != static_cast<TriObject*>(obj));

            Mesh& mesh = tri->GetMesh();
            mesh.buildNormals();
            const bool hasUV = (mesh.numTVerts > 0 && mesh.tvFace != nullptr);

            MeshData data;
            // Per-corner expansion (like Blender's per-loop) so positions, UVs and
            // face normals stay aligned; winding is reversed once by the shared
            // translator (Z-up RH -> Babylon LH).
            for (int f = 0; f < mesh.numFaces; ++f)
            {
                const Face& face = mesh.faces[f];
                const Point3 fn = mesh.getFaceNormal(f);
                for (int c = 0; c < 3; ++c)
                {
                    const DWORD vi = face.v[c];
                    const Point3& p = mesh.verts[vi];
                    data.positions.push_back(p.x);
                    data.positions.push_back(p.y);
                    data.positions.push_back(p.z);
                    data.normals.push_back(fn.x);
                    data.normals.push_back(fn.y);
                    data.normals.push_back(fn.z);
                    if (hasUV)
                    {
                        const UVVert& uv = mesh.tVerts[mesh.tvFace[f].t[c]];
                        data.uvs.push_back(uv.x);
                        data.uvs.push_back(1.0f - uv.y); // flip V for Babylon's origin
                    }
                    data.indices.push_back(static_cast<uint32_t>(data.indices.size()));
                }
            }

            MaterialData mat;
            ExtractMaterial(node->GetMtl(), t, mat);

            float world[16];
            ToWorld16(node->GetObjectTM(t), world);

            const std::string key = WideToUtf8(node->GetName());
            tr.SyncMesh(enc, key, key, world, &data, mat);

            if (deleteTri) tri->DeleteMe();
        }

        void CaptureLightNode(SceneTranslator& tr, CommandEncoder& enc, INode* node, TimeValue t)
        {
            const ObjectState os = node->EvalWorldState(t);
            Object* obj = os.obj;
            if (!obj || obj->SuperClassID() != LIGHT_CLASS_ID) return;

            LightObject* lightObj = static_cast<LightObject*>(obj);
            Interval iv = FOREVER;
            LightState ls;
            lightObj->EvalLightState(t, iv, &ls);

            LightData light;
            light.color[0] = ls.color.r;
            light.color[1] = ls.color.g;
            light.color[2] = ls.color.b;
            light.intensity = ls.intens;

            const CoordinateBasis& basis = tr.Basis();
            const Matrix3 tm = node->GetObjTMAfterWSM(t);
            if (ls.type == DIRECT_LGT)
            {
                light.type = LightType::Directional;
                // Max lights aim down local -Z; world dir = -(row 2 of the TM).
                const Point3 d = -tm.GetRow(2);
                const Vec3 v = basis.Dir(d.x, d.y, d.z);
                light.vec[0] = v.x; light.vec[1] = v.y; light.vec[2] = v.z;
            }
            else
            {
                light.type = LightType::Point; // omni + spot approximated as point
                const Point3 p = tm.GetTrans();
                const Vec3 v = basis.Point(p.x, p.y, p.z);
                light.vec[0] = v.x; light.vec[1] = v.y; light.vec[2] = v.z;
            }

            const std::string key = WideToUtf8(node->GetName());
            tr.SyncLight(enc, key, light, nullptr);
        }

        void RecurseNodes(SceneTranslator& tr, CommandEncoder& enc, INode* node, TimeValue t, int& lightCount)
        {
            if (!node) return;
            const ObjectState os = node->EvalWorldState(t);
            if (os.obj)
            {
                const SClass_ID scid = os.obj->SuperClassID();
                if (scid == GEOMOBJECT_CLASS_ID)
                {
                    CaptureMeshNode(tr, enc, node, t);
                }
                else if (scid == LIGHT_CLASS_ID)
                {
                    CaptureLightNode(tr, enc, node, t);
                    ++lightCount;
                }
            }
            for (int i = 0; i < node->NumberOfChildren(); ++i)
            {
                RecurseNodes(tr, enc, node->GetChildNode(i), t, lightCount);
            }
        }

        void CaptureViewportCamera(SceneTranslator& tr, CommandEncoder& enc, Interface* ip)
        {
            ViewExp& view = ip->GetActiveViewExp();
            if (!view.IsAlive()) return;
            Matrix3 affineTM;
            view.GetAffineTM(affineTM);
            // The view matrix is world->view; invert to get the camera (eye) TM.
            const Matrix3 camTM = Inverse(affineTM);
            const Point3 eye = camTM.GetTrans();
            const Point3 fwd = -camTM.GetRow(2); // camera looks down -Z
            const Point3 target = eye + fwd * 100.0f;

            const CoordinateBasis& basis = tr.Basis();
            const Vec3 e = basis.Point(eye.x, eye.y, eye.z);
            const Vec3 tgt = basis.Point(target.x, target.y, target.z);
            CameraData cam = CameraData::Arc(e, tgt);
            tr.SyncCamera(enc, cam);
        }
    } // namespace

    std::vector<uint8_t> CaptureScene(SceneTranslator& tr, Interface* ip, bool incremental)
    {
        CommandEncoder enc;
        if (incremental)
        {
            tr.BeginSync();
        }
        else
        {
            const float clear[4] = {0.05f, 0.06f, 0.09f, 1.0f};
            tr.BeginSnapshot(enc, clear);
        }

        const TimeValue t = ip->GetTime();
        int lightCount = 0;
        RecurseNodes(tr, enc, ip->GetRootNode(), t, lightCount);
        CaptureViewportCamera(tr, enc, ip);

        if (incremental)
        {
            tr.EmitRemovals(enc);
        }
        else
        {
            tr.EmitDefaultFill(enc, lightCount > 0);
        }
        return enc.Finish();
    }
}
