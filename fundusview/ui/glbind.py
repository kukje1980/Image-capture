"""PyOpenGL on the OpenGL library Qt draws with (Windows).

Qt has two OpenGL libraries on Windows: the graphics driver's (``opengl32.dll``) and the Mesa
software renderer shipped with PySide6 (``opengl32sw.dll``) — chosen in 설정 → 일반 → 3D 렌더링, and
taken by Qt on its own where the driver has no OpenGL 2 (no graphics driver, remote desktop, a
virtual machine). PyOpenGL knows only ``opengl32.dll``: with Qt's context living in the other
library every call past OpenGL 1.1 was "an undefined function glCreateProgram" and the 3D views
stayed black. ``gl()`` is ``OpenGL.GL`` looking in the library that owns the current context.
"""
from __future__ import annotations

import ctypes
import os
import sys

_bound = False


def _loaded(name: str):
    """The library of that name, when this process has loaded it (never loads one)."""
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    handle = k32.GetModuleHandleW(name)
    return ctypes.WinDLL(name, handle=handle) if handle else None


def _has_context(dll) -> bool:
    try:
        current = dll.wglGetCurrentContext
        current.restype = ctypes.c_void_p
        return bool(current())
    except Exception:
        return False


def _context_library(find=None):
    """The loaded OpenGL library with a current context, when that is not ``opengl32.dll``."""
    find = find or _loaded
    names = [os.getenv("QT_OPENGL_DLL") or "", "opengl32sw"]
    system = find("opengl32.dll")
    if system is not None and _has_context(system):
        return None                       # the driver's library: what PyOpenGL uses anyway
    for name in names:
        if not name:
            continue
        dll = find(name if name.lower().endswith(".dll") else name + ".dll")
        if dll is not None and _has_context(dll):
            return dll
    return None


def _rebind(platform, dll) -> None:
    """Point PyOpenGL's platform (not yet used for a call) at ``dll``."""
    p = platform.PLATFORM
    current = dll.wglGetCurrentContext
    current.restype = ctypes.c_void_p
    address = dll.wglGetProcAddress
    address.restype = ctypes.c_void_p
    # (lazy properties of the platform object: set = never looked up in opengl32.dll)
    p.GL = p.OpenGL = p.WGL = dll
    p.GetCurrentContext = p.CurrentContextIsValid = current
    p.getExtensionProcedure = address
    platform.GetCurrentContext = platform.CurrentContextIsValid = current


def gl():
    """``OpenGL.GL`` for the context that is current now (call with the widget's context current)."""
    global _bound
    if not _bound and sys.platform == "win32" and "OpenGL.GL" not in sys.modules:
        try:
            dll = _context_library()
            if dll is not None:
                from OpenGL import platform
                _rebind(platform, dll)
        except Exception:
            pass                          # as before: the driver's library
    _bound = True
    from OpenGL import GL
    return GL
