"""Babylon Live Preview — Blender add-on.

Renders the current Blender scene live in Babylon.js (via Babylon Native) and
displays the result inside the 3D viewport. Target: Blender 4.2 LTS (Python 3.11).

Architecture: this add-on loads the shared C-API DLL (babylon_live_preview.dll)
via ctypes (bridge.py), pushes scene edits as protocol command buffers
(capture.py), pumps the native render loop on a timer, and paints the readback
frame with the GPU module (viewport.py).
"""

bl_info = {
    "name": "Babylon Live Preview",
    "author": "Babylon Live Preview",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Babylon",
    "description": "Live-preview the scene rendered by Babylon.js (Babylon Native).",
    "category": "3D View",
}

import os

import bpy

from . import bridge
from . import capture
from . import viewport


def _default_dll_path():
    # Cross-platform: the native module is babylon_live_preview.dll (Windows),
    # libbabylon_live_preview.dylib (macOS) or libbabylon_live_preview.so (Linux).
    # The packaged add-on ships it under bin/; also allow a sibling file and the
    # in-repo dev build output during development.
    name = bridge.library_filename()
    here = os.path.dirname(__file__)
    repo = os.path.normpath(os.path.join(here, "..", "..", "..", ".."))
    candidates = [
        os.path.join(here, name),
        os.path.join(here, "bin", name),
        bridge.default_build_library(repo),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


class BLP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    dll_path: bpy.props.StringProperty(
        name="Core Module",
        subtype='FILE_PATH',
        default=_default_dll_path(),
        description="Path to the Babylon Live Preview native module "
                    "(babylon_live_preview.dll / .dylib / .so)",
    )
    render_width: bpy.props.IntProperty(name="Width", default=1280, min=64, max=8192)
    render_height: bpy.props.IntProperty(name="Height", default=720, min=64, max=8192)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "dll_path")
        row = layout.row()
        row.prop(self, "render_width")
        row.prop(self, "render_height")


# Module-level session state (one preview at a time for now).
_bridge = None
_sync = None            # capture.SceneSync once the initial snapshot is pushed
_pushed = False         # initial snapshot submitted
_readback_logged = False


def _on_depsgraph_update(scene, depsgraph=None):
    """Blender handler: emit incremental changes to the live Babylon scene."""
    global _bridge, _sync
    if _bridge is None or not _bridge.alive or _sync is None:
        return
    try:
        buf = _sync.sync(bpy.context)
        if buf is not None:
            _bridge.submit_commands(buf)
    except Exception as exc:  # noqa: BLE001
        print("[BLP] incremental sync failed: %s" % exc)


def _redraw_viewports():
    wm = bpy.context.window_manager
    if not wm:
        return
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _pump():
    """bpy.app.timers callback: pump a frame, sync readback, repaint.

    Returns seconds until the next call, or None to stop the timer. Using a
    module timer (rather than a modal operator) makes the pump independent of
    operator event delivery, which is unreliable when launched from a button.
    """
    global _bridge, _sync, _pushed, _readback_logged
    if _bridge is None or not _bridge.alive:
        return None
    try:
        _bridge.render_frame()

        if not _pushed and _bridge.is_ready():
            _sync = capture.SceneSync()
            buf = _sync.initial_snapshot(bpy.context)
            _bridge.submit_commands(buf)
            if _on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
            _pushed = True
            print("[BLP] pushed initial snapshot: %d bytes" % len(buf))

        # Acquire any completed frame FIRST, then request the next one.
        # (request_readback starts a new capture and clears the ready flag, so
        # requesting before acquiring would always drop the finished frame.)
        result = _bridge.try_acquire_readback()
        if result is not None:
            data, w, h = result
            viewport.update_texture(data, w, h)
            if not _readback_logged:
                _readback_logged = True
                print("[BLP] first readback %dx%d -> viewport texture updated" % (w, h))
        _bridge.request_readback()

        _redraw_viewports()
    except Exception as exc:  # noqa: BLE001
        print("[BLP] pump error: %s" % exc)
    return 1.0 / 60.0


def _start(context):
    global _bridge, _sync, _pushed, _readback_logged
    addon = context.preferences.addons.get(__package__)
    if addon is not None:
        prefs = addon.preferences
        width, height = prefs.render_width, prefs.render_height
        dll_path = bpy.path.abspath(prefs.dll_path) if prefs.dll_path else _default_dll_path()
    else:
        width, height, dll_path = 1280, 720, _default_dll_path()

    print("[BLP] starting live preview, dll=%s" % dll_path)
    try:
        _bridge = bridge.BabylonBridge(dll_path)
    except Exception as exc:  # noqa: BLE001
        _bridge = None
        return False, "Failed to load core DLL: %s" % exc

    scripts_root = os.path.join(os.path.dirname(dll_path), "Scripts")
    if not _bridge.create(width, height, scripts_root):
        _bridge = None
        return False, "blp_create failed (see console). scriptsRoot=%s" % scripts_root

    _sync = None
    _pushed = False
    _readback_logged = False
    viewport.enable()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.0)
    return True, "Babylon Live Preview started"


def _stop():
    global _bridge, _sync, _pushed, _readback_logged
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    viewport.disable()
    if _bridge is not None:
        _bridge.destroy()
        _bridge = None
    _sync = None
    _pushed = False
    _readback_logged = False
    _redraw_viewports()


class BLP_OT_toggle_preview(bpy.types.Operator):
    """Start/stop the Babylon live preview."""

    bl_idname = "babylon.toggle_live_preview"
    bl_label = "Toggle Babylon Live Preview"

    def execute(self, context):
        global _bridge
        if _bridge is not None and _bridge.alive:
            _stop()
            self.report({'INFO'}, "Babylon Live Preview stopped")
            return {'FINISHED'}
        ok, message = _start(context)
        self.report({'INFO'} if ok else {'ERROR'}, message)
        return {'FINISHED'} if ok else {'CANCELLED'}


class BLP_PT_panel(bpy.types.Panel):
    bl_label = "Babylon Live Preview"
    bl_idname = "BLP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Babylon"

    def draw(self, context):
        self.layout.operator(BLP_OT_toggle_preview.bl_idname, text="Toggle Live Preview")


_classes = (
    BLP_AddonPreferences,
    BLP_OT_toggle_preview,
    BLP_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    _stop()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
