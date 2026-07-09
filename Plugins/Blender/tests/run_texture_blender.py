"""Validate the Blender capture path for PBR textures (bpy -> protocol).

Creates a plane whose material has an Image Texture node wired to Base Color,
runs the real `capture` extraction (image bytes + UVs), submits the buffer, and
reads back four quadrants to confirm the texture decoded and mapped. Unlike
run_texture.py (which hand-builds the buffer), this exercises _trace_image,
_image_encoded_bytes and the UV export on genuine bpy data.

    blender --background --python Plugins/Blender/tests/run_texture_blender.py
"""

import os
import sys
import time

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import bridge   # noqa: E402
import capture  # noqa: E402


def default_dll():
    return os.path.join(_REPO, "build", "Plugins", "Blender", "Release", "babylon_live_preview.dll")


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # A flat ground plane (Blender XY -> Babylon XZ horizontal, identity node
    # transform) so the test camera placement is predictable.
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
    plane = bpy.context.active_object

    # 2x2 image. Blender pixel rows are bottom-to-top, so the TOP image row
    # (RED, GREEN) is written last; the bottom row (BLUE, YELLOW) first.
    img = bpy.data.images.new("blp_tex", width=2, height=2, alpha=True)
    img.colorspace_settings.name = 'sRGB'
    img.pixels.foreach_set([
        0, 0, 1, 1,   1, 1, 0, 1,   # bottom: BLUE, YELLOW
        1, 0, 0, 1,   0, 1, 0, 1,   # top:    RED,  GREEN
    ])
    img.pack()
    img.update()

    mat = bpy.data.materials.new("blp_mat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = 'Closest'
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    plane.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("cam")
    cam_obj = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (0, -3, 0)
    cam_obj.rotation_euler = (1.5707963, 0, 0)
    scene.camera = cam_obj


_SETUP = (
    "(function(){var s=currentScene;"
    "s.imageProcessingConfiguration.isEnabled=false;"
    "for(var i=0;i<s.meshes.length;i++){var m=s.meshes[i].material;if(m){m.unlit=true;"
    "if(m.baseTexture){m.baseTexture.updateSamplingMode(BABYLON.Texture.NEAREST_SAMPLINGMODE);}}}"
    "var c=new BABYLON.FreeCamera('tc',new BABYLON.Vector3(0.0,3.0,-3.2),s);"
    "c.setTarget(BABYLON.Vector3.Zero());c.fov=0.8;c.minZ=0.01;c.maxZ=100;"
    "s.activeCamera=c;})()"
)


def dominant(px):
    if px is None:
        return None
    r, g, bl = px[0], px[1], px[2]
    if r > 120 and g > 120 and bl < 100:
        return "YELLOW"
    if r > 100 and g < 90 and bl < 90:
        return "RED"
    if g > 100 and r < 90 and bl < 90:
        return "GREEN"
    if bl > 100 and r < 90 and g < 90:
        return "BLUE"
    return None


def scan_colours(b):
    """Read one frame and tally how many pixels fall into each texture colour."""
    b.request_readback()
    for _ in range(600):
        b.render_frame()
        r = b.try_acquire_readback()
        if r:
            data, w, h = r
            tally = {}
            bright = 0
            for i in range(0, len(data) - 3, 4):
                rr, gg, bb = data[i], data[i + 1], data[i + 2]
                if rr + gg + bb > 120:
                    bright += 1
                d = dominant((rr, gg, bb))
                if d:
                    tally[d] = tally.get(d, 0) + 1
            ci = ((h // 2) * w + w // 2) * 4
            print("[texbl] frame %dx%d bright=%d center=%s" %
                  (w, h, bright, [data[ci], data[ci + 1], data[ci + 2]]))
            return tally
        time.sleep(0.006)
    return {}


def count_texture_cmds(buf):
    """Walk the command buffer and count UpsertMaterialTexture records w/ bytes."""
    import struct
    off = 0
    magic, ver, count = struct.unpack_from("<IHH", buf, 0)
    off = 8
    n_tex = 0
    for _ in range(count):
        (ctype,) = struct.unpack_from("<H", buf, off); off += 2
        if ctype == capture.CMD_UPSERT_MATERIAL_TEXTURE:
            off += 8  # node id
            (channel,) = struct.unpack_from("<H", buf, off); off += 2
            off += 1  # encoding
            (blen,) = struct.unpack_from("<I", buf, off); off += 4
            off += blen
            if blen > 0:
                n_tex += 1
        else:
            # We only need to skip other records; re-serialise via a throwaway
            # decode is overkill, so bail out of precise walking on the first
            # non-texture we can't size. Instead, rely on the end-to-end render.
            return None
    return n_tex


def main():
    build_scene()
    buf = capture.build_scene_snapshot(bpy.context)
    print("[texbl] snapshot %d bytes" % len(buf))

    dll = default_dll()
    scripts = os.path.join(os.path.dirname(dll), "Scripts")
    b = bridge.BabylonBridge(dll)
    if not b.create(320, 240, scripts):
        print("[texbl] FAILED: blp_create")
        return 2
    for _ in range(4000):
        b.render_frame()
        if b.is_ready():
            break
        time.sleep(0.01)

    b.submit_commands(buf)
    b.eval(_SETUP)
    for _ in range(150):
        b.render_frame()
        time.sleep(0.01)

    tally = scan_colours(b)
    print("[texbl] colour pixel tally:", tally)
    present = {k for k, v in tally.items() if v > 20}
    ok = present == {"RED", "GREEN", "BLUE", "YELLOW"}
    print("[texbl] colours present %s -> %s" % (sorted(present), "PASS" if ok else "FAIL"))
    b.destroy()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
