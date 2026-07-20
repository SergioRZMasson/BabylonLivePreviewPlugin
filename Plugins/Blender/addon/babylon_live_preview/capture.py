"""Scene capture: translate the Blender scene graph into BabylonLivePreview
protocol command buffers.

Mirrors the C++/JS protocol (Shared/include/BabylonLivePreview/SceneProtocol.h
and Shared/Scripts/live_preview.js). Requires bpy/mathutils only inside the
methods that touch scene data, so the CommandEncoder stays importable (and
unit-testable) outside Blender.

M4: `SceneSync` keeps per-object state and, on each `sync(context)`, emits only
what changed (transform / geometry / material / add / remove). Geometry is sent
in LOCAL (object) space with a Babylon node transform, so moving an object costs
a tiny `set_transform` instead of re-uploading geometry.

Coordinate systems: Blender is Z-up right-handed; Babylon is Y-up left-handed.
Positions map (x, y, z) -> (x, z, -y); a full transform M maps to C @ M @ C^-1
where C is that basis change; triangle winding is reversed once on the geometry.
"""

import struct

_MAGIC = 0x43504C42  # 'BLPC'
_VERSION = 2

# Command type ids (must match SceneProtocol.h / live_preview.js)
CMD_UPSERT_NODE = 1
CMD_REMOVE_NODE = 2
CMD_SET_TRANSFORM = 3
CMD_UPSERT_MESH_GEOMETRY = 4
CMD_UPSERT_MATERIAL = 5
CMD_UPSERT_LIGHT = 6
CMD_SET_CAMERA = 7
CMD_UPSERT_MATERIAL_TEXTURE = 8
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

# PBR texture channels (must match SceneProtocol.h / live_preview.js).
TEX_BASECOLOR = 0        # sRGB — albedo
TEX_METALROUGH = 1       # linear — glTF layout (G=roughness, B=metallic)
TEX_NORMAL = 2           # linear — tangent-space normal map
TEX_EMISSIVE = 3         # sRGB
TEX_OCCLUSION = 4        # linear — ambient occlusion (R)

# Texture payload encodings.
TEXENC_IMAGE = 0         # PNG/JPG/etc. file bytes, decoded natively via bimg

# Fixed ids for synthetic nodes.
_FILL_LIGHT_ID = 1000000


class CommandEncoder:
    """Builds a little-endian command buffer decoded by live_preview.js."""

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
        """Send encoded image bytes for one PBR channel. data None/empty clears it."""
        payload = data or b""
        self._u16(CMD_UPSERT_MATERIAL_TEXTURE)
        self._body += struct.pack("<Q", int(node_id))
        self._body += struct.pack("<H", int(channel))
        self._body += struct.pack("<B", int(encoding))
        self._body += struct.pack("<I", len(payload))
        self._body += payload
        self._count += 1

    def upsert_light(self, node_id, light_type, direction, color, intensity):
        self._u16(CMD_UPSERT_LIGHT)
        self._body += struct.pack("<QH", int(node_id), int(light_type))
        self._body += struct.pack("<3f", *direction)
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
        header = struct.pack("<IHH", _MAGIC, _VERSION, self._count)
        return bytes(header + bytes(self._body))


# ---------------------------------------------------------------------------
# Coordinate / transform helpers (lazy bpy/mathutils imports)
# ---------------------------------------------------------------------------

def _to_babylon(x, y, z):
    return (x, z, -y)


def matrix_to_columns(matrix):
    """Flatten a Blender mathutils.Matrix (row-major 4x4) to column-major 16."""
    return [matrix[r][c] for c in range(4) for r in range(4)]


_BASIS = None
_BASIS_INV = None


def _basis():
    global _BASIS, _BASIS_INV
    if _BASIS is None:
        from mathutils import Matrix
        # Columns chosen so C @ v == (v.x, v.z, -v.y).
        _BASIS = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
        _BASIS_INV = _BASIS.inverted()
    return _BASIS, _BASIS_INV


def _node_trs(obj):
    """Convert an object's world matrix to a Babylon (pos, quat_xyzw, scale)."""
    C, Cinv = _basis()
    m = C @ obj.matrix_world @ Cinv
    loc, quat, scale = m.decompose()
    return ((loc.x, loc.y, loc.z),
            (quat.x, quat.y, quat.z, quat.w),
            (scale.x, scale.y, scale.z))


# The classic Babylon.js default clear color (a dark purple-blue). Used as the
# viewport background so the scene clearly reads as a Babylon render rather than
# mirroring Blender's world color.
BABYLON_CLEAR_COLOR = (0.2, 0.2, 0.3, 1.0)


def _emit_geometry(enc, obj, node_id, depsgraph):
    """Send LOCAL (object-space) geometry with real per-loop normals and UVs.

    Per-loop vertices preserve Blender's smooth/flat/custom split normals and the
    active UV layer. Both positions and normals are mapped into Babylon space;
    winding is reversed once to compensate for the coordinate-system handedness
    difference. UVs are emitted with V flipped (Blender's bottom-left origin vs
    Babylon's top-left) so textures map the right way up.
    """
    eval_obj = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
    mesh = eval_obj.to_mesh()
    try:
        mesh.calc_loop_triangles()

        # Per-loop normals (Blender 4.1+ exposes mesh.corner_normals). Fall back
        # to vertex normals if unavailable.
        corner_normals = None
        try:
            corner_normals = mesh.corner_normals  # sequence indexed by loop index
        except Exception:
            corner_normals = None

        # Active UV layer (per-loop). None when the mesh is unwrapped-less.
        uv_data = None
        try:
            uv_layer = mesh.uv_layers.active
            if uv_layer is not None:
                uv_data = uv_layer.data
        except Exception:
            uv_data = None

        positions, normals, uvs, indices = [], [], [], []
        for tri in mesh.loop_triangles:
            for vidx, lidx in zip(tri.vertices, tri.loops):
                co = mesh.vertices[vidx].co  # object space
                p = _to_babylon(co.x, co.y, co.z)
                if corner_normals is not None:
                    nv = corner_normals[lidx].vector
                else:
                    nv = mesh.vertices[vidx].normal
                n = _to_babylon(nv.x, nv.y, nv.z)
                indices.append(len(positions) // 3)
                positions += [p[0], p[1], p[2]]
                normals += [n[0], n[1], n[2]]
                if uv_data is not None:
                    uv = uv_data[lidx].uv
                    uvs += [uv[0], 1.0 - uv[1]]

        # Reverse winding once to compensate for the basis-change handedness.
        for t in range(0, len(indices) - 2, 3):
            indices[t + 1], indices[t + 2] = indices[t + 2], indices[t + 1]

        enc.upsert_mesh_geometry(node_id, positions, normals,
                                 uvs if uv_data is not None else None, indices)
    finally:
        eval_obj.to_mesh_clear()


_TEX_CHANNELS = (TEX_BASECOLOR, TEX_METALROUGH, TEX_NORMAL, TEX_EMISSIVE, TEX_OCCLUSION)

# Raster formats bimg can decode directly (read original file bytes as-is).
_RASTER_EXTS = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.dds', '.ktx', '.hdr')


def _find_principled(mat):
    if mat is None or not getattr(mat, "use_nodes", False) or mat.node_tree is None:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def _trace_image(socket, depth=0):
    """Follow a node socket's links back to the source Image Texture datablock."""
    if socket is None or not getattr(socket, "is_linked", False) or depth > 6:
        return None
    node = socket.links[0].from_node
    if node.type == 'TEX_IMAGE':
        return node.image
    # Passthrough / helper nodes (Normal Map, Separate Color, Mix, ...): follow
    # the most likely colour-carrying input first, then any linked input.
    for name in ('Color', 'Image', 'Vector', 'Fac'):
        inp = node.inputs.get(name) if hasattr(node.inputs, "get") else None
        if inp is not None and inp.is_linked:
            img = _trace_image(inp, depth + 1)
            if img is not None:
                return img
    for inp in node.inputs:
        if inp.is_linked:
            img = _trace_image(inp, depth + 1)
            if img is not None:
                return img
    return None


def _material_images(bsdf):
    """Map each PBR texture channel to a Blender Image datablock (or None)."""
    imgs = {ch: None for ch in _TEX_CHANNELS}
    if bsdf is None:
        return imgs
    inputs = bsdf.inputs
    imgs[TEX_BASECOLOR] = _trace_image(inputs.get('Base Color'))
    imgs[TEX_NORMAL] = _trace_image(inputs.get('Normal'))
    emission = inputs.get('Emission Color') or inputs.get('Emission')
    imgs[TEX_EMISSIVE] = _trace_image(emission)
    # Combined metallic-roughness: only when the SAME image feeds both sockets
    # (the glTF ORM / Separate-Color convention). Separate/scalar inputs fall
    # back to the scalar metallic/roughness values.
    mimg = _trace_image(inputs.get('Metallic'))
    rimg = _trace_image(inputs.get('Roughness'))
    if mimg is not None and mimg == rimg:
        imgs[TEX_METALROUGH] = mimg
    return imgs


def _material_scalars(obj, imgs):
    rgba = (0.8, 0.8, 0.8, 1.0)
    metallic, roughness = 0.0, 0.6
    emissive = (0.0, 0.0, 0.0)
    emissive_strength = 0.0
    mat = obj.active_material
    bsdf = _find_principled(mat)
    if bsdf is not None:
        try:
            bc = bsdf.inputs['Base Color'].default_value
            rgba = (bc[0], bc[1], bc[2], bc[3])
        except Exception:
            pass
        try:
            metallic = float(bsdf.inputs['Metallic'].default_value)
            roughness = float(bsdf.inputs['Roughness'].default_value)
        except Exception:
            pass
        try:
            em = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
            if em is not None:
                ec = em.default_value
                emissive = (ec[0], ec[1], ec[2])
            es = bsdf.inputs.get('Emission Strength')
            emissive_strength = float(es.default_value) if es is not None else 1.0
        except Exception:
            pass
    elif mat is not None:
        c = mat.diffuse_color
        rgba = (c[0], c[1], c[2], c[3])
    # A base-colour texture multiplies baseColor; use white so the (often black)
    # socket default doesn't tint it out.
    if imgs.get(TEX_BASECOLOR) is not None:
        rgba = (1.0, 1.0, 1.0, rgba[3])
    return rgba, metallic, roughness, emissive, emissive_strength


def _image_key(img):
    """Cheap identity used for change detection (no pixel data)."""
    if img is None:
        return None
    try:
        return (img.name, tuple(img.size), img.filepath, bool(getattr(img, 'is_dirty', False)))
    except Exception:
        return (getattr(img, 'name', '?'),)


def _save_temp_png(img):
    """Re-encode any image to PNG via a temporary, non-mutating copy."""
    import bpy
    import tempfile
    copy = None
    path = None
    try:
        copy = img.copy()
        copy.file_format = 'PNG'
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        copy.filepath_raw = path
        copy.save()
        with open(path, 'rb') as f:
            return f.read()
    except Exception as exc:
        print('[BLP] temp PNG encode failed for %s: %s' % (getattr(img, 'name', '?'), exc))
        return None
    finally:
        if copy is not None:
            try:
                bpy.data.images.remove(copy)
            except Exception:
                pass
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass


def _image_encoded_bytes(img):
    """Return decodable encoded-image bytes for a Blender image, or None."""
    if img is None:
        return None
    # 1. Packed image: packed_file.data holds the original file bytes.
    try:
        if img.packed_file is not None and img.packed_file.data:
            return bytes(img.packed_file.data)
    except Exception:
        pass
    # 2. File on disk in a bimg-decodable raster format: read as-is.
    try:
        import bpy
        raw = img.filepath_from_user() or img.filepath
        path = bpy.path.abspath(raw) if raw else None
        if path and os.path.isfile(path):
            if os.path.splitext(path)[1].lower() in _RASTER_EXTS:
                with open(path, 'rb') as f:
                    return f.read()
    except Exception:
        pass
    # 3. Fallback: re-encode to PNG (generated images, exotic formats).
    return _save_temp_png(img)


def _capture_material(obj):
    """Return (scalars, imgs, signature). Signature is cheap/hashable and used
    for incremental change detection; imgs are datablocks (bytes extracted only
    when actually emitting)."""
    bsdf = _find_principled(obj.active_material)
    imgs = _material_images(bsdf)
    scalars = _material_scalars(obj, imgs)
    sig = (scalars, tuple((ch, _image_key(imgs.get(ch))) for ch in _TEX_CHANNELS))
    return scalars, imgs, sig


def _emit_material(enc, node_id, scalars, imgs, prev_channels=None):
    """Emit scalars + per-channel textures. Returns the set of channels that now
    carry a texture, so callers can clear channels that disappeared."""
    rgba, metallic, roughness, emissive, emissive_strength = scalars
    enc.upsert_material(node_id, rgba, metallic, roughness, emissive, emissive_strength)
    active = set()
    for ch in _TEX_CHANNELS:
        img = imgs.get(ch)
        if img is None:
            continue
        data = _image_encoded_bytes(img)
        if data:
            enc.upsert_material_texture(node_id, ch, data)
            active.add(ch)
    if prev_channels:
        for ch in prev_channels:
            if ch not in active:
                enc.upsert_material_texture(node_id, ch, None)  # clear
    return active


def _light_tuple(obj):
    from mathutils import Vector
    light = obj.data
    color = (light.color[0], light.color[1], light.color[2])
    if light.type == 'SUN':
        d = (obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        vec = _to_babylon(d.x, d.y, d.z)
        return LIGHT_DIRECTIONAL, vec, color, max(0.05, float(light.energy))
    # Point (and spot/area approximated as point): send the world position.
    loc = obj.matrix_world.translation
    vec = _to_babylon(loc.x, loc.y, loc.z)
    return LIGHT_POINT, vec, color, max(0.05, float(light.energy) / 10.0)


def _emit_light(enc, obj, node_id):
    lt, d, color, intensity = _light_tuple(obj)
    enc.upsert_light(node_id, lt, d, color, intensity)


def _camera_arc(cam):
    import math
    loc = _to_babylon(cam.matrix_world.translation.x,
                      cam.matrix_world.translation.y,
                      cam.matrix_world.translation.z)
    target = (0.0, 0.0, 0.0)
    dx, dy, dz = loc[0] - target[0], loc[1] - target[1], loc[2] - target[2]
    radius = max(0.1, math.sqrt(dx * dx + dy * dy + dz * dz))
    beta = math.acos(max(-1.0, min(1.0, dy / radius)))
    alpha = math.atan2(dz, dx)
    return alpha, beta, radius, target


def _emit_camera(enc, cam):
    alpha, beta, radius, target = _camera_arc(cam)
    enc.set_camera_arcrotate(alpha, beta, radius, target)


def _matrix_key(m):
    return tuple(round(m[r][c], 5) for r in range(4) for c in range(4))


def _geo_key(obj):
    """Cheap key that changes when the base mesh's vertices/topology change."""
    me = obj.data
    n = len(me.vertices)
    coords = [0.0] * (n * 3)
    if n:
        me.vertices.foreach_get("co", coords)
    return (n, len(me.polygons), hash(tuple(round(v, 5) for v in coords)))


# ---------------------------------------------------------------------------
# SceneSync — stateful incremental capture
# ---------------------------------------------------------------------------

class SceneSync:
    def __init__(self):
        self._ids = {}
        self._counter = 1
        self._state = {}  # name -> {'m','geo','matsig','texch','kind'}

    def _id(self, name):
        if name not in self._ids:
            self._ids[name] = self._counter
            self._counter += 1
        return self._ids[name]

    def initial_snapshot(self, context):
        """Full reset + push of the whole scene. Resets internal state."""
        depsgraph = context.evaluated_depsgraph_get()
        self._ids = {}
        self._counter = 1
        self._state = {}

        enc = CommandEncoder()
        enc.reset_scene()
        enc.set_clear_color(BABYLON_CLEAR_COLOR)
        # Add a dim hemispheric fill ONLY when the scene has no lights, so the
        # actual scene lights drive the look (and light edits are visible).
        if not any(o.type == 'LIGHT' for o in context.scene.objects):
            enc.upsert_light(_FILL_LIGHT_ID, LIGHT_HEMISPHERIC, (0.2, 1.0, 0.3), (1.0, 1.0, 1.0), 0.7)

        for obj in context.scene.objects:
            try:
                self._add_object(enc, obj, depsgraph)
            except Exception as exc:
                print("[BLP] snapshot skipped %s: %s" % (obj.name, exc))

        if context.scene.camera is not None:
            _emit_camera(enc, context.scene.camera)

        return enc.finish()

    def sync(self, context):
        """Diff the scene against last state; emit only changes. None if nothing changed."""
        depsgraph = context.evaluated_depsgraph_get()
        enc = CommandEncoder()
        touched = False
        seen = set()

        for obj in context.scene.objects:
            seen.add(obj.name)
            try:
                if obj.type == 'MESH':
                    touched |= self._sync_mesh(enc, obj, depsgraph)
                elif obj.type == 'LIGHT':
                    touched |= self._sync_light(enc, obj)
            except Exception as exc:
                print("[BLP] sync skipped %s: %s" % (obj.name, exc))

        cam = context.scene.camera
        if cam is not None:
            touched |= self._sync_camera(enc, cam)

        for name in list(self._state.keys()):
            if name not in seen and name != "__camera__":
                enc.remove_node(self._id(name))
                del self._state[name]
                touched = True

        return enc.finish() if touched else None

    # --- internal emit + diff helpers ---

    def _add_object(self, enc, obj, depsgraph):
        if obj.type == 'MESH':
            node_id = self._id(obj.name)
            pos, quat, scale = _node_trs(obj)
            enc.upsert_node(node_id, 0, KIND_MESH, obj.name, pos, quat, scale)
            _emit_geometry(enc, obj, node_id, depsgraph)
            scalars, imgs, matsig = _capture_material(obj)
            texch = _emit_material(enc, node_id, scalars, imgs)
            self._state[obj.name] = {
                'm': _matrix_key(obj.matrix_world),
                'geo': _geo_key(obj),
                'matsig': matsig,
                'texch': texch,
                'kind': 'MESH',
            }
        elif obj.type == 'LIGHT':
            node_id = self._id(obj.name)
            _emit_light(enc, obj, node_id)
            self._state[obj.name] = {
                'm': _matrix_key(obj.matrix_world),
                'light': _light_tuple(obj),
                'kind': 'LIGHT',
            }

    def _sync_mesh(self, enc, obj, depsgraph):
        st = self._state.get(obj.name)
        if st is None:
            self._add_object(enc, obj, depsgraph)
            return True

        node_id = self._id(obj.name)
        changed = False

        geo = _geo_key(obj)
        if geo != st['geo']:
            _emit_geometry(enc, obj, node_id, depsgraph)
            st['geo'] = geo
            changed = True

        mkey = _matrix_key(obj.matrix_world)
        if mkey != st['m']:
            pos, quat, scale = _node_trs(obj)
            enc.set_transform(node_id, pos, quat, scale)
            st['m'] = mkey
            changed = True

        scalars, imgs, matsig = _capture_material(obj)
        if matsig != st.get('matsig'):
            st['texch'] = _emit_material(enc, node_id, scalars, imgs, st.get('texch'))
            st['matsig'] = matsig
            changed = True

        return changed

    def _sync_light(self, enc, obj):
        st = self._state.get(obj.name)
        if st is None:
            self._add_object(enc, obj, None)
            return True
        node_id = self._id(obj.name)
        changed = False
        lt = _light_tuple(obj)
        mkey = _matrix_key(obj.matrix_world)
        if lt != st.get('light') or mkey != st['m']:
            _emit_light(enc, obj, node_id)
            st['light'] = lt
            st['m'] = mkey
            changed = True
        return changed

    def _sync_camera(self, enc, cam):
        st = self._state.get("__camera__")
        arc = _camera_arc(cam)
        key = tuple(round(v, 5) for v in (arc[0], arc[1], arc[2]) + arc[3])
        if st is None or st.get('key') != key:
            _emit_camera(enc, cam)
            self._state["__camera__"] = {'key': key, 'kind': 'CAMERA'}
            return True
        return False


def build_scene_snapshot(context):
    """Convenience: a one-shot full snapshot (used by the add-on on start)."""
    return SceneSync().initial_snapshot(context)
