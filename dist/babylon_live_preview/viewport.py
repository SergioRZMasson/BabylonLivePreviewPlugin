"""Viewport display: paint the Babylon-rendered frame inside Blender's 3D view.

The modal operator uploads each CPU readback into a GPUTexture via
`update_texture`; this POST_PIXEL draw handler paints it over the viewport.
(The zero-copy D3D11<->GL interop path is M5; this readback path is M1..M4.)
"""

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

_draw_handle = None
_texture = None
_shader = None
_painted_once = False


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('IMAGE')
    return _shader


def update_texture(rgba_bytes, width, height):
    """Upload readback RGBA8 pixels into a GPUTexture for drawing."""
    global _texture
    if not rgba_bytes or width <= 0 or height <= 0:
        return
    try:
        # Blender 4.2's GPUTexture(data=...) only accepts a FLOAT buffer, so
        # convert the RGBA8 readback to normalized float32 (numpy keeps it fast).
        import numpy as np
        arr = np.frombuffer(rgba_bytes, dtype=np.uint8).astype(np.float32)
        arr *= (1.0 / 255.0)
        buffer = gpu.types.Buffer('FLOAT', width * height * 4, arr)
        _texture = gpu.types.GPUTexture((width, height), format='RGBA8', data=buffer)
    except Exception as exc:  # noqa: BLE001
        print("[BLP] update_texture failed: %s" % exc)


def _draw():
    global _painted_once
    if _texture is None:
        return
    region = bpy.context.region
    if region is None:
        return

    width, height = region.width, region.height
    shader = _get_shader()
    # Readback is top-down; Blender samples bottom-up, so flip V in texCoord.
    batch = batch_for_shader(
        shader, 'TRI_FAN',
        {
            "pos": ((0, 0), (width, 0), (width, height), (0, height)),
            "texCoord": ((0, 1), (1, 1), (1, 0), (0, 0)),
        },
    )
    # Draw opaque: the Babylon back-buffer alpha may be 0, which with alpha
    # blending would make the whole image invisible.
    gpu.state.blend_set('NONE')
    shader.bind()
    shader.uniform_sampler("image", _texture)
    batch.draw(shader)

    if not _painted_once:
        _painted_once = True
        print("[BLP] viewport draw active (%dx%d)" % (width, height))


def enable():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')


def disable():
    global _draw_handle, _texture, _painted_once
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    _texture = None
    _painted_once = False
