"""Babylon Live Sync — USD/Omniverse -> WebSocket bridge.

Opens a USD stage (local .usd/.usda/.usdc, or an ``omniverse://`` URL when the
Omniverse USD resolver is installed), translates it into Babylon Live Sync
scene-delta buffers, and broadcasts them to connected web clients over
WebSocket. Stage edits (via ``Usd.Notice.ObjectsChanged``) become incremental
transform/material deltas.

Coordinate systems: USD is right-handed (default Y-up); Babylon is left-handed
Y-up. For a Y-up stage, points map (x, y, z) -> (x, y, -z), and a decomposed
world transform maps translation (tx, ty, -tz), quaternion
(qx, qy, qz, qw) -> (-qx, -qy, qz, qw) (conjugation by diag(1,1,-1), which is a
proper rotation), scale unchanged. Materials are double-sided, so face winding
under the reflection is not a visual concern.

Run:
    python bridge.py --stage sample.usda --port 8765
Then point a Babylon Live Sync web client at ws://localhost:8765.
"""

import argparse
import asyncio
import math
import os
import sys
import threading

from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdLux, UsdShade

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Shared", "python"))
import blp_protocol as blp  # noqa: E402


# ---------------------------------------------------------------------------
# Coordinate conversion (Y-up right-handed USD -> Y-up left-handed Babylon)
# ---------------------------------------------------------------------------

def _point_yup(x, y, z):
    return (x, y, -z)


def _point_zup(x, y, z):
    return (x, z, -y)


def _is_vec(v):
    """True for a Gf.Vec*/tuple-like colour value (not a scalar or None)."""
    return v is not None and hasattr(v, "__len__") and len(v) >= 3


class UsdBridge:
    def __init__(self, stage):
        self.stage = stage
        self._ids = {}
        self._counter = 1
        up = UsdGeom.GetStageUpAxis(stage)
        self._point = _point_zup if up == UsdGeom.Tokens.z else _point_yup
        self._zup = (up == UsdGeom.Tokens.z)

    # --- id assignment ---------------------------------------------------
    def _id(self, path):
        key = str(path)
        if key not in self._ids:
            self._ids[key] = self._counter
            self._counter += 1
        return self._ids[key]

    def has_id(self, path):
        return str(path) in self._ids

    # --- transforms ------------------------------------------------------
    def _node_trs(self, prim):
        xformable = UsdGeom.Xformable(prim)
        world = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        xf = Gf.Transform(world)
        t = xf.GetTranslation()
        q = xf.GetRotation().GetQuat()
        s = xf.GetScale()
        qi = q.GetImaginary()
        qx, qy, qz, qw = qi[0], qi[1], qi[2], q.GetReal()
        if self._zup:
            # (x,y,z)->(x,z,-y): rotation conjugated by that basis.
            pos = (t[0], t[2], -t[1])
            quat = (qx, qz, -qy, qw)
            scale = (s[0], s[2], s[1])
        else:
            # (x,y,z)->(x,y,-z): conjugation by diag(1,1,-1).
            pos = (t[0], t[1], -t[2])
            quat = (-qx, -qy, qz, qw)
            scale = (s[0], s[1], s[2])
        return pos, quat, scale

    def _world_forward(self, prim):
        world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        # USD cameras/lights look down local -Z; row 2 is the world Z axis.
        z = world.ExtractRotationMatrix().GetRow(2)
        d = self._point(-z[0], -z[1], -z[2])
        n = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) or 1.0
        return (d[0] / n, d[1] / n, d[2] / n)

    # --- geometry --------------------------------------------------------
    def _mesh_arrays(self, prim):
        """Flatten a UsdGeom.Mesh into Babylon-space (positions, normals, uvs,
        indices). Authored normals (schema ``normals`` or ``primvars:normals``)
        and UVs (``primvars:st`` and common aliases) are honoured, respecting
        their interpolation (vertex/varying/faceVarying/uniform/constant). When
        any attribute is faceVarying (or uniform), geometry is expanded per
        face-corner so all streams stay index-aligned; otherwise the compact
        per-point form is used. Returns None if the mesh has no drawable data."""
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        idx = mesh.GetFaceVertexIndicesAttr().Get()
        if not pts or not counts or not idx:
            return None

        normals, n_interp = self._mesh_normals(prim, mesh)
        st_vals, st_interp = self._mesh_uvs(prim)

        fv = UsdGeom.Tokens.faceVarying
        uni = UsdGeom.Tokens.uniform
        expand = n_interp in (fv, uni) or st_interp in (fv, uni)

        def sample(vals, interp, corner, point, face):
            if interp == fv:
                return vals[corner]
            if interp == uni:
                return vals[face]
            if interp == UsdGeom.Tokens.constant:
                return vals[0]
            return vals[point]  # vertex / varying

        positions, out_norms, out_uvs, indices = [], [], [], []

        if not expand:
            for p in pts:
                bp = self._point(p[0], p[1], p[2])
                positions += [bp[0], bp[1], bp[2]]
            if normals:
                for pi in range(len(pts)):
                    n = sample(normals, n_interp, 0, pi, 0)
                    bn = self._point(n[0], n[1], n[2])
                    out_norms += [bn[0], bn[1], bn[2]]
            if st_vals:
                for pi in range(len(pts)):
                    uv = sample(st_vals, st_interp, 0, pi, 0)
                    out_uvs += [uv[0], 1.0 - uv[1]]
            o = 0
            for c in counts:
                for k in range(1, c - 1):
                    indices += [idx[o], idx[o + k], idx[o + k + 1]]
                o += c
        else:
            corner = 0
            for face, c in enumerate(counts):
                base = len(positions) // 3
                for k in range(c):
                    pi = idx[corner + k]
                    p = pts[pi]
                    bp = self._point(p[0], p[1], p[2])
                    positions += [bp[0], bp[1], bp[2]]
                    if normals:
                        n = sample(normals, n_interp, corner + k, pi, face)
                        bn = self._point(n[0], n[1], n[2])
                        out_norms += [bn[0], bn[1], bn[2]]
                    if st_vals:
                        uv = sample(st_vals, st_interp, corner + k, pi, face)
                        out_uvs += [uv[0], 1.0 - uv[1]]
                for k in range(1, c - 1):
                    indices += [base, base + k, base + k + 1]
                corner += c

        return positions, (out_norms or None), (out_uvs or None), indices

    def _mesh_normals(self, prim, mesh):
        """(values, interpolation) for authored normals, or (None, None)."""
        vals = mesh.GetNormalsAttr().Get()
        if vals:
            interp = mesh.GetNormalsInterpolation() or UsdGeom.Tokens.vertex
            return vals, interp
        pv = UsdGeom.PrimvarsAPI(prim).GetPrimvar("normals")
        if pv and pv.HasValue():
            return pv.ComputeFlattened(), (pv.GetInterpolation() or UsdGeom.Tokens.vertex)
        return None, None

    def _mesh_uvs(self, prim):
        """(values, interpolation) for the first UV set found, or (None, None)."""
        pv_api = UsdGeom.PrimvarsAPI(prim)
        for name in ("st", "st0", "UVMap", "uv", "map1"):
            pv = pv_api.GetPrimvar(name)
            if pv and pv.HasValue():
                return pv.ComputeFlattened(), (pv.GetInterpolation() or UsdGeom.Tokens.faceVarying)
        return None, None

    # --- emitters --------------------------------------------------------
    def _emit_mesh(self, enc, prim, upsert_node=True):
        arrays = self._mesh_arrays(prim)
        if arrays is None:
            return False
        positions, normals, uvs, indices = arrays

        node_id = self._id(prim.GetPath())
        if upsert_node:
            pos, quat, scale = self._node_trs(prim)
            enc.upsert_node(node_id, 0, blp.KIND_MESH, prim.GetName(), pos, quat, scale)
        enc.upsert_mesh_geometry(node_id, positions, normals, uvs, indices)
        self._emit_material(enc, node_id, prim, include_textures=True)
        return True

    def _base_color(self, prim):
        try:
            dc = UsdGeom.Gprim(prim).GetDisplayColorAttr().Get()
            if dc and len(dc) > 0:
                c = dc[0]
                return (c[0], c[1], c[2], 1.0)
        except Exception:
            pass
        return (0.8, 0.8, 0.8, 1.0)

    # --- materials (UsdPreviewSurface -> PBR) ----------------------------
    def _emit_material(self, enc, node_id, prim, include_textures=True):
        info = self._material_info(prim)
        enc.upsert_material(node_id, info["rgba"], info["metallic"], info["roughness"],
                            info["emissive"], info["emissive_strength"])
        if include_textures:
            for channel, data in info["textures"].items():
                enc.upsert_material_texture(node_id, channel, data)

    def _material_info(self, prim):
        """Extract PBR from the bound UsdPreviewSurface, falling back to
        displayColor. Returns a dict of scalars + a {channel: bytes} texture map
        (base/metallic-roughness/normal/emissive/occlusion)."""
        info = {
            "rgba": (0.8, 0.8, 0.8, 1.0),
            "metallic": 0.0,
            "roughness": 0.6,
            "emissive": (0.0, 0.0, 0.0),
            "emissive_strength": 0.0,
            "textures": {},
        }
        shader = self._bound_surface(prim)
        if shader is None:
            info["rgba"] = self._base_color(prim)
            return info

        diff = self._input_value(shader, "diffuseColor")
        if _is_vec(diff):
            opacity = self._input_value(shader, "opacity")
            a = float(opacity) if isinstance(opacity, (int, float)) else 1.0
            info["rgba"] = (diff[0], diff[1], diff[2], a)
        metallic = self._input_value(shader, "metallic")
        if isinstance(metallic, (int, float)):
            info["metallic"] = float(metallic)
        rough = self._input_value(shader, "roughness")
        if isinstance(rough, (int, float)):
            info["roughness"] = float(rough)
        emis = self._input_value(shader, "emissiveColor")
        if _is_vec(emis):
            info["emissive"] = (emis[0], emis[1], emis[2])
            if any(v > 1e-6 for v in info["emissive"]):
                info["emissive_strength"] = 1.0

        tex = info["textures"]
        base = self._connected_texture(shader, "diffuseColor")
        if base:
            b = self._read_texture_bytes(base)
            if b:
                tex[blp.TEX_BASECOLOR] = b
        nrm = self._connected_texture(shader, "normal")
        if nrm:
            b = self._read_texture_bytes(nrm)
            if b:
                tex[blp.TEX_NORMAL] = b
        emt = self._connected_texture(shader, "emissiveColor")
        if emt:
            b = self._read_texture_bytes(emt)
            if b:
                tex[blp.TEX_EMISSIVE] = b
                info["emissive_strength"] = max(info["emissive_strength"], 1.0)
        occ = self._connected_texture(shader, "occlusion")
        if occ:
            b = self._read_texture_bytes(occ)
            if b:
                tex[blp.TEX_OCCLUSION] = b

        # glTF ORM: metallic + roughness share one texture (metal=B, rough=G).
        m_src = self._connected_texture(shader, "metallic")
        r_src = self._connected_texture(shader, "roughness")
        mr = r_src or m_src
        if m_src and r_src and m_src.GetPath() != r_src.GetPath():
            mr = r_src  # separate maps: prefer roughness carrier
        if mr:
            b = self._read_texture_bytes(mr)
            if b:
                tex[blp.TEX_METALROUGH] = b

        return info

    def _bound_surface(self, prim):
        """The UsdPreviewSurface UsdShade.Shader bound to `prim`, or None."""
        try:
            bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        except Exception:
            return None
        mat = bound[0] if isinstance(bound, (tuple, list)) else bound
        if not mat:
            return None
        try:
            surface = mat.ComputeSurfaceSource()
        except Exception:
            return None
        shader = surface[0] if isinstance(surface, (tuple, list)) else surface
        if not shader:
            return None
        return shader

    @staticmethod
    def _input_value(shader, name):
        inp = shader.GetInput(name)
        return inp.Get() if inp else None

    def _connected_texture(self, shader, input_name):
        """The connected UsdUVTexture shader prim feeding `input_name`, or None."""
        inp = shader.GetInput(input_name)
        if not inp:
            return None
        conns = inp.GetAttr().GetConnections()
        if not conns:
            return None
        src_prim = self.stage.GetPrimAtPath(conns[0].GetPrimPath())
        if not src_prim or not src_prim.IsValid():
            return None
        if UsdShade.Shader(src_prim).GetIdAttr().Get() != "UsdUVTexture":
            return None
        return src_prim

    def _read_texture_bytes(self, tex_prim):
        fin = UsdShade.Shader(tex_prim).GetInput("file")
        asset = fin.Get() if fin else None
        if not asset:
            return None
        path = getattr(asset, "resolvedPath", "") or getattr(asset, "path", "") or str(asset)
        if not path:
            return None
        if not os.path.isabs(path):
            base = os.path.dirname(self.stage.GetRootLayer().realPath or "")
            cand = os.path.join(base, path)
            if os.path.exists(cand):
                path = cand
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            return None

    def _emit_light(self, enc, prim):
        node_id = self._id(prim.GetPath())
        color = (1.0, 1.0, 1.0)
        intensity = 1.0
        try:
            light = UsdLux.LightAPI(prim)
            c = light.GetColorAttr().Get()
            if c is not None:
                color = (c[0], c[1], c[2])
            i = light.GetIntensityAttr().Get()
            if i is not None:
                intensity = float(i)
        except Exception:
            pass

        if prim.IsA(UsdLux.DistantLight):
            d = self._world_forward(prim)
            enc.upsert_light(node_id, blp.LIGHT_DIRECTIONAL, d, color, max(0.05, intensity))
        else:
            pos, _q, _s = self._node_trs(prim)
            enc.upsert_light(node_id, blp.LIGHT_POINT, pos, color, max(0.05, intensity / 1000.0))

    def _emit_camera(self, enc, prim):
        pos, _q, _s = self._node_trs(prim)
        # Place an arc-rotate camera at the USD camera's position looking at the
        # origin (a sensible default for origin-centred scenes; orientation is
        # otherwise ignored in this first bridge).
        target = (0.0, 0.0, 0.0)
        dx, dy, dz = pos[0] - target[0], pos[1] - target[1], pos[2] - target[2]
        radius = max(0.1, math.sqrt(dx * dx + dy * dy + dz * dz))
        beta = math.acos(max(-1.0, min(1.0, dy / radius)))
        alpha = math.atan2(dz, dx)
        enc.set_camera_arcrotate(alpha, beta, radius, target)

    # --- public: snapshot + delta ---------------------------------------
    def _raw_trs(self, prim):
        """USD-space (glTF-space) TRS — no Babylon conversion. Used for the
        bake-once flow, where the glTF and the deltas share glTF space."""
        world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        xf = Gf.Transform(world)
        t = xf.GetTranslation()
        q = xf.GetRotation().GetQuat()
        s = xf.GetScale()
        qi = q.GetImaginary()
        return ((t[0], t[1], t[2]), (qi[0], qi[1], qi[2], q.GetReal()), (s[0], s[1], s[2]))

    def _mesh_records(self):
        """Collect glTF-space mesh data for baking (positions local, raw TRS)."""
        records = []
        for prim in self.stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh):
                continue
            mesh = UsdGeom.Mesh(prim)
            pts = mesh.GetPointsAttr().Get()
            counts = mesh.GetFaceVertexCountsAttr().Get()
            idx = mesh.GetFaceVertexIndicesAttr().Get()
            if not pts or not counts or not idx:
                continue
            positions = []
            for p in pts:
                positions += [p[0], p[1], p[2]]
            indices = []
            o = 0
            for c in counts:
                for k in range(1, c - 1):
                    indices += [idx[o], idx[o + k], idx[o + k + 1]]
                o += c
            t, q, s = self._raw_trs(prim)
            records.append({
                "name": str(prim.GetPath()),
                "positions": positions,
                "indices": indices,
                "base_color": self._base_color(prim),
                "translation": t,
                "rotation": q,
                "scale": s,
            })
        return records

    def export_gltf(self, out_path):
        """Bake the stage's meshes to a self-contained glTF (node.name=PrimPath)."""
        import gltf_export
        return gltf_export.write_gltf(self._mesh_records(), out_path)

    def build_snapshot(self):
        enc = blp.CommandEncoder()
        enc.reset_scene()
        enc.set_clear_color((0.05, 0.06, 0.09, 1.0))

        camera_prim = None
        light_count = 0
        for prim in self.stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                self._emit_mesh(enc, prim, upsert_node=True)
            elif prim.IsA(UsdLux.BoundableLightBase) or prim.IsA(UsdLux.NonboundableLightBase):
                self._emit_light(enc, prim)
                light_count += 1
            elif prim.IsA(UsdGeom.Camera) and camera_prim is None:
                camera_prim = prim

        if camera_prim is not None:
            self._emit_camera(enc, camera_prim)
        if light_count == 0:
            enc.upsert_light(1000000, blp.LIGHT_HEMISPHERIC, (0.2, 1.0, 0.3), (1.0, 1.0, 1.0), 0.7)
        return enc.finish()

    def build_snapshot_baked(self):
        """Baked flow: the client has already loaded the glTF. Bind each mesh to
        its pre-loaded node by path (no geometry), then add camera + lights. No
        ResetScene — that would drop the loaded glTF."""
        enc = blp.CommandEncoder()
        enc.set_clear_color((0.05, 0.06, 0.09, 1.0))
        camera_prim = None
        light_count = 0
        for prim in self.stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                enc.bind_node_path(self._id(prim.GetPath()), str(prim.GetPath()))
            elif prim.IsA(UsdLux.BoundableLightBase) or prim.IsA(UsdLux.NonboundableLightBase):
                self._emit_light(enc, prim)
                light_count += 1
            elif prim.IsA(UsdGeom.Camera) and camera_prim is None:
                camera_prim = prim
        if camera_prim is not None:
            self._emit_camera(enc, camera_prim)
        if light_count == 0:
            enc.upsert_light(1000000, blp.LIGHT_HEMISPHERIC, (0.2, 1.0, 0.3), (1.0, 1.0, 1.0), 0.7)
        return enc.finish()

    def build_delta(self, prim_paths, baked=False):
        """Emit transform/material updates for the given (already-known) prims.
        In baked mode, transforms are in glTF space (raw), matching the baked
        node's local frame; otherwise they are Babylon-converted."""
        enc = blp.CommandEncoder()
        for path in prim_paths:
            prim = self.stage.GetPrimAtPath(path)
            if not prim or not prim.IsValid():
                continue
            if prim.IsA(UsdGeom.Mesh):
                node_id = self._id(prim.GetPath())
                if baked:
                    pos, quat, scale = self._raw_trs(prim)
                else:
                    pos, quat, scale = self._node_trs(prim)
                    self._emit_material(enc, node_id, prim, include_textures=False)
                enc.set_transform(node_id, pos, quat, scale)
            elif prim.IsA(UsdLux.BoundableLightBase) or prim.IsA(UsdLux.NonboundableLightBase):
                self._emit_light(enc, prim)
        return None if enc.empty() else enc.finish()


# ---------------------------------------------------------------------------
# WebSocket server + change notices
# ---------------------------------------------------------------------------

async def serve(stage, host="localhost", port=8765, throttle_ms=50, baked=False, animate=False):
    import websockets

    bridge = UsdBridge(stage)
    clients = set()
    dirty = set()
    lock = threading.Lock()

    # In baked mode the client loads a glTF first; bind ids to prim paths up front
    # so change notices for those prims produce deltas.
    if baked:
        for prim in stage.Traverse():
            if prim.IsA(UsdGeom.Mesh):
                bridge._id(prim.GetPath())

    def on_changed(notice, sender):
        with lock:
            for p in list(notice.GetResyncedPaths()) + list(notice.GetChangedInfoOnlyPaths()):
                prim_path = p.GetPrimPath()
                if bridge.has_id(prim_path):
                    dirty.add(prim_path)

    listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, on_changed, stage)

    async def handler(ws):
        clients.add(ws)
        try:
            await ws.send(bridge.build_snapshot_baked() if baked else bridge.build_snapshot())
            await ws.wait_closed()
        finally:
            clients.discard(ws)

    async def broadcaster():
        while True:
            await asyncio.sleep(throttle_ms / 1000.0)
            with lock:
                if not dirty or not clients:
                    dirty.clear()
                    continue
                paths = list(dirty)
                dirty.clear()
            buf = bridge.build_delta(paths, baked=baked)
            if buf:
                for ws in list(clients):
                    try:
                        await ws.send(buf)
                    except Exception:
                        clients.discard(ws)

    async def animator():
        """Demo driver: orbit the first mesh by editing the stage, so clients see
        the full stage-edit -> ObjectsChanged -> delta loop with no external tool."""
        import time
        prim = next((p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)), None)
        if prim is None:
            return
        xf = UsdGeom.Xformable(prim)
        op = next((o for o in xf.GetOrderedXformOps()
                   if o.GetOpType() == UsdGeom.XformOp.TypeTranslate), None)
        if op is None:
            op = xf.AddTranslateOp()
        start = time.time()
        while True:
            await asyncio.sleep(0.05)
            t = time.time() - start
            op.Set(Gf.Vec3d(math.cos(t) * 2.0, 1.0, math.sin(t) * 2.0))

    async with websockets.serve(handler, host, port):
        mode = "baked (bind glTF nodes by path)" if baked else "streaming geometry"
        print("[usd-bridge] serving %s [%s%s] on ws://%s:%d" %
              (stage.GetRootLayer().identifier, mode, ", animating" if animate else "", host, port))
        if animate:
            await asyncio.gather(broadcaster(), animator())
        else:
            await broadcaster()
    del listener


def main():
    ap = argparse.ArgumentParser(description="USD -> Babylon Live Sync WebSocket bridge")
    ap.add_argument("--stage", required=True, help="USD stage path or omniverse:// URL")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bake", metavar="OUT.gltf",
                    help="Bake the stage's meshes to a glTF (node.name=PrimPath) and exit.")
    ap.add_argument("--baked", action="store_true",
                    help="Serve in baked mode: bind pre-loaded glTF nodes by path + stream deltas.")
    ap.add_argument("--animate", action="store_true",
                    help="Demo: orbit the first mesh by editing the stage on a timer.")
    args = ap.parse_args()

    stage = Usd.Stage.Open(args.stage)
    if stage is None:
        print("[usd-bridge] failed to open stage: %s" % args.stage)
        sys.exit(2)

    if args.bake:
        out = UsdBridge(stage).export_gltf(args.bake)
        print("[usd-bridge] baked glTF -> %s" % out)
        return

    try:
        asyncio.run(serve(stage, args.host, args.port, baked=args.baked, animate=args.animate))
    except KeyboardInterrupt:
        print("\n[usd-bridge] stopped")


if __name__ == "__main__":
    main()
