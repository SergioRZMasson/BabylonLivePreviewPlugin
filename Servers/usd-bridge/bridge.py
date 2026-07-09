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

from pxr import Gf, Tf, Usd, UsdGeom, UsdLux

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "Shared", "python"))
import blp_protocol as blp  # noqa: E402


# ---------------------------------------------------------------------------
# Coordinate conversion (Y-up right-handed USD -> Y-up left-handed Babylon)
# ---------------------------------------------------------------------------

def _point_yup(x, y, z):
    return (x, y, -z)


def _point_zup(x, y, z):
    return (x, z, -y)


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

    # --- emitters --------------------------------------------------------
    def _emit_mesh(self, enc, prim, upsert_node=True):
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        idx = mesh.GetFaceVertexIndicesAttr().Get()
        if not pts or not counts or not idx:
            return False

        positions = []
        for p in pts:
            bp = self._point(p[0], p[1], p[2])
            positions += [bp[0], bp[1], bp[2]]

        # Fan-triangulate arbitrary polygons. Winding is irrelevant (double-sided).
        indices = []
        o = 0
        for c in counts:
            for k in range(1, c - 1):
                indices += [idx[o], idx[o + k], idx[o + k + 1]]
            o += c

        node_id = self._id(prim.GetPath())
        if upsert_node:
            pos, quat, scale = self._node_trs(prim)
            enc.upsert_node(node_id, 0, blp.KIND_MESH, prim.GetName(), pos, quat, scale)
        enc.upsert_mesh_geometry(node_id, positions, None, None, indices)

        rgba = self._base_color(prim)
        enc.upsert_material(node_id, rgba, 0.0, 0.6)
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
                    enc.upsert_material(node_id, self._base_color(prim), 0.0, 0.6)
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
