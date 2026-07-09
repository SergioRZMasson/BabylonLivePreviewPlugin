"""Validate incremental texture change detection in SceneSync.

Ensures that adding, swapping, and removing a base-colour texture each produce a
sync delta containing the right UpsertMaterialTexture record (bytes present for
add/swap, byteLength 0 for clear).

    blender --background --python Plugins/Blender/tests/run_texture_incremental.py
"""

import os
import struct
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import capture  # noqa: E402


def find_tex_cmds(buf):
    """Return list of (channel, byteLength) for every UpsertMaterialTexture."""
    if buf is None:
        return []
    magic, ver, count = struct.unpack_from("<IHH", buf, 0)
    off = 8
    out = []
    for _ in range(count):
        (ctype,) = struct.unpack_from("<H", buf, off); off += 2
        if ctype == capture.CMD_UPSERT_NODE:
            off += 18
            (nl,) = struct.unpack_from("<H", buf, off); off += 2 + nl
            off += 40
        elif ctype == capture.CMD_REMOVE_NODE:
            off += 8
        elif ctype == capture.CMD_SET_TRANSFORM:
            off += 8 + 40
        elif ctype == capture.CMD_UPSERT_MESH_GEOMETRY:
            off += 8
            (vtx,) = struct.unpack_from("<I", buf, off); off += 4
            hn, hu = struct.unpack_from("<BB", buf, off); off += 2
            (idx,) = struct.unpack_from("<I", buf, off); off += 4
            off += vtx * 3 * 4
            if hn:
                off += vtx * 3 * 4
            if hu:
                off += vtx * 2 * 4
            off += idx * 4
        elif ctype == capture.CMD_UPSERT_MATERIAL:
            off += 8 + 4 * 4 + 2 * 4 + 3 * 4 + 4
        elif ctype == capture.CMD_UPSERT_MATERIAL_TEXTURE:
            off += 8
            (channel,) = struct.unpack_from("<H", buf, off); off += 2
            off += 1
            (blen,) = struct.unpack_from("<I", buf, off); off += 4
            off += blen
            out.append((channel, blen))
        elif ctype == capture.CMD_UPSERT_LIGHT:
            off += 8 + 2 + 3 * 4 + 3 * 4 + 4
        elif ctype == capture.CMD_SET_CAMERA:
            (mode,) = struct.unpack_from("<B", buf, off); off += 1
            off += (6 * 4) if mode == 0 else (32 * 4)
        elif ctype in (capture.CMD_RESET_SCENE,):
            pass
        elif ctype == capture.CMD_SET_CLEAR_COLOR:
            off += 4 * 4
        else:
            raise RuntimeError("unknown cmd %d" % ctype)
    return out


def make_image(name, packed=True):
    im = bpy.data.images.new(name, width=2, height=2, alpha=True)
    im.pixels.foreach_set([0.6] * 16)
    if packed:
        im.pack()
    return im


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.active_object
    mat = bpy.data.materials.new("m")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    plane.data.materials.append(mat)

    sync = capture.SceneSync()

    class Ctx:
        scene = bpy.context.scene
        def evaluated_depsgraph_get(self):
            return bpy.context.evaluated_depsgraph_get()
    ctx = Ctx()

    sync.initial_snapshot(ctx)  # no texture yet

    # 1. Add a base-colour texture.
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = make_image("t1")
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    plane.data.update_tag()
    d1 = sync.sync(ctx)
    cmds1 = find_tex_cmds(d1)
    print("[texinc] add ->", cmds1)
    add_ok = any(ch == capture.TEX_BASECOLOR and bl > 0 for ch, bl in cmds1)

    # 2. Swap the image datablock.
    tex.image = make_image("t2")
    plane.data.update_tag()
    d2 = sync.sync(ctx)
    cmds2 = find_tex_cmds(d2)
    print("[texinc] swap ->", cmds2)
    swap_ok = any(ch == capture.TEX_BASECOLOR and bl > 0 for ch, bl in cmds2)

    # 3. Remove the texture link -> expect a clear (byteLength 0).
    for link in list(bsdf.inputs['Base Color'].links):
        mat.node_tree.links.remove(link)
    plane.data.update_tag()
    d3 = sync.sync(ctx)
    cmds3 = find_tex_cmds(d3)
    print("[texinc] remove ->", cmds3)
    clear_ok = any(ch == capture.TEX_BASECOLOR and bl == 0 for ch, bl in cmds3)

    ok = add_ok and swap_ok and clear_ok
    print("[texinc] add=%s swap=%s clear=%s -> %s" %
          (add_ok, swap_ok, clear_ok, "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
