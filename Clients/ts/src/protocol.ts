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
