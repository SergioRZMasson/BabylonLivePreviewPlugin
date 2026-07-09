"""Minimal glTF 2.0 writer for the USD bridge's bake-once flow.

Writes a self-contained ``.gltf`` (JSON with an embedded base64 buffer) from a
list of triangle meshes. Each glTF node's ``name`` is the mesh's stable path
(USD PrimPath), so a Babylon Live Sync client can resolve BindNodePath(id, path)
to the loaded node and then drive it with id-addressed deltas.

Geometry and node transforms are written in glTF space (Y-up right-handed, the
same as a Y-up USD stage); Babylon's glTF loader converts to its left-handed
space on load, and the bridge streams matching (un-converted) transform deltas,
so baked nodes and deltas stay in the same frame.
"""

import base64
import json
import struct

# glTF component types / targets.
_FLOAT = 5126
_UINT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963


def write_gltf(meshes, out_path):
    """meshes: list of dicts with keys
        name (str), positions (flat [x,y,z,...]), indices (flat ints),
        base_color (r,g,b,a), translation (x,y,z), rotation (x,y,z,w), scale (x,y,z).
    """
    buffer = bytearray()
    buffer_views = []
    accessors = []
    gltf_meshes = []
    gltf_materials = []
    gltf_nodes = []
    scene_nodes = []

    def add_view(data_bytes, target):
        # 4-byte align each view.
        while len(buffer) % 4 != 0:
            buffer.append(0)
        offset = len(buffer)
        buffer.extend(data_bytes)
        buffer_views.append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data_bytes),
            "target": target,
        })
        return len(buffer_views) - 1

    for m in meshes:
        positions = m["positions"]
        indices = m["indices"]
        vtx = len(positions) // 3

        pos_bytes = struct.pack("<%df" % len(positions), *positions)
        pos_view = add_view(pos_bytes, _ARRAY_BUFFER)
        xs = positions[0::3] or [0.0]
        ys = positions[1::3] or [0.0]
        zs = positions[2::3] or [0.0]
        accessors.append({
            "bufferView": pos_view, "componentType": _FLOAT, "count": vtx,
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        })
        pos_acc = len(accessors) - 1

        idx_bytes = struct.pack("<%dI" % len(indices), *indices)
        idx_view = add_view(idx_bytes, _ELEMENT_ARRAY_BUFFER)
        accessors.append({
            "bufferView": idx_view, "componentType": _UINT,
            "count": len(indices), "type": "SCALAR",
        })
        idx_acc = len(accessors) - 1

        gltf_materials.append({
            "pbrMetallicRoughness": {
                "baseColorFactor": list(m.get("base_color", (0.8, 0.8, 0.8, 1.0))),
                "metallicFactor": 0.0,
                "roughnessFactor": 0.6,
            },
            "doubleSided": True,
        })
        mat_idx = len(gltf_materials) - 1

        gltf_meshes.append({
            "primitives": [{
                "attributes": {"POSITION": pos_acc},
                "indices": idx_acc,
                "material": mat_idx,
            }],
        })
        mesh_idx = len(gltf_meshes) - 1

        gltf_nodes.append({
            "name": m["name"],
            "mesh": mesh_idx,
            "translation": list(m.get("translation", (0.0, 0.0, 0.0))),
            "rotation": list(m.get("rotation", (0.0, 0.0, 0.0, 1.0))),
            "scale": list(m.get("scale", (1.0, 1.0, 1.0))),
        })
        scene_nodes.append(len(gltf_nodes) - 1)

    b64 = base64.b64encode(bytes(buffer)).decode("ascii")
    gltf = {
        "asset": {"version": "2.0", "generator": "blp-usd-bridge"},
        "scene": 0,
        "scenes": [{"nodes": scene_nodes}],
        "nodes": gltf_nodes,
        "meshes": gltf_meshes,
        "materials": gltf_materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{
            "byteLength": len(buffer),
            "uri": "data:application/octet-stream;base64," + b64,
        }],
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(gltf, f)
    return out_path
