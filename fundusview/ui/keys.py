"""Shortcut wording for the platform.

Qt maps the Ctrl modifier to ⌘ (Command) on macOS — shortcuts and
Ctrl+click already work there — so on-screen texts that name Ctrl say ⌘.
"""
from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"


def keys(text: str, mac: bool = IS_MAC) -> str:
    """``text`` with Ctrl+ written as ⌘ on macOS (unchanged elsewhere)."""
    return text.replace("Ctrl+", "⌘") if mac else text
