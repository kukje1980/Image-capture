"""PyOpenGL is pointed at Qt's software OpenGL library (Windows · 소프트웨어 렌더링)."""
import sys
import types

import pytest

pytest.importorskip("OpenGL")

from fundusview.ui import glbind


class _Fn:
    restype = None

    def __init__(self, value=1):
        self.value = value

    def __call__(self, *a):
        return self.value


class _Dll:
    def __init__(self, context=1):
        self.wglGetCurrentContext = _Fn(context)
        self.wglGetProcAddress = _Fn()


@pytest.fixture
def platform(monkeypatch):
    """A stand-in for OpenGL.platform, before OpenGL.GL is imported."""
    plat = types.ModuleType("OpenGL.platform")
    plat.PLATFORM = types.SimpleNamespace(GL="system", OpenGL="system")
    plat.GetCurrentContext = plat.CurrentContextIsValid = "system"
    import OpenGL
    monkeypatch.setitem(sys.modules, "OpenGL.platform", plat)
    monkeypatch.setattr(OpenGL, "platform", plat, raising=False)
    monkeypatch.delitem(sys.modules, "OpenGL.GL", raising=False)
    monkeypatch.delitem(sys.modules, "OpenGL.error", raising=False)
    return plat


def test_rebind_points_every_lookup_at_the_dll(platform):
    dll = _Dll()
    assert glbind._rebind(dll)
    p = platform.PLATFORM
    assert p.GL is dll and p.OpenGL is dll and p.WGL is dll
    assert p.getExtensionProcedure is dll.wglGetProcAddress          # glCreateProgram … are found here
    assert p.GetCurrentContext is dll.wglGetCurrentContext is p.CurrentContextIsValid
    assert platform.GetCurrentContext is dll.wglGetCurrentContext is platform.CurrentContextIsValid
    assert dll.wglGetProcAddress.restype is not None                 # a pointer, not a 32-bit int


def test_rebind_updates_a_loaded_error_checker(platform, monkeypatch):
    err = types.ModuleType("OpenGL.error")
    err._error_checker = types.SimpleNamespace(_isValid="system")
    monkeypatch.setitem(sys.modules, "OpenGL.error", err)
    dll = _Dll()
    assert glbind._rebind(dll)
    assert err._error_checker._isValid is dll.wglGetCurrentContext


def test_no_rebind_once_gl_is_imported(platform, monkeypatch):
    monkeypatch.setitem(sys.modules, "OpenGL.GL", types.ModuleType("OpenGL.GL"))
    assert not glbind._rebind(_Dll())
    assert platform.PLATFORM.GL == "system"


def test_nothing_changes_without_the_software_library(platform, monkeypatch):
    monkeypatch.setattr(glbind, "_loaded_software_gl", lambda: None)
    assert glbind.bind_pyopengl_to_qt() is False
    assert platform.PLATFORM.GL == "system"


def test_a_failure_leaves_pyopengl_as_it_was(monkeypatch):
    def boom():
        raise OSError("no kernel32")
    monkeypatch.setattr(glbind, "_loaded_software_gl", boom)
    assert glbind.bind_pyopengl_to_qt() is False


@pytest.mark.skipif(sys.platform == "win32", reason="Windows looks for opengl32sw.dll")
def test_other_systems_are_left_alone():
    assert glbind._loaded_software_gl() is None


def test_renderer_text_reads_through_qt():
    class F:
        def glGetString(self, name):
            return {0x1F00: b"Mesa", 0x1F01: "llvmpipe", 0x1F02: None}[name]

    class Ctx:
        def functions(self):
            return F()

    assert glbind.renderer_text(Ctx()) == "Mesa · llvmpipe"
    assert glbind.renderer_text(object()) == ""
