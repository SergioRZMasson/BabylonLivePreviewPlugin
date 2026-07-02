"""Validate the viewport draw's gpu API calls in Blender (offscreen).

    blender --background --python Plugins/Blender/tests/run_gpu_draw.py

Renders the same IMAGE-shader textured quad viewport.py uses into a GPUOffScreen
(with an explicit pixel-space ortho, since offscreen has no POST_PIXEL matrix)
and checks the centre pixel matches the source texture. Confirms the shader
name, Buffer/GPUTexture, uniform_sampler and batch attributes are valid on 4.2.
"""

import sys

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
    from mathutils import Matrix
except Exception as exc:  # noqa: BLE001
    print("[gpu] import failed: %s" % exc)
    sys.exit(1)

W, H = 64, 64


def main():
    src = bytes([200, 30, 30, 255]) * (W * H)  # solid red-ish
    try:
        buf = gpu.types.Buffer('UBYTE', W * H * 4, src)
        tex = gpu.types.GPUTexture((W, H), format='RGBA8', data=buf)
        shader = gpu.shader.from_builtin('IMAGE')
    except Exception as exc:  # noqa: BLE001
        print("[gpu] setup failed (likely no GPU context in --background): %s" % exc)
        return 2

    try:
        offscreen = gpu.types.GPUOffScreen(W, H)
    except Exception as exc:  # noqa: BLE001
        print("[gpu] GPUOffScreen failed (no headless GPU): %s" % exc)
        return 3

    ortho = Matrix(((2.0 / W, 0, 0, -1),
                    (0, 2.0 / H, 0, -1),
                    (0, 0, -1, 0),
                    (0, 0, 0, 1)))
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 1.0))
            with gpu.matrix.push_pop():
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(ortho)
                batch = batch_for_shader(
                    shader, 'TRI_FAN',
                    {"pos": ((0, 0), (W, 0), (W, H), (0, H)),
                     "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})
                gpu.state.blend_set('NONE')
                shader.bind()
                shader.uniform_sampler("image", tex)
                batch.draw(shader)
            out = fb.read_color(0, 0, W, H, 4, 0, 'UBYTE')
            out.dimensions = W * H * 4
    except Exception as exc:  # noqa: BLE001
        print("[gpu] draw failed: %s" % exc)
        return 4

    c = (H // 2 * W + W // 2) * 4
    center = [out[c], out[c + 1], out[c + 2], out[c + 3]]
    print("[gpu] center pixel = %s (expected ~[200,30,30,255])" % center)
    ok = center[0] > 150 and center[1] < 90 and center[2] < 90
    print("[gpu] %s" % ("PASS - draw pipeline valid" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
