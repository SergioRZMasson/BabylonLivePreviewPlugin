// ===========================================================================
// BabylonLivePreview — Maya scene capture implementation
// ===========================================================================
#include "MayaCapture.h"

#include <maya/MDagPath.h>
#include <maya/MFloatArray.h>
#include <maya/MFloatVectorArray.h>
#include <maya/MFnCamera.h>
#include <maya/MFnDagNode.h>
#include <maya/MFnDependencyNode.h>
#include <maya/MFnLight.h>
#include <maya/MFnMesh.h>
#include <maya/MIntArray.h>
#include <maya/MItDag.h>
#include <maya/MItMeshPolygon.h>
#include <maya/MMatrix.h>
#include <maya/MObjectArray.h>
#include <maya/MPlug.h>
#include <maya/MPlugArray.h>
#include <maya/MPointArray.h>
#include <maya/MString.h>

#include <cstdio>
#include <fstream>
#include <string>

namespace BabylonLivePreview::MayaPlugin
{
    namespace
    {
        // Maya MMatrix is row-major / row-vector (v' = v * M, translation in row
        // 3). Our translator expects a column-major/column-vector matrix, i.e.
        // the transpose: world[c*4+r] = M(c, r).
        void ToWorld16(const MMatrix& m, float out[16])
        {
            for (int c = 0; c < 4; ++c)
                for (int r = 0; r < 4; ++r)
                    out[c * 4 + r] = static_cast<float>(m(c, r));
        }

        bool ReadFloat3(const MFnDependencyNode& fn, const char* attr, float out[3])
        {
            MStatus st;
            MPlug plug = fn.findPlug(attr, true, &st);
            if (!st || plug.isNull() || plug.numChildren() < 3) return false;
            for (unsigned i = 0; i < 3; ++i) out[i] = plug.child(i).asFloat();
            return true;
        }

        bool ReadFloat(const MFnDependencyNode& fn, const char* attr, float& out)
        {
            MStatus st;
            MPlug plug = fn.findPlug(attr, true, &st);
            if (!st || plug.isNull()) return false;
            out = plug.asFloat();
            return true;
        }

        // Read the encoded image bytes referenced by a Maya `file` node.
        bool ReadFileNodeBytes(const MObject& fileNode, std::vector<uint8_t>& outBytes, uint64_t& outId)
        {
            if (fileNode.isNull() || !fileNode.hasFn(MFn::kFileTexture)) return false;
            MStatus st;
            MFnDependencyNode fileFn(fileNode);
            MPlug namePlug = fileFn.findPlug("fileTextureName", true, &st);
            if (!st || namePlug.isNull()) return false;
            MString path = namePlug.asString();
            std::ifstream f(path.asChar(), std::ios::binary);
            if (!f) return false;
            outBytes.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
            if (outBytes.empty()) return false;
            // Identity: hash the path + size (cheap change token).
            uint64_t h = 1469598103934665603ull;
            for (const char* c = path.asChar(); *c; ++c) { h ^= static_cast<uint8_t>(*c); h *= 1099511628211ull; }
            outId = h ^ outBytes.size();
            return true;
        }

        // The upstream source node driving `attr` on `fn` (or null if unconnected).
        MObject ConnectedSourceNode(const MFnDependencyNode& fn, const char* attr)
        {
            MStatus st;
            MPlug plug = fn.findPlug(attr, true, &st);
            if (!st || plug.isNull()) return MObject::kNullObj;
            MPlugArray src;
            plug.connectedTo(src, true, false, &st);
            if (!st || src.length() == 0) return MObject::kNullObj;
            return src[0].node();
        }

        // The `fileTextureName` of a Maya `file` node (empty if not a file node).
        std::string FileNodePath(const MObject& fileNode)
        {
            if (fileNode.isNull() || !fileNode.hasFn(MFn::kFileTexture)) return {};
            MStatus st;
            MFnDependencyNode fileFn(fileNode);
            MPlug namePlug = fileFn.findPlug("fileTextureName", true, &st);
            if (!st || namePlug.isNull()) return {};
            return namePlug.asString().asChar();
        }

        // Follow a (possibly connected) plug to a `file` node and read its bytes.
        // Mirrors capture.py's file-texture path.
        bool ReadConnectedFileTexture(const MFnDependencyNode& matFn, const char* attr,
            std::vector<uint8_t>& outBytes, uint64_t& outId)
        {
            return ReadFileNodeBytes(ConnectedSourceNode(matFn, attr), outBytes, outId);
        }

        // Normal maps reach `normalCamera` through a bump2d / aiNormalMap node;
        // trace one level of indirection to the underlying `file` node.
        bool ReadNormalTexture(const MFnDependencyNode& matFn,
            std::vector<uint8_t>& outBytes, uint64_t& outId)
        {
            MObject node = ConnectedSourceNode(matFn, "normalCamera");
            if (node.isNull()) return false;
            if (node.hasFn(MFn::kFileTexture)) return ReadFileNodeBytes(node, outBytes, outId);
            MFnDependencyNode bumpFn(node);
            for (const char* a : {"bumpValue", "input", "normalMap", "inColor", "bumpNormal"})
            {
                MObject f = ConnectedSourceNode(bumpFn, a);
                if (!f.isNull() && f.hasFn(MFn::kFileTexture))
                    return ReadFileNodeBytes(f, outBytes, outId);
            }
            return false;
        }

        void ExtractMaterial(const MFnMesh& meshFn, MaterialData& mat)
        {
            MStatus st;
            MObjectArray shaders;
            MIntArray faceIndices;
            if (!meshFn.getConnectedShaders(0, shaders, faceIndices) || shaders.length() == 0)
                return;

            // shaders[0] is a shadingEngine; follow .surfaceShader to the material.
            MFnDependencyNode seFn(shaders[0]);
            MPlug ssPlug = seFn.findPlug("surfaceShader", true, &st);
            if (!st || ssPlug.isNull()) return;
            MPlugArray src;
            ssPlug.connectedTo(src, true, false, &st);
            if (!st || src.length() == 0) return;

            MObject matNode = src[0].node();
            MFnDependencyNode matFn(matNode);

            float c3[3];
            if (ReadFloat3(matFn, "baseColor", c3) || ReadFloat3(matFn, "color", c3))
            {
                mat.baseColor[0] = c3[0]; mat.baseColor[1] = c3[1]; mat.baseColor[2] = c3[2];
            }
            float f;
            if (ReadFloat(matFn, "metalness", f)) mat.metallic = f;
            if (ReadFloat(matFn, "specularRoughness", f)) mat.roughness = f;
            float e3[3];
            if (ReadFloat3(matFn, "emissionColor", e3) || ReadFloat3(matFn, "incandescence", e3))
            {
                mat.emissive[0] = e3[0]; mat.emissive[1] = e3[1]; mat.emissive[2] = e3[2];
                float es = 1.0f;
                ReadFloat(matFn, "emission", es);
                mat.emissiveStrength = es;
            }

            // Base-color file texture (standardSurface baseColor / lambert color).
            std::vector<uint8_t> bytes;
            uint64_t id = 0;
            if (ReadConnectedFileTexture(matFn, "baseColor", bytes, id) ||
                ReadConnectedFileTexture(matFn, "color", bytes, id))
            {
                const size_t ch = static_cast<size_t>(TexChannel::BaseColor);
                mat.textures[ch] = std::move(bytes);
                mat.textureIds[ch] = id;
                // A base texture multiplies baseColor; use white so it isn't tinted.
                mat.baseColor[0] = mat.baseColor[1] = mat.baseColor[2] = 1.0f;
            }

            // Metallic-roughness: glTF packs metal (B) + rough (G) in one image.
            // Emit the combined channel only when metalness and specularRoughness
            // are driven by the SAME file node (mirrors Blender's ORM detection).
            {
                MObject metalNode = ConnectedSourceNode(matFn, "metalness");
                MObject roughNode = ConnectedSourceNode(matFn, "specularRoughness");
                std::string metalPath = FileNodePath(metalNode);
                std::string roughPath = FileNodePath(roughNode);
                std::vector<uint8_t> mrBytes;
                uint64_t mrId = 0;
                if (!roughPath.empty() && roughPath == metalPath &&
                    ReadFileNodeBytes(roughNode, mrBytes, mrId))
                {
                    const size_t ch = static_cast<size_t>(TexChannel::MetallicRoughness);
                    mat.textures[ch] = std::move(mrBytes);
                    mat.textureIds[ch] = mrId;
                }
            }

            // Normal map (via bump2d / aiNormalMap on normalCamera).
            {
                std::vector<uint8_t> nBytes;
                uint64_t nId = 0;
                if (ReadNormalTexture(matFn, nBytes, nId))
                {
                    const size_t ch = static_cast<size_t>(TexChannel::Normal);
                    mat.textures[ch] = std::move(nBytes);
                    mat.textureIds[ch] = nId;
                }
            }

            // Emissive texture (standardSurface emissionColor / lambert incandescence).
            {
                std::vector<uint8_t> eBytes;
                uint64_t eId = 0;
                if (ReadConnectedFileTexture(matFn, "emissionColor", eBytes, eId) ||
                    ReadConnectedFileTexture(matFn, "incandescence", eBytes, eId))
                {
                    const size_t ch = static_cast<size_t>(TexChannel::Emissive);
                    mat.textures[ch] = std::move(eBytes);
                    mat.textureIds[ch] = eId;
                    if (mat.emissiveStrength <= 0.0f) mat.emissiveStrength = 1.0f;
                    mat.emissive[0] = mat.emissive[1] = mat.emissive[2] = 1.0f;
                }
            }
        }

        void CaptureMesh(SceneTranslator& tr, CommandEncoder& enc, const MDagPath& path)
        {
            MStatus st;
            MFnMesh meshFn(path, &st);
            if (!st) return;

            MPointArray pts;
            if (!meshFn.getPoints(pts, MSpace::kObject) || pts.length() == 0) return;

            MFloatVectorArray norms;
            const bool haveNormals = meshFn.getVertexNormals(false, norms, MSpace::kObject) &&
                norms.length() == pts.length();

            MIntArray triCounts, triVerts;
            if (!meshFn.getTriangles(triCounts, triVerts) || triVerts.length() == 0) return;

            MeshData mesh;
            mesh.positions.resize(pts.length() * 3);
            for (unsigned i = 0; i < pts.length(); ++i)
            {
                mesh.positions[i * 3] = static_cast<float>(pts[i].x);
                mesh.positions[i * 3 + 1] = static_cast<float>(pts[i].y);
                mesh.positions[i * 3 + 2] = static_cast<float>(pts[i].z);
            }
            if (haveNormals)
            {
                mesh.normals.resize(norms.length() * 3);
                for (unsigned i = 0; i < norms.length(); ++i)
                {
                    mesh.normals[i * 3] = norms[i].x;
                    mesh.normals[i * 3 + 1] = norms[i].y;
                    mesh.normals[i * 3 + 2] = norms[i].z;
                }
            }

            // Per-vertex UVs (positions are vertex-indexed, so collapse Maya's
            // per-face-vertex UVs to one value per control vertex; seams take the
            // last-written corner). V is flipped for Babylon's top-left origin.
            if (meshFn.numUVs() > 0)
            {
                mesh.uvs.assign(pts.length() * 2, 0.0f);
                bool anyUV = false;
                for (MItMeshPolygon polyIt(path); !polyIt.isDone(); polyIt.next())
                {
                    if (!polyIt.hasUVs()) continue;
                    const unsigned vc = polyIt.polygonVertexCount();
                    for (unsigned k = 0; k < vc; ++k)
                    {
                        float2 uv;
                        if (!polyIt.getUV(k, uv)) continue;
                        const int vId = polyIt.vertexIndex(k);
                        if (vId < 0 || static_cast<unsigned>(vId) >= pts.length()) continue;
                        mesh.uvs[vId * 2] = uv[0];
                        mesh.uvs[vId * 2 + 1] = 1.0f - uv[1];
                        anyUV = true;
                    }
                }
                if (!anyUV) mesh.uvs.clear();
            }
            mesh.indices.resize(triVerts.length());
            for (unsigned i = 0; i < triVerts.length(); ++i)
                mesh.indices[i] = static_cast<uint32_t>(triVerts[i]);

            MaterialData mat;
            ExtractMaterial(meshFn, mat);

            float world[16];
            ToWorld16(path.inclusiveMatrix(), world);

            const std::string key = path.fullPathName().asChar();
            const std::string name = path.partialPathName().asChar();
            tr.SyncMesh(enc, key, name, world, &mesh, mat);
        }

        void CaptureLight(SceneTranslator& tr, CommandEncoder& enc, const MDagPath& path)
        {
            MStatus st;
            MFnLight lightFn(path, &st);
            if (!st) return;

            LightData light;
            MColor col = lightFn.color();
            light.color[0] = col.r; light.color[1] = col.g; light.color[2] = col.b;
            light.intensity = lightFn.intensity();

            const MMatrix wm = path.inclusiveMatrix();
            const CoordinateBasis& basis = tr.Basis();

            if (path.hasFn(MFn::kDirectionalLight))
            {
                light.type = LightType::Directional;
                // Maya lights aim down local -Z; world dir = -(z axis of matrix).
                Vec3 d = basis.Dir(static_cast<float>(-wm(2, 0)),
                                   static_cast<float>(-wm(2, 1)),
                                   static_cast<float>(-wm(2, 2)));
                light.vec[0] = d.x; light.vec[1] = d.y; light.vec[2] = d.z;
            }
            else
            {
                light.type = LightType::Point; // point + spot approximated as point
                Vec3 p = basis.Point(static_cast<float>(wm(3, 0)),
                                     static_cast<float>(wm(3, 1)),
                                     static_cast<float>(wm(3, 2)));
                light.vec[0] = p.x; light.vec[1] = p.y; light.vec[2] = p.z;
            }

            const std::string key = path.fullPathName().asChar();
            tr.SyncLight(enc, key, light, nullptr);
        }

        bool CaptureCamera(SceneTranslator& tr, CommandEncoder& enc)
        {
            // Prefer the "persp" camera (present even in headless mayapy).
            MStatus st;
            MItDag it(MItDag::kDepthFirst, MFn::kCamera, &st);
            MDagPath chosen;
            for (; !it.isDone(); it.next())
            {
                MDagPath path;
                if (!it.getPath(path)) continue;
                MFnCamera cam(path, &st);
                if (!st) continue;
                if (cam.isOrtho()) continue;
                chosen = path;
                if (path.partialPathName() == MString("perspShape")) break;
            }
            if (!chosen.isValid()) return false;

            MFnCamera cam(chosen);
            MPoint eye = cam.eyePoint(MSpace::kWorld);
            MPoint tgt = cam.centerOfInterestPoint(MSpace::kWorld);
            const CoordinateBasis& basis = tr.Basis();
            Vec3 e = basis.Point(static_cast<float>(eye.x), static_cast<float>(eye.y), static_cast<float>(eye.z));
            Vec3 t = basis.Point(static_cast<float>(tgt.x), static_cast<float>(tgt.y), static_cast<float>(tgt.z));
            CameraData c = CameraData::Arc(e, t);
            return tr.SyncCamera(enc, c);
        }
    } // namespace

    std::vector<uint8_t> CaptureScene(SceneTranslator& tr, uint32_t /*width*/, uint32_t /*height*/,
        bool incremental)
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

        int lightCount = 0;
        MStatus st;
        for (MItDag it(MItDag::kDepthFirst, MFn::kInvalid, &st); !it.isDone(); it.next())
        {
            MDagPath path;
            if (!it.getPath(path)) continue;
            MObject node = path.node();
            MFnDagNode dagFn(path);
            if (dagFn.isIntermediateObject()) continue;

            if (node.hasFn(MFn::kMesh))
            {
                CaptureMesh(tr, enc, path);
            }
            else if (node.hasFn(MFn::kLight))
            {
                CaptureLight(tr, enc, path);
                ++lightCount;
            }
        }

        CaptureCamera(tr, enc);

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
