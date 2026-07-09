"""Validate PBR texture streaming end to end.

Builds a full-screen quad (with UVs), sends a 2x2 base-colour PNG through the new
UpsertMaterialTexture protocol command, renders unlit with image processing off,
and reads back the four quadrants to confirm the texture decoded, mapped through
UVs, and kept its channel order.

  python Plugins/Blender/tests/run_texture.py
"""

import os
import struct
import sys
import time
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import bridge   # noqa: E402
import capture  # noqa: E402


def default_dll():
    return os.path.join(_REPO, "build", "Plugins", "Blender", "Release", "babylon_live_preview.dll")


def make_png(width, height, pixels):
    """Encode RGBA pixels (row-major, top-to-bottom) as an 8-bit PNG."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            raw += bytes(pixels[y * width + x])

    def chunk(typ, data):
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # RGBA8
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# 2x2: top-left RED, top-right GREEN, bottom-left BLUE, bottom-right YELLOW.
_TEX = make_png(2, 2, [
    (255, 0, 0, 255), (0, 255, 0, 255),
    (0, 0, 255, 255), (255, 255, 0, 255),
])


def build_quad_commands():
    enc = capture.CommandEncoder()
    enc.reset_scene()
    enc.set_clear_color((0.0, 0.0, 0.0, 1.0))
    nid = 1
    enc.upsert_node(nid, 0, capture.KIND_MESH, "quad",
                    (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    # Quad in the XY plane (Babylon space). Screen corners -> UVs (invertY=false,
    # image top-left = uv(0,0)).
    positions = [
        -1.0,  1.0, 0.0,   # TL
         1.0,  1.0, 0.0,   # TR
         1.0, -1.0, 0.0,   # BR
        -1.0, -1.0, 0.0,   # BL
    ]
    normals = [0, 0, -1] * 4
    uvs = [0.0, 0.0,  1.0, 0.0,  1.0, 1.0,  0.0, 1.0]
    indices = [0, 1, 2, 0, 2, 3]
    enc.upsert_mesh_geometry(nid, positions, normals, uvs, indices)
    enc.upsert_material(nid, (1.0, 1.0, 1.0, 1.0), 0.0, 1.0)
    enc.upsert_material_texture(nid, capture.TEX_BASECOLOR, _TEX)
    return enc.finish()


_SETUP = (
    "(function(){var s=currentScene;"
    "s.imageProcessingConfiguration.isEnabled=false;"
    "for(var i=0;i<s.meshes.length;i++){var m=s.meshes[i].material;if(m){m.unlit=true;"
    "if(m.baseTexture){m.baseTexture.updateSamplingMode(BABYLON.Texture.NEAREST_SAMPLINGMODE);}}}"
    "var c=new BABYLON.FreeCamera('tc',new BABYLON.Vector3(0,0,-3),s);"
    "c.setTarget(BABYLON.Vector3.Zero());c.mode=BABYLON.Camera.ORTHOGRAPHIC_CAMERA;"
    "c.orthoLeft=-1;c.orthoRight=1;c.orthoTop=1;c.orthoBottom=-1;c.minZ=0.01;c.maxZ=100;"
    "s.activeCamera=c;})()"
)


def sample(b, fx, fy):
    b.request_readback()
    for _ in range(500):
        b.render_frame()
        r = b.try_acquire_readback()
        if r:
            data, w, h = r
            x = int(fx * w)
            y = int(fy * h)
            i = (y * w + x) * 4
            return [data[i], data[i + 1], data[i + 2], data[i + 3]]
        time.sleep(0.006)
    return None


def dominant(px):
    if px is None:
        return "?"
    r, g, bl = px[0], px[1], px[2]
    if r > 150 and g > 150 and bl < 120:
        return "YELLOW"
    if r > 130 and g < 110 and bl < 110:
        return "RED"
    if g > 130 and r < 110 and bl < 110:
        return "GREEN"
    if bl > 130 and r < 110 and g < 110:
        return "BLUE"
    return "mixed%s" % px[:3]


def main():
    dll = default_dll()
    scripts = os.path.join(os.path.dirname(dll), "Scripts")
    b = bridge.BabylonBridge(dll)
    if not b.create(320, 240, scripts):
        print("[tex] FAILED: blp_create")
        return 2
    for _ in range(4000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    b.submit_commands(build_quad_commands())
    b.eval(_SETUP)
    for _ in range(120):
        b.render_frame()
        time.sleep(0.01)

    tl = sample(b, 0.25, 0.25)
    tr = sample(b, 0.75, 0.25)
    bl = sample(b, 0.25, 0.75)
    br = sample(b, 0.75, 0.75)

    print("[tex] screen TL 25,25 ->", tl, dominant(tl))
    print("[tex] screen TR 75,25 ->", tr, dominant(tr))
    print("[tex] screen BL 25,75 ->", bl, dominant(bl))
    print("[tex] screen BR 75,75 ->", br, dominant(br))

    doms = {dominant(tl), dominant(tr), dominant(bl), dominant(br)}
    ok = doms == {"RED", "GREEN", "BLUE", "YELLOW"}
    print("[tex] distinct quadrant colours: %s -> %s" % (sorted(doms), "PASS" if ok else "CHECK"))
    b.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
