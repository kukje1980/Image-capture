"""Start the fundus viewer (also the PyInstaller entry script).

Usage:
    python run_viewer.py [--home DIR] [--demo]
"""
from fundusview.app import main

if __name__ == "__main__":
    raise SystemExit(main())
