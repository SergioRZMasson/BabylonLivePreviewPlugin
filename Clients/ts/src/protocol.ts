// ===========================================================================
// Babylon Live Sync — scene-delta protocol (decoder side)
// ===========================================================================
// Mirrors Shared/include/BabylonLivePreview/SceneProtocol.h and the C++/Python
// encoders. Buffer layout (little-endian):
//   [u32 magic 'BLPC'][u16 version][u16 count] then `count` records:
//   [u16 type][payload...]. Strings: [u16 byteLength][utf8].

export const COMMAND_MAGIC = 0x43504c42; // 'BLPC'
export const COMMAND_VERSION = 2;

export enum CommandType {
    UpsertNode = 1,
    RemoveNode = 2,
    SetTransform = 3,
    UpsertMeshGeometry = 4,
    UpsertMaterial = 5,
    UpsertLight = 6,
    SetCamera = 7,
    UpsertMaterialTexture = 8,
    ResetScene = 10,
    SetClearColor = 11,
}

export enum NodeKind {
    TransformNode = 0,
    Mesh = 1,
}

export enum LightType {
    Hemispheric = 0,
    Directional = 1,
    Point = 2,
}

export enum CameraMode {
    ArcRotate = 0,
    Matrices = 1,
}

export enum TextureChannel {
    BaseColor = 0,          // sRGB
    MetallicRoughness = 1,  // linear (glTF G=rough, B=metal)
    Normal = 2,             // linear
    Emissive = 3,           // sRGB
    Occlusion = 4,          // linear
}

// Sequential little-endian reader over a command buffer.
export class Reader {
    private readonly view: DataView;
    private readonly bytes: Uint8Array;
    public off = 0;

    constructor(buffer: ArrayBuffer) {
        this.view = new DataView(buffer);
        this.bytes = new Uint8Array(buffer);
    }

    get byteLength(): number {
        return this.view.byteLength;
    }

    u8(): number {
        const v = this.view.getUint8(this.off);
        this.off += 1;
        return v;
    }

    u16(): number {
        const v = this.view.getUint16(this.off, true);
        this.off += 2;
        return v;
    }

    u32(): number {
        const v = this.view.getUint32(this.off, true);
        this.off += 4;
        return v;
    }

    f32(): number {
        const v = this.view.getFloat32(this.off, true);
        this.off += 4;
        return v;
    }

    // DataView lacks a 53-bit-safe u64; ids stay < 2^53 in practice.
    u64(): number {
        const lo = this.view.getUint32(this.off, true);
        const hi = this.view.getUint32(this.off + 4, true);
        this.off += 8;
        return hi * 4294967296 + lo;
    }

    string(): string {
        const len = this.u16();
        let s = "";
        for (let i = 0; i < len; i++) {
            s += String.fromCharCode(this.bytes[this.off + i]);
        }
        this.off += len;
        return s;
    }

    // Returns a COPY of `len` bytes (safe to retain past the buffer's lifetime).
    take(len: number): Uint8Array {
        const out = this.bytes.slice(this.off, this.off + len);
        this.off += len;
        return out;
    }
}

// ---------------------------------------------------------------------------
// Encoder — mirrors the C++ (SceneProtocol.cpp) and Python (capture.py)
// CommandEncoders byte-for-byte. Use from any TypeScript/Node producer (mock
// server, USD/Omniverse bridge, tests). Little-endian throughout.
// ---------------------------------------------------------------------------

class ByteBuffer {
    private bytes: number[] = [];
    private readonly scratch = new DataView(new ArrayBuffer(8));

    u8(v: number): void {
        this.bytes.push(v & 0xff);
    }

    u16(v: number): void {
        this.scratch.setUint16(0, v, true);
        this.spill(2);
    }

    u32(v: number): void {
        this.scratch.setUint32(0, v, true);
        this.spill(4);
    }

    f32(v: number): void {
        this.scratch.setFloat32(0, v, true);
        this.spill(4);
    }

    // ids stay < 2^53 in practice; split into lo/hi 32-bit words.
    u64(v: number): void {
        const lo = v >>> 0;
        const hi = Math.floor(v / 4294967296);
        this.u32(lo);
        this.u32(hi);
    }

    raw(arr: Uint8Array): void {
        for (let i = 0; i < arr.length; i++) {
            this.bytes.push(arr[i]);
        }
    }

    private spill(n: number): void {
        for (let i = 0; i < n; i++) {
            this.bytes.push(this.scratch.getUint8(i));
        }
    }

    toUint8(): Uint8Array {
        return Uint8Array.from(this.bytes);
    }

    get length(): number {
        return this.bytes.length;
    }
}

export type Vec3 = readonly [number, number, number];
export type Quat = readonly [number, number, number, number]; // x, y, z, w

export class CommandWriter {
    private body = new ByteBuffer();
    private count = 0;

    private string(s: string): void {
        const enc = new TextEncoder().encode(s);
        const len = Math.min(enc.length, 0xffff);
        this.body.u16(len);
        this.body.raw(enc.subarray(0, len));
    }

    private transform(pos: Vec3, quat: Quat, scale: Vec3): void {
        this.body.f32(pos[0]); this.body.f32(pos[1]); this.body.f32(pos[2]);
        this.body.f32(quat[0]); this.body.f32(quat[1]); this.body.f32(quat[2]); this.body.f32(quat[3]);
        this.body.f32(scale[0]); this.body.f32(scale[1]); this.body.f32(scale[2]);
    }

    resetScene(): this {
        this.body.u16(CommandType.ResetScene);
        this.count++;
        return this;
    }

    setClearColor(r: number, g: number, b: number, a: number): this {
        this.body.u16(CommandType.SetClearColor);
        this.body.f32(r); this.body.f32(g); this.body.f32(b); this.body.f32(a);
        this.count++;
        return this;
    }

    upsertNode(id: number, parentId: number, kind: NodeKind, name: string,
               pos: Vec3, quat: Quat, scale: Vec3): this {
        this.body.u16(CommandType.UpsertNode);
        this.body.u64(id);
        this.body.u64(parentId);
        this.body.u16(kind);
        this.string(name);
        this.transform(pos, quat, scale);
        this.count++;
        return this;
    }

    removeNode(id: number): this {
        this.body.u16(CommandType.RemoveNode);
        this.body.u64(id);
        this.count++;
        return this;
    }

    setTransform(id: number, pos: Vec3, quat: Quat, scale: Vec3): this {
        this.body.u16(CommandType.SetTransform);
        this.body.u64(id);
        this.transform(pos, quat, scale);
        this.count++;
        return this;
    }

    upsertMeshGeometry(id: number, positions: ArrayLike<number>,
                       normals: ArrayLike<number> | null,
                       uvs: ArrayLike<number> | null,
                       indices: ArrayLike<number>): this {
        const vtx = Math.floor(positions.length / 3);
        this.body.u16(CommandType.UpsertMeshGeometry);
        this.body.u64(id);
        this.body.u32(vtx);
        this.body.u8(normals ? 1 : 0);
        this.body.u8(uvs ? 1 : 0);
        this.body.u32(indices.length);
        for (let i = 0; i < positions.length; i++) { this.body.f32(positions[i]); }
        if (normals) {
            for (let i = 0; i < normals.length; i++) { this.body.f32(normals[i]); }
        }
        if (uvs) {
            for (let i = 0; i < uvs.length; i++) { this.body.f32(uvs[i]); }
        }
        for (let i = 0; i < indices.length; i++) { this.body.u32(indices[i]); }
        this.count++;
        return this;
    }

    upsertMaterial(id: number, rgba: readonly [number, number, number, number],
                   metallic: number, roughness: number,
                   emissive: Vec3 = [0, 0, 0], emissiveStrength = 0): this {
        this.body.u16(CommandType.UpsertMaterial);
        this.body.u64(id);
        this.body.f32(rgba[0]); this.body.f32(rgba[1]); this.body.f32(rgba[2]); this.body.f32(rgba[3]);
        this.body.f32(metallic); this.body.f32(roughness);
        this.body.f32(emissive[0]); this.body.f32(emissive[1]); this.body.f32(emissive[2]);
        this.body.f32(emissiveStrength);
        this.count++;
        return this;
    }

    upsertMaterialTexture(id: number, channel: TextureChannel, bytes: Uint8Array | null): this {
        this.body.u16(CommandType.UpsertMaterialTexture);
        this.body.u64(id);
        this.body.u16(channel);
        this.body.u8(0); // encoding: EncodedImage
        const len = bytes ? bytes.length : 0;
        this.body.u32(len);
        if (bytes && len > 0) {
            this.body.raw(bytes);
        }
        this.count++;
        return this;
    }

    upsertLight(id: number, type: LightType, vec: Vec3, color: Vec3, intensity: number): this {
        this.body.u16(CommandType.UpsertLight);
        this.body.u64(id);
        this.body.u16(type);
        this.body.f32(vec[0]); this.body.f32(vec[1]); this.body.f32(vec[2]);
        this.body.f32(color[0]); this.body.f32(color[1]); this.body.f32(color[2]);
        this.body.f32(intensity);
        this.count++;
        return this;
    }

    setCameraArcRotate(alpha: number, beta: number, radius: number, target: Vec3): this {
        this.body.u16(CommandType.SetCamera);
        this.body.u8(CameraMode.ArcRotate);
        this.body.f32(alpha); this.body.f32(beta); this.body.f32(radius);
        this.body.f32(target[0]); this.body.f32(target[1]); this.body.f32(target[2]);
        this.count++;
        return this;
    }

    setCameraMatrices(view16: ArrayLike<number>, projection16: ArrayLike<number>): this {
        this.body.u16(CommandType.SetCamera);
        this.body.u8(CameraMode.Matrices);
        for (let i = 0; i < 16; i++) { this.body.f32(view16[i]); }
        for (let i = 0; i < 16; i++) { this.body.f32(projection16[i]); }
        this.count++;
        return this;
    }

    get empty(): boolean {
        return this.count === 0;
    }

    /** Assemble the header + body and reset the writer for reuse. */
    finish(): ArrayBuffer {
        const header = new ByteBuffer();
        header.u32(COMMAND_MAGIC);
        header.u16(COMMAND_VERSION);
        header.u16(this.count);
        const h = header.toUint8();
        const b = this.body.toUint8();
        const out = new Uint8Array(h.length + b.length);
        out.set(h, 0);
        out.set(b, h.length);
        this.body = new ByteBuffer();
        this.count = 0;
        return out.buffer;
    }
}

