"""Validate multi-channel PBR texture extraction from Blender node graphs.

Exercises capture._trace_image for Base Color, Normal (through a Normal Map
node), combined Metallic-Roughness (same image feeding both sockets via a
Separate Color node), and Emission. Pure capture-side: asserts the right
channels are emitted, no DLL/render needed.

    blender --background --python Plugins/Blender/tests/run_texture_channels.py
"""

import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_ADDON = os.path.join(_REPO, "Plugins", "Blender", "addon", "babylon_live_preview")
sys.path.insert(0, _ADDON)

import capture  # noqa: E402


def _img(name):
    im = bpy.data.images.new(name, width=2, height=2, alpha=True)
    im.pixels.foreach_set([0.5] * 16)
    im.pack()
    return im


def build():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.active_object

    mat = bpy.data.materials.new("multi")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    base = nt.nodes.new("ShaderNodeTexImage"); base.image = _img("base")
    nt.links.new(base.outputs['Color'], bsdf.inputs['Base Color'])

    # Normal via a Normal Map node.
    nrm_img = nt.nodes.new("ShaderNodeTexImage"); nrm_img.image = _img("nrm")
    nrm_img.image.colorspace_settings.name = 'Non-Color'
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nrm_img.outputs['Color'], nmap.inputs['Color'])
    nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])

    # Combined metallic-roughness: one image -> Separate Color -> both sockets.
    orm = nt.nodes.new("ShaderNodeTexImage"); orm.image = _img("orm")
    orm.image.colorspace_settings.name = 'Non-Color'
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(orm.outputs['Color'], sep.inputs['Color'])
    nt.links.new(sep.outputs['Green'], bsdf.inputs['Roughness'])
    nt.links.new(sep.outputs['Blue'], bsdf.inputs['Metallic'])

    # Emission colour texture + strength so it actually emits.
    em = nt.nodes.new("ShaderNodeTexImage"); em.image = _img("emis")
    em_socket = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
    nt.links.new(em.outputs['Color'], em_socket)
    strength = bsdf.inputs.get('Emission Strength')
    if strength is not None:
        strength.default_value = 1.0

    plane.data.materials.append(mat)
    return plane


def main():
    plane = build()
    scalars, imgs, sig = capture._capture_material(plane)
    found = {k: (v.name if v else None) for k, v in imgs.items()}
    print("[texch] traced images:", found)

    enc = capture.CommandEncoder()
    active = capture._emit_material(enc, 1, scalars, imgs)
    print("[texch] emitted channels:", sorted(active))
    print("[texch] emissive scalars:", scalars[3], "strength", scalars[4])

    expected = {capture.TEX_BASECOLOR, capture.TEX_NORMAL,
                capture.TEX_METALROUGH, capture.TEX_EMISSIVE}
    ok = active == expected and len(enc.finish()) > 0
    print("[texch] channels %s == expected %s -> %s" %
          (sorted(active), sorted(expected), "PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
