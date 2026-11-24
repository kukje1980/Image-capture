"""PyOpenGL looks in the OpenGL library that Qt's context lives in (Windows: opengl32sw.dll)."""
import types

from fundusview.ui import glbind


class _Fn:
    def __init__(self, value):
        self.value, self.restype = value, None

    def __call__(self, *args):
        return self.value


class _Dll:
    def __init__(self, context):
        self.wglGetCurrentContext = _Fn(context)
        self.wglGetProcAddress = _Fn(1234)


def test_driver_library_with_a_context_is_left_alone():
    libs = {"opengl32.dll": _Dll(7), "opengl32sw.dll": _Dll(0)}
    assert glbind._context_library(libs.get) is None


def test_software_library_owning_the_context_is_found():
    sw = _Dll(9)
    libs = {"opengl32.dll": _Dll(0), "opengl32sw.dll": sw}
    assert glbind._context_library(libs.get) is sw
    assert glbind._context_library({"opengl32sw.dll": sw}.get) is sw      # (opengl32.dll not loaded at all)


def test_no_context_anywhere_changes_nothing():
    assert glbind._context_library({"opengl32.dll": _Dll(0), "opengl32sw.dll": _Dll(0)}.get) is None
    assert glbind._context_library({}.get) is None


def test_rebind_points_every_lookup_at_the_library():
    sw = _Dll(9)
    platform = types.SimpleNamespace(PLATFORM=types.SimpleNamespace())
    glbind._rebind(platform, sw)
    p = platform.PLATFORM
    assert p.GL is sw and p.OpenGL is sw and p.WGL is sw
    assert p.getExtensionProcedure is sw.wglGetProcAddress
    assert p.GetCurrentContext() == 9 and platform.CurrentContextIsValid() == 9
