// ===========================================================================
// BabylonLivePreview — live scene script (runs inside Babylon Native)
// ===========================================================================
// Loaded and evaluated by the shared core after babylon.max.js. Owns the
// NativeEngine, the current scene, the render loop, and the host-command
// decoder (`applyCommands`).
//
// Native globals available: `window` (polyfill). Native callbacks may be
// registered on the global object by the core in later milestones.
// ===========================================================================

var engine = new BABYLON.NativeEngine();
var currentScene = null;

console.log("[live_preview] script loaded, Babylon " + BABYLON.Engine.Version);

// Babylon expects a rendering canvas; the Window polyfill stands in for it.
engine.getRenderingCanvas = function () { return window; };
engine.getInputElement = function () { return 0; };

// Registry mapping host node ids (as strings) to Babylon nodes, so incremental
// updates from the DCC can find their targets (mirrors the reference's
// uniqueId lookup).
var _nodeById = {};

function _registerNode(id, node) {
    if (node) { node._blpId = id; _nodeById[String(id)] = node; }
    return node;
}

function _findNode(id) {
    return _nodeById[String(id)] || null;
}

// ---------------------------------------------------------------------------
// Default scene — gives M1 something to render/read back immediately.
// ---------------------------------------------------------------------------
function createDefaultScene() {
    var scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(0.15, 0.17, 0.22, 1.0);

    var camera = new BABYLON.ArcRotateCamera(
        "camera", -Math.PI / 3, Math.PI / 3, 8, BABYLON.Vector3.Zero(), scene);

    var light = new BABYLON.HemisphericLight(
        "light", new BABYLON.Vector3(0.3, 1.0, 0.2), scene);
    light.intensity = 0.9;

    var mat = new BABYLON.PBRMetallicRoughnessMaterial("mat", scene);
    mat.baseColor = new BABYLON.Color3(0.90, 0.35, 0.20);
    mat.metallic = 0.1;
    mat.roughness = 0.5;

    var sphere = BABYLON.MeshBuilder.CreateSphere("sphere", { diameter: 2, segments: 32 }, scene);
    sphere.position.y = 1;
    sphere.material = mat;

    var ground = BABYLON.MeshBuilder.CreateGround("ground", { width: 8, height: 8 }, scene);
    var gmat = new BABYLON.PBRMetallicRoughnessMaterial("groundMat", scene);
    gmat.baseColor = new BABYLON.Color3(0.35, 0.37, 0.40);
    gmat.metallic = 0.0;
    gmat.roughness = 0.9;
    ground.material = gmat;

    return scene;
}

function setCurrentScene(scene) {
    if (currentScene) {
        currentScene.dispose();
        engine.releaseEffects();
    }
    _nodeById = {};
    currentScene = scene;
}

setCurrentScene(createDefaultScene());
console.log("[live_preview] default scene created");

// ---------------------------------------------------------------------------
// Host -> Babylon command decoder (M2 fills in the record handlers).
// Buffer: [u32 magic 'BLPC'][u16 version][u16 count] then records.
// ---------------------------------------------------------------------------
var _BLP_MAGIC = 0x43504C42; // 'BLPC'

function applyCommands(buf) {
    if (!currentScene || !buf) return;
    var view = new DataView(buf);
    var off = 0;
    if (view.byteLength < 8) return;
    var magic = view.getUint32(off, true); off += 4;
    if (magic !== _BLP_MAGIC) { console.error("[BLP] bad command magic"); return; }
    /* version */ view.getUint16(off, true); off += 2;
    var count = view.getUint16(off, true); off += 2;

    for (var i = 0; i < count; i++) {
        var type = view.getUint16(off, true); off += 2;
        off = _applyCommand(type, view, off);
        if (off < 0) { console.error("[BLP] command decode aborted at record " + i); return; }
    }
}

function _applyCommand(type, view, off) {
    switch (type) {
        case 1: return _cmdUpsertNode(view, off);
        case 2: return _cmdRemoveNode(view, off);
        case 3: return _cmdSetTransform(view, off);
        case 4: return _cmdUpsertMeshGeometry(view, off);
        case 5: return _cmdUpsertMaterial(view, off);
        case 6: return _cmdUpsertLight(view, off);
        case 7: return _cmdSetCamera(view, off);
        case 10: return _cmdResetScene(view, off);
        case 11: return _cmdSetClearColor(view, off);
        default:
            console.error("[BLP] unknown command type " + type);
            return -1; // unknown length -> abort (encoder/decoder must stay in sync)
    }
}

function _cmdSetTransform(view, off) {
    var id = _readU64(view, off); off += 8;
    var px = view.getFloat32(off, true); off += 4;
    var py = view.getFloat32(off, true); off += 4;
    var pz = view.getFloat32(off, true); off += 4;
    var qx = view.getFloat32(off, true); off += 4;
    var qy = view.getFloat32(off, true); off += 4;
    var qz = view.getFloat32(off, true); off += 4;
    var qw = view.getFloat32(off, true); off += 4;
    var sx = view.getFloat32(off, true); off += 4;
    var sy = view.getFloat32(off, true); off += 4;
    var sz = view.getFloat32(off, true); off += 4;
    var node = _findNode(id);
    if (node) {
        node.position.set(px, py, pz);
        if (!node.rotationQuaternion) node.rotationQuaternion = new BABYLON.Quaternion();
        node.rotationQuaternion.set(qx, qy, qz, qw);
        if (node.scaling) node.scaling.set(sx, sy, sz);
    }
    return off;
}

function _cmdUpsertMaterial(view, off) {
    var id = _readU64(view, off); off += 8;
    var r = view.getFloat32(off, true); off += 4;
    var g = view.getFloat32(off, true); off += 4;
    var b = view.getFloat32(off, true); off += 4;
    var a = view.getFloat32(off, true); off += 4;
    var metallic = view.getFloat32(off, true); off += 4;
    var roughness = view.getFloat32(off, true); off += 4;
    var node = _findNode(id);
    if (node) {
        // Always use Babylon's PBR metallic/roughness material.
        var m = node.material;
        if (!m || m.getClassName() !== "PBRMetallicRoughnessMaterial") {
            if (m) { try { m.dispose(); } catch (e) {} }
            m = new BABYLON.PBRMetallicRoughnessMaterial("mat" + id, currentScene);
            node.material = m;
        }
        m.baseColor.set(r, g, b);
        m.metallic = metallic;
        m.roughness = roughness;
        m.alpha = a;
        m.backFaceCulling = false;
    }
    return off;
}

function _cmdSetCamera(view, off) {
    var mode = view.getUint8(off); off += 1;
    if (mode === 0) {
        // ArcRotate: alpha, beta, radius, target[3]
        var alpha = view.getFloat32(off, true); off += 4;
        var beta = view.getFloat32(off, true); off += 4;
        var radius = view.getFloat32(off, true); off += 4;
        var tx = view.getFloat32(off, true); off += 4;
        var ty = view.getFloat32(off, true); off += 4;
        var tz = view.getFloat32(off, true); off += 4;
        var target = new BABYLON.Vector3(tx, ty, tz);
        var cam = currentScene.activeCamera;
        if (!cam || !(cam instanceof BABYLON.ArcRotateCamera)) {
            cam = new BABYLON.ArcRotateCamera("camera", alpha, beta, radius, target, currentScene);
            currentScene.activeCamera = cam;
        } else {
            cam.alpha = alpha; cam.beta = beta; cam.radius = radius; cam.setTarget(target);
        }
    } else {
        // Matrices: view[16] + projection[16] (column-major). Apply position from
        // the inverse view matrix (full free-camera support comes later).
        var m = []; var i;
        for (i = 0; i < 32; i++) { m.push(view.getFloat32(off, true)); off += 4; }
        var cam2 = currentScene.activeCamera;
        if (cam2) {
            try {
                var viewMat = BABYLON.Matrix.FromArray(m.slice(0, 16));
                cam2.position.copyFrom(viewMat.clone().invert().getTranslation());
            } catch (e) { /* ignore during bring-up */ }
        }
    }
    return off;
}

function _cmdRemoveNode(view, off) {
    var id = _readU64(view, off); off += 8;
    var node = _findNode(id);
    if (node) { try { node.dispose(); } catch (e) {} delete _nodeById[String(id)]; }
    return off;
}

function _readString(view, off) {
    var len = view.getUint16(off, true); off += 2;
    var s = "";
    for (var i = 0; i < len; i++) { s += String.fromCharCode(view.getUint8(off + i)); }
    return [s, off + len];
}

// Reads pos[3], quat[4], scale[3] and applies to a node (guards for lights).
function _applyTransform(node, view, off) {
    var px = view.getFloat32(off, true); off += 4;
    var py = view.getFloat32(off, true); off += 4;
    var pz = view.getFloat32(off, true); off += 4;
    var qx = view.getFloat32(off, true); off += 4;
    var qy = view.getFloat32(off, true); off += 4;
    var qz = view.getFloat32(off, true); off += 4;
    var qw = view.getFloat32(off, true); off += 4;
    var sx = view.getFloat32(off, true); off += 4;
    var sy = view.getFloat32(off, true); off += 4;
    var sz = view.getFloat32(off, true); off += 4;
    if (node) {
        if (node.position) node.position.set(px, py, pz);
        if (node.rotationQuaternion !== undefined) {
            if (!node.rotationQuaternion) node.rotationQuaternion = new BABYLON.Quaternion();
            node.rotationQuaternion.set(qx, qy, qz, qw);
        }
        if (node.scaling) node.scaling.set(sx, sy, sz);
    }
    return off;
}

function _cmdUpsertNode(view, off) {
    var id = _readU64(view, off); off += 8;
    var parentId = _readU64(view, off); off += 8;
    var kind = view.getUint16(off, true); off += 2;
    var sr = _readString(view, off); var name = sr[0]; off = sr[1];
    var node = _findNode(id);
    if (!node) {
        if (kind === 1) node = new BABYLON.Mesh(name || ("mesh" + id), currentScene);
        else node = new BABYLON.TransformNode(name || ("node" + id), currentScene);
        _registerNode(id, node);
    }
    if (parentId) { var p = _findNode(parentId); if (p) node.parent = p; }
    return _applyTransform(node, view, off);
}

function _cmdUpsertMeshGeometry(view, off) {
    var id = _readU64(view, off); off += 8;
    var vtx = view.getUint32(off, true); off += 4;
    var hasN = view.getUint8(off); off += 1;
    var hasUV = view.getUint8(off); off += 1;
    var idx = view.getUint32(off, true); off += 4;
    var i;
    var positions = new Float32Array(vtx * 3);
    for (i = 0; i < vtx * 3; i++) { positions[i] = view.getFloat32(off, true); off += 4; }
    var normals = null;
    if (hasN) { normals = new Float32Array(vtx * 3); for (i = 0; i < vtx * 3; i++) { normals[i] = view.getFloat32(off, true); off += 4; } }
    var uvs = null;
    if (hasUV) { uvs = new Float32Array(vtx * 2); for (i = 0; i < vtx * 2; i++) { uvs[i] = view.getFloat32(off, true); off += 4; } }
    var indices = new Uint32Array(idx);
    for (i = 0; i < idx; i++) { indices[i] = view.getUint32(off, true); off += 4; }
    var node = _findNode(id);
    if (node) {
        var vd = new BABYLON.VertexData();
        vd.positions = positions;
        vd.indices = indices;
        if (normals) { vd.normals = normals; }
        else { var n = []; BABYLON.VertexData.ComputeNormals(positions, indices, n); vd.normals = n; }
        if (uvs) { vd.uvs = uvs; }
        vd.applyToMesh(node, true);
    }
    return off;
}

function _cmdUpsertLight(view, off) {
    var id = _readU64(view, off); off += 8;
    var type = view.getUint16(off, true); off += 2;
    var vx = view.getFloat32(off, true); off += 4;
    var vy = view.getFloat32(off, true); off += 4;
    var vz = view.getFloat32(off, true); off += 4;
    var r = view.getFloat32(off, true); off += 4;
    var g = view.getFloat32(off, true); off += 4;
    var b = view.getFloat32(off, true); off += 4;
    var intensity = view.getFloat32(off, true); off += 4;
    var node = _findNode(id);

    // The vector is a direction for directional/hemispheric lights, or a world
    // position for point lights. Recreate if missing or if the type changed.
    var desired = (type === 1) ? "DirectionalLight" : (type === 2) ? "PointLight" : "HemisphericLight";
    if (!node || node.getClassName() !== desired) {
        if (node) { try { node.dispose(); } catch (e) {} }
        var vec = new BABYLON.Vector3(vx, vy, vz);
        if (type === 1) node = new BABYLON.DirectionalLight("light" + id, vec, currentScene);
        else if (type === 2) node = new BABYLON.PointLight("light" + id, vec, currentScene);
        else node = new BABYLON.HemisphericLight("light" + id, vec, currentScene);
        _registerNode(id, node);
    } else if (type === 2) {
        if (node.position) node.position.set(vx, vy, vz);
    } else if (node.direction) {
        node.direction.set(vx, vy, vz);
    }
    if (node.diffuse) node.diffuse.set(r, g, b);
    node.intensity = intensity;
    return off;
}

function _cmdResetScene(view, off) {
    setCurrentScene(new BABYLON.Scene(engine));
    var cam = new BABYLON.ArcRotateCamera("camera", -Math.PI / 2, Math.PI / 3, 10, BABYLON.Vector3.Zero(), currentScene);
    currentScene.activeCamera = cam;
    return off;
}

function _cmdSetClearColor(view, off) {
    var r = view.getFloat32(off, true); off += 4;
    var g = view.getFloat32(off, true); off += 4;
    var b = view.getFloat32(off, true); off += 4;
    var a = view.getFloat32(off, true); off += 4;
    if (currentScene) currentScene.clearColor = new BABYLON.Color4(r, g, b, a);
    return off;
}

// DataView has no 64-bit float-safe int reader across all engines; read as two
// 32-bit halves and combine (ids stay < 2^53 in practice).
function _readU64(view, off) {
    var lo = view.getUint32(off, true);
    var hi = view.getUint32(off + 4, true);
    return hi * 4294967296 + lo;
}

// Debug/escape hatch invoked by LivePreviewSession::Eval.
function blpEval(code) {
    try { return eval(code); }
    catch (e) { console.error("[BLP] blpEval error: " + e); return null; }
}

// ---------------------------------------------------------------------------
// Render loop
// ---------------------------------------------------------------------------
var _notifiedReady = false;

engine.runRenderLoop(function () {
    if (currentScene && currentScene.activeCamera) {
        currentScene.render();
        if (!_notifiedReady) {
            _notifiedReady = true;
            console.log("[live_preview] first frame rendered");
            if (typeof _blpNotifyReady === "function") {
                _blpNotifyReady();
            }
        }
    }
});
