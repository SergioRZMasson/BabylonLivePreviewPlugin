// ===========================================================================
// Babylon Live Sync — SceneApplier (protocol decoder + scene mutation)
// ===========================================================================
// Transport-agnostic: decode a command buffer and mutate an injected
// BABYLON.Scene. The host (Babylon Native or a browser page) owns the engine
// and render loop and hands the scene in via setScene(). This is the TypeScript
// port of the validated Shared/Scripts/live_preview.js decoder, preserving its
// colour-space, environment and texture behaviour.
import type * as BJS from "babylonjs";
import { Babylon, getGlobalBabylon } from "./babylon";
import { CameraMode, CommandType, LightType, NodeKind, Reader, TextureChannel } from "./protocol";

export interface SceneApplierOptions {
    /** Babylon namespace. Defaults to the global `BABYLON`. */
    babylon?: Babylon;
    /** Host hook to create/replace the scene on a ResetScene command. */
    onResetScene?: () => BJS.Scene;
    /** Default .env bytes applied as IBL to every scene (optional). */
    environmentBuffer?: Uint8Array | null;
    /** Apply the standard image-processing config (default true). */
    imageProcessing?: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyNode = any;

export class SceneApplier {
    private readonly B: Babylon;
    private readonly opts: SceneApplierOptions;
    private scene: BJS.Scene | null = null;
    private nodeById: Record<string, AnyNode> = {};
    private envBuffer: Uint8Array | null;
    private texCounter = 0;

    constructor(options: SceneApplierOptions = {}) {
        this.opts = options;
        this.B = options.babylon ?? getGlobalBabylon();
        this.envBuffer = options.environmentBuffer ?? null;
    }

    /** The scene currently being driven. */
    getScene(): BJS.Scene | null {
        return this.scene;
    }

    /** Point the applier at a scene; resets the node registry + applies env/IP. */
    setScene(scene: BJS.Scene): void {
        this.scene = scene;
        this.nodeById = {};
        this.applyEnvironment();
        this.ensureImageProcessing();
    }

    /** Provide/replace the default environment (.env) bytes and re-apply. */
    setEnvironmentBuffer(bytes: Uint8Array | null): void {
        this.envBuffer = bytes;
        if (this.scene) {
            this.applyEnvironment();
        }
    }

    /** Decode one command buffer and apply it to the current scene. */
    apply(buffer: ArrayBuffer): void {
        if (!this.scene || !buffer) {
            return;
        }
        const r = new Reader(buffer);
        if (r.byteLength < 8) {
            return;
        }
        const magic = r.u32();
        if (magic !== 0x43504c42) {
            console.error("[live_sync] bad command magic");
            return;
        }
        r.u16(); // version (unchecked; additive commands stay compatible)
        const count = r.u16();
        for (let i = 0; i < count; i++) {
            const type = r.u16() as CommandType;
            try {
                this.applyCommand(type, r);
            } catch (e) {
                console.error("[live_sync] command " + type + " failed at record " + i + ": " + e);
                return;
            }
        }
    }

    // --- command dispatch ---------------------------------------------------

    private applyCommand(type: CommandType, r: Reader): void {
        switch (type) {
            case CommandType.UpsertNode: return this.cmdUpsertNode(r);
            case CommandType.RemoveNode: return this.cmdRemoveNode(r);
            case CommandType.SetTransform: return this.cmdSetTransform(r);
            case CommandType.UpsertMeshGeometry: return this.cmdUpsertMeshGeometry(r);
            case CommandType.UpsertMaterial: return this.cmdUpsertMaterial(r);
            case CommandType.UpsertLight: return this.cmdUpsertLight(r);
            case CommandType.SetCamera: return this.cmdSetCamera(r);
            case CommandType.UpsertMaterialTexture: return this.cmdUpsertMaterialTexture(r);
            case CommandType.ResetScene: return this.cmdResetScene();
            case CommandType.SetClearColor: return this.cmdSetClearColor(r);
            default:
                throw new Error("unknown command type " + type);
        }
    }

    // --- node registry ------------------------------------------------------

    private registerNode(id: number, node: AnyNode): AnyNode {
        if (node) {
            node._blpId = id;
            this.nodeById[String(id)] = node;
        }
        return node;
    }

    private findNode(id: number): AnyNode {
        return this.nodeById[String(id)] || null;
    }

    // --- environment + image processing (colour-space correctness) ----------

    private ensureImageProcessing(): void {
        const scene = this.scene;
        if (!scene || this.opts.imageProcessing === false) {
            return;
        }
        const B = this.B;
        const ip = scene.imageProcessingConfiguration;
        ip.isEnabled = true;
        // Materials output LINEAR (skip in-shader gamma); the readback is then
        // uniformly linear so the host framebuffer encodes exactly once.
        ip.applyByPostProcess = true;
        ip.toneMappingEnabled = true;
        ip.toneMappingType = B.ImageProcessingConfiguration.TONEMAPPING_ACES;
        ip.contrast = 1.0;
        ip.exposure = 1.0;
    }

    private applyEnvironment(): void {
        const scene = this.scene;
        if (!scene || !this.envBuffer) {
            return;
        }
        const B = this.B;
        try {
            const env = new B.CubeTexture(
                "data:environment.env",
                scene,
                { buffer: this.envBuffer, forcedExtension: ".env" } as never);
            scene.environmentTexture = env;
            scene.environmentIntensity = 1.0;
        } catch (e) {
            console.error("[live_sync] environment apply failed: " + e);
        }
        this.ensureImageProcessing();
    }

    // --- commands -----------------------------------------------------------

    private readTransform(node: AnyNode, r: Reader): void {
        const px = r.f32(), py = r.f32(), pz = r.f32();
        const qx = r.f32(), qy = r.f32(), qz = r.f32(), qw = r.f32();
        const sx = r.f32(), sy = r.f32(), sz = r.f32();
        if (!node) {
            return;
        }
        if (node.position) {
            node.position.set(px, py, pz);
        }
        if (node.rotationQuaternion !== undefined) {
            if (!node.rotationQuaternion) {
                node.rotationQuaternion = new this.B.Quaternion();
            }
            node.rotationQuaternion.set(qx, qy, qz, qw);
        }
        if (node.scaling) {
            node.scaling.set(sx, sy, sz);
        }
    }

    private cmdUpsertNode(r: Reader): void {
        const id = r.u64();
        const parentId = r.u64();
        const kind = r.u16();
        const name = r.string();
        let node = this.findNode(id);
        if (!node) {
            node = (kind === NodeKind.Mesh)
                ? new this.B.Mesh(name || ("mesh" + id), this.scene!)
                : new this.B.TransformNode(name || ("node" + id), this.scene!);
            this.registerNode(id, node);
        }
        if (parentId) {
            const p = this.findNode(parentId);
            if (p) {
                node.parent = p;
            }
        }
        this.readTransform(node, r);
    }

    private cmdRemoveNode(r: Reader): void {
        const id = r.u64();
        const node = this.findNode(id);
        if (node) {
            try { node.dispose(); } catch { /* ignore */ }
            delete this.nodeById[String(id)];
        }
    }

    private cmdSetTransform(r: Reader): void {
        const id = r.u64();
        this.readTransform(this.findNode(id), r);
    }

    private cmdUpsertMeshGeometry(r: Reader): void {
        const id = r.u64();
        const vtx = r.u32();
        const hasN = r.u8();
        const hasUV = r.u8();
        const idx = r.u32();
        const B = this.B;

        const positions = new Float32Array(vtx * 3);
        for (let i = 0; i < vtx * 3; i++) { positions[i] = r.f32(); }
        let normals: Float32Array | null = null;
        if (hasN) {
            normals = new Float32Array(vtx * 3);
            for (let i = 0; i < vtx * 3; i++) { normals[i] = r.f32(); }
        }
        let uvs: Float32Array | null = null;
        if (hasUV) {
            uvs = new Float32Array(vtx * 2);
            for (let i = 0; i < vtx * 2; i++) { uvs[i] = r.f32(); }
        }
        const indices = new Uint32Array(idx);
        for (let i = 0; i < idx; i++) { indices[i] = r.u32(); }

        const node = this.findNode(id);
        if (!node) {
            return;
        }
        const vd = new B.VertexData();
        vd.positions = positions as unknown as number[];
        vd.indices = indices as unknown as number[];
        if (normals) {
            vd.normals = normals as unknown as number[];
        } else {
            const n: number[] = [];
            B.VertexData.ComputeNormals(positions, indices, n);
            vd.normals = n;
        }
        if (uvs) {
            vd.uvs = uvs as unknown as number[];
        }
        vd.applyToMesh(node, true);
    }

    private ensurePbr(node: AnyNode, id: number): AnyNode {
        const B = this.B;
        let m = node.material;
        if (!m || m.getClassName() !== "PBRMetallicRoughnessMaterial") {
            if (m) { try { m.dispose(); } catch { /* ignore */ } }
            m = new B.PBRMetallicRoughnessMaterial("mat" + id, this.scene!);
            m.backFaceCulling = false;
            node.material = m;
        }
        return m;
    }

    private cmdUpsertMaterial(r: Reader): void {
        const id = r.u64();
        const cr = r.f32(), cg = r.f32(), cb = r.f32(), ca = r.f32();
        const metallic = r.f32(), roughness = r.f32();
        const er = r.f32(), eg = r.f32(), eb = r.f32(), estr = r.f32();
        const node = this.findNode(id);
        if (!node) {
            return;
        }
        const m = this.ensurePbr(node, id);
        m.baseColor.set(cr, cg, cb);
        m.metallic = metallic;
        m.roughness = roughness;
        m.alpha = ca;
        // Effective emission = colour * strength (Blender/Max/Maya model).
        // Premultiplying keeps "no emission" truly black — Babylon's unlit path
        // adds emissiveColor regardless of emissiveIntensity.
        if (m.emissiveColor) {
            m.emissiveColor.set(er * estr, eg * estr, eb * estr);
        }
        m.emissiveIntensity = 1.0;
    }

    private texSlot(channel: TextureChannel): string | null {
        switch (channel) {
            case TextureChannel.BaseColor: return "baseTexture";
            case TextureChannel.MetallicRoughness: return "metallicRoughnessTexture";
            case TextureChannel.Normal: return "normalTexture";
            case TextureChannel.Emissive: return "emissiveTexture";
            case TextureChannel.Occlusion: return "occlusionTexture";
            default: return null;
        }
    }

    private makeTexture(bytes: Uint8Array, gammaSpace: boolean): AnyNode {
        const B = this.B;
        // Babylon Native decodes an encoded-image buffer only when the url starts
        // with "data:" AND the buffer is the 8th positional arg (NOT the options
        // object). invertY is unsupported for Native textures, so the V flip is
        // baked into the UVs on the host side.
        const tex = new (B.Texture as unknown as new (...args: unknown[]) => AnyNode)(
            "data:blptex" + (this.texCounter++),
            this.scene,
            false, // noMipmap -> generate mips
            false, // invertY
            B.Texture.TRILINEAR_SAMPLINGMODE,
            null,  // onLoad
            (msg: unknown) => console.error("[live_sync] texture load failed: " + msg),
            bytes, // buffer
            true);  // deleteBuffer
        tex.gammaSpace = gammaSpace;
        return tex;
    }

    private setChannel(mat: AnyNode, channel: TextureChannel, tex: AnyNode): void {
        const slot = this.texSlot(channel);
        if (!slot) {
            if (tex) { try { tex.dispose(); } catch { /* ignore */ } }
            return;
        }
        const old = mat[slot];
        if (old && old !== tex) {
            try { old.dispose(); } catch { /* ignore */ }
        }
        mat[slot] = tex;
    }

    private cmdUpsertMaterialTexture(r: Reader): void {
        const id = r.u64();
        const channel = r.u16() as TextureChannel;
        r.u8(); // encoding (only EncodedImage today)
        const len = r.u32();
        const bytes = len > 0 ? r.take(len) : null;
        const node = this.findNode(id);
        if (!node) {
            return;
        }
        const mat = this.ensurePbr(node, id);
        if (!bytes) {
            this.setChannel(mat, channel, null); // clear
            return;
        }
        const gamma = (channel === TextureChannel.BaseColor || channel === TextureChannel.Emissive);
        this.setChannel(mat, channel, this.makeTexture(bytes, gamma));
    }

    private cmdUpsertLight(r: Reader): void {
        const id = r.u64();
        const type = r.u16() as LightType;
        const vx = r.f32(), vy = r.f32(), vz = r.f32();
        const cr = r.f32(), cg = r.f32(), cb = r.f32();
        const intensity = r.f32();
        const B = this.B;
        let node = this.findNode(id);

        // The vector is a direction (directional/hemispheric) or a world position
        // (point). Recreate on type change.
        const desired = (type === LightType.Directional) ? "DirectionalLight"
            : (type === LightType.Point) ? "PointLight" : "HemisphericLight";
        if (!node || node.getClassName() !== desired) {
            if (node) { try { node.dispose(); } catch { /* ignore */ } }
            const vec = new B.Vector3(vx, vy, vz);
            if (type === LightType.Directional) {
                node = new B.DirectionalLight("light" + id, vec, this.scene!);
            } else if (type === LightType.Point) {
                node = new B.PointLight("light" + id, vec, this.scene!);
            } else {
                node = new B.HemisphericLight("light" + id, vec, this.scene!);
            }
            this.registerNode(id, node);
        } else if (type === LightType.Point) {
            if (node.position) { node.position.set(vx, vy, vz); }
        } else if (node.direction) {
            node.direction.set(vx, vy, vz);
        }
        if (node.diffuse) { node.diffuse.set(cr, cg, cb); }
        node.intensity = intensity;
    }

    private cmdSetCamera(r: Reader): void {
        const B = this.B;
        const scene = this.scene!;
        const mode = r.u8() as CameraMode;
        if (mode === CameraMode.ArcRotate) {
            const alpha = r.f32(), beta = r.f32(), radius = r.f32();
            const tx = r.f32(), ty = r.f32(), tz = r.f32();
            let cam = scene.activeCamera as AnyNode;
            if (!cam || cam.getClassName() !== "ArcRotateCamera") {
                if (cam) { try { cam.dispose(); } catch { /* ignore */ } }
                cam = new B.ArcRotateCamera("camera", alpha, beta, radius, new B.Vector3(tx, ty, tz), scene);
                scene.activeCamera = cam;
            } else {
                cam.alpha = alpha;
                cam.beta = beta;
                cam.radius = radius;
                cam.setTarget(new B.Vector3(tx, ty, tz));
            }
        } else {
            const view: number[] = [];
            for (let i = 0; i < 16; i++) { view.push(r.f32()); }
            const proj: number[] = [];
            for (let i = 0; i < 16; i++) { proj.push(r.f32()); }
            let cam = scene.activeCamera as AnyNode;
            if (!cam || cam.getClassName() !== "FreeCamera") {
                if (cam) { try { cam.dispose(); } catch { /* ignore */ } }
                cam = new B.FreeCamera("camera", B.Vector3.Zero(), scene);
                scene.activeCamera = cam;
            }
            const V = B.Matrix.FromArray(view);
            const P = B.Matrix.FromArray(proj);
            cam.getViewMatrix = () => V;
            cam.getProjectionMatrix = () => P;
        }
        this.ensureImageProcessing();
    }

    private cmdResetScene(): void {
        if (this.opts.onResetScene) {
            this.setScene(this.opts.onResetScene());
        } else {
            // No host hook: keep the current scene, just drop the node registry.
            this.nodeById = {};
        }
    }

    private cmdSetClearColor(r: Reader): void {
        const cr = r.f32(), cg = r.f32(), cb = r.f32(), ca = r.f32();
        if (this.scene) {
            this.scene.clearColor = new this.B.Color4(cr, cg, cb, ca);
        }
    }
}
