"""Babylon Live Sync — scene-delta protocol encoder (Python).

Standalone mirror of the C++ (Shared/src/SceneProtocol.cpp), TypeScript
(Clients/ts/src/protocol.ts) and Blender add-on (capture.py) encoders. Use from
any Python producer — the USD/Omniverse bridge, tests, tooling — so they all
speak the exact same wire format.

Buffer layout (little-endian):
  [u32 magic 'BLPC'][u16 version][u16 count] then `count` records:
  [u16 type][payload...]. Strings: [u16 byteLength][utf8].
"""

import struct

MAGIC = 0x43504C42  # 'BLPC'
VERSION = 2

# Command type ids (must match SceneProtocol.h).
CMD_UPSERT_NODE = 1
CMD_REMOVE_NODE = 2
CMD_SET_TRANSFORM = 3
CMD_UPSERT_MESH_GEOMETRY = 4
CMD_UPSERT_MATERIAL = 5
CMD_UPSERT_LIGHT = 6
CMD_SET_CAMERA = 7
CMD_UPSERT_MATERIAL_TEXTURE = 8
CMD_BIND_NODE_PATH = 9
CMD_RESET_SCENE = 10
CMD_SET_CLEAR_COLOR = 11

# NodeKind
KIND_TRANSFORM = 0
KIND_MESH = 1

# LightType
LIGHT_HEMISPHERIC = 0
LIGHT_DIRECTIONAL = 1
LIGHT_POINT = 2

# CameraMode
CAM_ARCROTATE = 0
CAM_MATRICES = 1

# PBR texture channels
TEX_BASECOLOR = 0
TEX_METALROUGH = 1
TEX_NORMAL = 2
TEX_EMISSIVE = 3
TEX_OCCLUSION = 4

# Texture payload encodings
TEXENC_IMAGE = 0


class CommandEncoder:
    """Builds a little-endian command buffer decoded by the SceneApplier."""

    def __init__(self):
        self._body = bytearray()
        self._count = 0

    def _u16(self, v):
        self._body += struct.pack("<H", v)

    def _string(self, s):
        data = s.encode("utf-8")[:0xFFFF]
        self._body += struct.pack("<H", len(data))
        self._body += data

    def _transform(self, pos, quat, scale):
        self._body += struct.pack("<3f", *pos)
        self._body += struct.pack("<4f", *quat)  # x, y, z, w
        self._body += struct.pack("<3f", *scale)

    def reset_scene(self):
        self._u16(CMD_RESET_SCENE)
        self._count += 1

    def set_clear_color(self, rgba):
        self._u16(CMD_SET_CLEAR_COLOR)
        self._body += struct.pack("<4f", *rgba)
        self._count += 1

    def upsert_node(self, node_id, parent_id, kind, name, pos, quat, scale):
        self._u16(CMD_UPSERT_NODE)
        self._body += struct.pack("<QQH", int(node_id), int(parent_id), int(kind))
        self._string(name)
        self._transform(pos, quat, scale)
        self._count += 1

    def remove_node(self, node_id):
        self._u16(CMD_REMOVE_NODE)
        self._body += struct.pack("<Q", int(node_id))
        self._count += 1

    def bind_node_path(self, node_id, path):
        """Bind a pre-loaded node (e.g. from a baked glTF) to `node_id` by its
        stable `path` (glTF node name / USD PrimPath)."""
        self._u16(CMD_BIND_NODE_PATH)
        self._body += struct.pack("<Q", int(node_id))
        self._string(path)
        self._count += 1

    def set_transform(self, node_id, pos, quat, scale):
        self._u16(CMD_SET_TRANSFORM)
        self._body += struct.pack("<Q", int(node_id))
        self._transform(pos, quat, scale)
        self._count += 1

    def upsert_mesh_geometry(self, node_id, positions, normals, uvs, indices):
        vtx = len(positions) // 3
        self._u16(CMD_UPSERT_MESH_GEOMETRY)
        self._body += struct.pack("<Q", int(node_id))
        self._body += struct.pack("<I", vtx)
        self._body += struct.pack("<BB", 1 if normals else 0, 1 if uvs else 0)
        self._body += struct.pack("<I", len(indices))
        self._body += struct.pack("<%df" % len(positions), *positions)
        if normals:
            self._body += struct.pack("<%df" % len(normals), *normals)
        if uvs:
            self._body += struct.pack("<%df" % len(uvs), *uvs)
        self._body += struct.pack("<%dI" % len(indices), *indices)
        self._count += 1

    def upsert_material(self, node_id, rgba, metallic, roughness,
                        emissive=(0.0, 0.0, 0.0), emissive_strength=0.0):
        self._u16(CMD_UPSERT_MATERIAL)
        self._body += struct.pack("<Q", int(node_id))
        self._body += struct.pack("<4f", *rgba)
        self._body += struct.pack("<2f", float(metallic), float(roughness))
        self._body += struct.pack("<3f", *emissive)
        self._body += struct.pack("<f", float(emissive_strength))
        self._count += 1

    def upsert_material_texture(self, node_id, channel, data, encoding=TEXENC_IMAGE):
        payload = data or b""
        self._u16(CMD_UPSERT_MATERIAL_TEXTURE)
        self._body += struct.pack("<Q", int(node_id))
        self._body += struct.pack("<H", int(channel))
        self._body += struct.pack("<B", int(encoding))
        self._body += struct.pack("<I", len(payload))
        self._body += payload
        self._count += 1

    def upsert_light(self, node_id, light_type, vec, color, intensity):
        self._u16(CMD_UPSERT_LIGHT)
        self._body += struct.pack("<QH", int(node_id), int(light_type))
        self._body += struct.pack("<3f", *vec)
        self._body += struct.pack("<3f", *color)
        self._body += struct.pack("<f", float(intensity))
        self._count += 1

    def set_camera_arcrotate(self, alpha, beta, radius, target):
        self._u16(CMD_SET_CAMERA)
        self._body += struct.pack("<B", CAM_ARCROTATE)
        self._body += struct.pack("<3f", alpha, beta, radius)
        self._body += struct.pack("<3f", *target)
        self._count += 1

    def set_camera_matrices(self, view16, projection16):
        self._u16(CMD_SET_CAMERA)
        self._body += struct.pack("<B", CAM_MATRICES)
        self._body += struct.pack("<16f", *view16)
        self._body += struct.pack("<16f", *projection16)
        self._count += 1

    def empty(self):
        return self._count == 0

    def finish(self):
        header = struct.pack("<IHH", MAGIC, VERSION, self._count)
        out = bytes(header + bytes(self._body))
        self._body = bytearray()
        self._count = 0
        return out
