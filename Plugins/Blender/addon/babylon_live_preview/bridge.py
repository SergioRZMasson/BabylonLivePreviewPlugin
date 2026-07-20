"""ctypes bridge to the BabylonLivePreview C ABI (see c_api.h).

Loads babylon_live_preview.dll and exposes a Pythonic wrapper around a live
preview session. Used by the Blender add-on; keeps zero Blender dependencies so
it can be unit-tested standalone.
"""

import ctypes
import os
import sys


def library_filename():
    """Platform-specific filename of the built Babylon Live Preview native module."""
    if sys.platform == "darwin":
        return "libbabylon_live_preview.dylib"
    if sys.platform == "win32":
        return "babylon_live_preview.dll"
    return "libbabylon_live_preview.so"


def default_build_library(repo_root):
    """Best-effort path to the in-repo built native module (dev convenience).

    Handles multi-config (Windows: Release/Debug subfolders) and single-config
    (macOS/Linux) generators, plus custom build dirs like build/macos-arm64/.
    """
    import glob

    name = library_filename()
    blender = ("Plugins", "Blender")
    # Cover the direct build dir and nested preset dirs (e.g. build/macos-arm64),
    # with and without a per-config subfolder (Release/Debug on multi-config gens).
    patterns = [
        os.path.join(repo_root, "build", *blender, name),
        os.path.join(repo_root, "build", *blender, "*", name),
        os.path.join(repo_root, "build*", *blender, name),
        os.path.join(repo_root, "build*", *blender, "*", name),
        os.path.join(repo_root, "build", "*", *blender, name),
        os.path.join(repo_root, "build", "*", *blender, "*", name),
        os.path.join(repo_root, "build*", "*", *blender, name),
        os.path.join(repo_root, "build*", "*", *blender, "*", name),
    ]
    hits = []
    for pattern in patterns:
        hits.extend(h for h in glob.glob(pattern) if os.path.isfile(h))
    if hits:
        # Prefer the most recently built module.
        return max(set(hits), key=os.path.getmtime)
    # Canonical Release path even if missing, so error messages are informative.
    return os.path.join(repo_root, "build", *blender, "Release", name)


class BlpConfig(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("renderMode", ctypes.c_int32),
        ("scriptsRoot", ctypes.c_char_p),
        ("d3dDevice", ctypes.c_void_p),
        ("nativeWindow", ctypes.c_void_p),
        ("loadLoaders", ctypes.c_int32),
        ("loadMaterials", ctypes.c_int32),
        ("enableLogging", ctypes.c_int32),
        ("msaaSamples", ctypes.c_uint32),
    ]


class BabylonBridge:
    """Thin wrapper over one native LivePreviewSession."""

    def __init__(self, dll_path):
        if not os.path.isfile(dll_path):
            raise FileNotFoundError("Babylon Live Preview native module not found: %s" % dll_path)
        # On Windows, ensure dependent DLLs (V8, Babylon Native) next to the
        # module resolve. On macOS/Linux the module is self-contained (Babylon
        # Native is linked statically), so this is a Windows-only no-op elsewhere.
        dll_dir = os.path.dirname(dll_path)
        if hasattr(os, "add_dll_directory") and os.path.isdir(dll_dir):
            self._dll_dir_handle = os.add_dll_directory(dll_dir)
        self._lib = ctypes.CDLL(dll_path)
        self._bind()
        self._session = None

    def _bind(self):
        lib = self._lib
        lib.blp_create.argtypes = [ctypes.POINTER(BlpConfig)]
        lib.blp_create.restype = ctypes.c_void_p
        lib.blp_destroy.argtypes = [ctypes.c_void_p]
        lib.blp_resize.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        lib.blp_render_frame.argtypes = [ctypes.c_void_p]
        lib.blp_is_ready.argtypes = [ctypes.c_void_p]
        lib.blp_is_ready.restype = ctypes.c_int32
        lib.blp_submit_commands.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.blp_eval.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.blp_request_readback.argtypes = [ctypes.c_void_p]
        lib.blp_try_acquire_readback.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        lib.blp_try_acquire_readback.restype = ctypes.c_int32

    def create(self, width, height, scripts_root, render_mode=0):
        cfg = BlpConfig()
        cfg.width = int(width)
        cfg.height = int(height)
        cfg.renderMode = int(render_mode)
        cfg.scriptsRoot = scripts_root.encode("utf-8")
        cfg.d3dDevice = None
        cfg.nativeWindow = None
        cfg.loadLoaders = 1
        cfg.loadMaterials = 1
        cfg.enableLogging = 1
        cfg.msaaSamples = 4
        self._session = self._lib.blp_create(ctypes.byref(cfg))
        return self._session is not None

    def destroy(self):
        if self._session:
            self._lib.blp_destroy(self._session)
            self._session = None

    @property
    def alive(self):
        return self._session is not None

    def resize(self, width, height):
        if self._session:
            self._lib.blp_resize(self._session, int(width), int(height))

    def render_frame(self):
        if self._session:
            self._lib.blp_render_frame(self._session)

    def is_ready(self):
        return bool(self._session and self._lib.blp_is_ready(self._session))

    def submit_commands(self, data):
        if self._session and data:
            self._lib.blp_submit_commands(self._session, data, len(data))

    def eval(self, code):
        if self._session:
            self._lib.blp_eval(self._session, code.encode("utf-8"))

    def request_readback(self):
        if self._session:
            self._lib.blp_request_readback(self._session)

    def try_acquire_readback(self):
        """Return (rgba_bytes, width, height) once available, else None."""
        if not self._session:
            return None
        out = ctypes.POINTER(ctypes.c_uint8)()
        w = ctypes.c_uint32()
        h = ctypes.c_uint32()
        n = ctypes.c_size_t()
        ok = self._lib.blp_try_acquire_readback(
            self._session, ctypes.byref(out), ctypes.byref(w), ctypes.byref(h), ctypes.byref(n))
        if not ok:
            return None
        data = ctypes.string_at(out, n.value)
        return (data, w.value, h.value)
