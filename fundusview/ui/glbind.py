"""PyOpenGL must call into the same OpenGL library as Qt.

On Windows PyOpenGL always loads the system ``opengl32.dll``. With 소프트웨어 렌더링
(``AA_UseSoftwareOpenGL``) Qt makes its context in the bundled Mesa ``opengl32sw.dll`` instead —
a second, separate OpenGL: the system library then has no current context, hands PyOpenGL no
function ("Attempt to call an undefined function glCreateProgram") and the 3D eye never starts.

``bind_pyopengl_to_qt()`` is called with Qt's context current, before ``OpenGL.GL`` is first
imported: when the current context lives in ``opengl32sw.dll``, PyOpenGL is pointed at that
library. Everywhere else (graphics-card OpenGL, macOS, Linux) it changes nothing.
"""
from __future__ import annotations

import ctypes
import sys

SOFTWARE_DLL = "opengl32sw.dll"


def _loaded_software_gl():
    """Mesa's ``opengl32sw.dll`` when Qt has loaded it and its context is current, else ``None``."""
    if sys.platform != "win32":
        return None
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    handle = k32.GetModuleHandleW(SOFTWARE_DLL)
    if not handle:
        return None
    dll = ctypes.WinDLL(SOFTWARE_DLL, handle=handle)
    dll.wglGetCurrentContext.restype = ctypes.c_void_p
    if not dll.wglGetCurrentContext():
        return None                     # loaded, but the context on this thread is not Mesa's
    return dll


def _rebind(dll) -> bool:
    """Point PyOpenGL's platform at ``dll``. Only before ``OpenGL.GL`` is imported: its functions
    are tied to a library when that module loads."""
    if "OpenGL.GL" in sys.modules:
        return False
    import OpenGL.platform as plat

    p = plat.PLATFORM
    current = dll.wglGetCurrentContext
    current.restype = ctypes.c_void_p
    lookup = dll.wglGetProcAddress
    lookup.restype = ctypes.c_void_p
    # (the platform's lazy properties keep their value on the instance — these replace them)
    p.GL = p.OpenGL = p.WGL = dll
    p.GetCurrentContext = p.CurrentContextIsValid = current
    p.getExtensionProcedure = lookup
    plat.GetCurrentContext = plat.CurrentContextIsValid = current
    checker = getattr(sys.modules.get("OpenGL.error"), "_error_checker", None)
    if checker is not None and hasattr(checker, "_isValid"):
        checker._isValid = current
    return True


def bind_pyopengl_to_qt() -> bool:
    """True when PyOpenGL was pointed at Qt's software OpenGL library."""
    try:
        dll = _loaded_software_gl()
        return bool(dll is not None and _rebind(dll))
    except Exception:
        return False                    # as before: PyOpenGL with the system library


def renderer_text(context) -> str:
    """'제조사 · 렌더러 · 버전' of Qt's current context, asked through Qt (works when PyOpenGL
    does not) — for the message of a 3D that could not start."""
    try:
        f = context.functions()
        parts = []
        for name in (0x1F00, 0x1F01, 0x1F02):       # GL_VENDOR, GL_RENDERER, GL_VERSION
            s = f.glGetString(name)
            if isinstance(s, (bytes, bytearray)):
                s = bytes(s).decode(errors="replace")
            if s:
                parts.append(str(s).strip())
        return " · ".join(parts)
    except Exception:
        return ""
