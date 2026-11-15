"""The lowest macOS the Mac app can start on, read from the libraries inside it.

Every Mach-O library records the macOS version it was built for (LC_BUILD_VERSION, or
LC_VERSION_MIN_MACOSX in older ones), and the app needs the highest of them. Qt 6.12
(PySide6 6.12), for instance, is built for macOS 14.4, so the app cannot run on macOS 13
even though our own code would. fundus_viewer.spec writes that version into Info.plist
(LSMinimumSystemVersion): an older Mac then says the app needs a newer macOS instead of
starting it and having it quit. build_mac.sh checks the finished app with

    python macos_bundle.py dist/FundusViewer.app [--notes-out FILE]

which fails when a library in the bundle needs a newer macOS than Info.plist says, and
writes the version (e.g. "macOS 14.4 Sonoma") for the download page.

PySide6's and shiboken6's own binding modules (PySide6/QtCore.abi3.so, libpyside6…,
shiboken6/…; not Qt itself under PySide6/Qt/) are built without a deployment target, so
they record the macOS of the machine that built the wheel (PySide6 6.11: 15.0, 6.12:
26.0) although the wheels are made for macOS 13 / 14 and import nothing newer from the
system. Those labels are reported but do not count.

Plain file reading: runs (and is tested) on every platform.
"""
from __future__ import annotations

import argparse
import os
import platform
import plistlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

FLOOR = (11, 0, 0)              # never claim less than macOS 11 (Big Sur)

CPU_TYPES = {"x86_64": 0x01000007, "arm64": 0x0100000C}
LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
PLATFORM_MACOS = 1
MH_MAGIC = 0xFEEDFACE
MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
LABEL_ONLY_PACKAGES = ("PySide6", "shiboken6")

NAMES = {11: "Big Sur", 12: "Monterey", 13: "Ventura", 14: "Sonoma", 15: "Sequoia", 26: "Tahoe"}

Version = tuple[int, int, int]


def _version(v: int) -> Version:
    return (v >> 16, (v >> 8) & 0xFF, v & 0xFF)


def _slice_min(f, offset: int) -> tuple[int, Version | None] | None:
    """(cputype, minimum macOS) of the thin Mach-O image at ``offset``; None if it is not one."""
    f.seek(offset)
    head = f.read(32)
    if len(head) < 28:
        return None
    if struct.unpack_from("<I", head)[0] in (MH_MAGIC, MH_MAGIC_64):
        e = "<"
    elif struct.unpack_from(">I", head)[0] in (MH_MAGIC, MH_MAGIC_64):
        e = ">"
    else:
        return None
    magic, cputype, _sub, _ftype, ncmds, sizeofcmds = struct.unpack_from(e + "IiiIII", head)
    f.seek(offset + (32 if magic == MH_MAGIC_64 else 28))
    cmds = f.read(sizeofcmds)
    found: Version | None = None
    p = 0
    for _ in range(ncmds):
        if p + 12 > len(cmds):
            break
        cmd, size = struct.unpack_from(e + "II", cmds, p)
        if cmd == LC_BUILD_VERSION:
            plat, minos = struct.unpack_from(e + "II", cmds, p + 8)
            if plat == PLATFORM_MACOS:
                found = _version(minos)
        elif cmd == LC_VERSION_MIN_MACOSX and found is None:
            found = _version(struct.unpack_from(e + "I", cmds, p + 8)[0])
        if size < 8:
            break
        p += size
    return cputype & 0xFFFFFFFF, found


def macho_min_versions(path: str | os.PathLike) -> dict[int, Version | None]:
    """{cputype: minimum macOS} for every slice of a Mach-O file ({} if it is not Mach-O)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return {}
            magic, nfat = struct.unpack(">II", head)
            if magic in (FAT_MAGIC, FAT_MAGIC_64):
                if not 0 < nfat < 30:       # 0xCAFEBABE also starts Java class files
                    return {}
                wide = magic == FAT_MAGIC_64
                entry = 32 if wide else 20
                table = f.read(nfat * entry)
                if len(table) < nfat * entry:
                    return {}
                out: dict[int, Version | None] = {}
                for i in range(nfat):
                    fmt = ">iiQQ" if wide else ">iiII"
                    _cpu, _sub, offset, _size = struct.unpack_from(fmt, table, i * entry)
                    r = _slice_min(f, offset)
                    if r is not None:
                        out[r[0]] = r[1]
                return out
            r = _slice_min(f, 0)
            return {} if r is None else {r[0]: r[1]}
    except OSError:
        return {}


def label_only(path: str | os.PathLike) -> bool:
    """A PySide6 / shiboken6 binding module (its macOS label is the wheel builder's, see above)."""
    parts = Path(path).parts
    for i, part in enumerate(parts):
        if part in LABEL_ONLY_PACKAGES:
            return "Qt" not in parts[i + 1:]
    return False


@dataclass
class Need:
    version: Version = FLOOR      # what the app needs (never below FLOOR)
    file: str | None = None       # the library that needs it (None: the floor)
    ignored: Version | None = None  # the highest label among the binding modules (not counted)


def minimum_macos(paths, arch: str | None = None) -> Need:
    """The highest minimum macOS among ``paths`` for ``arch`` (default: this machine's).

    Slices for other architectures are ignored (an Intel app never loads the arm64 half
    of a universal library); files that are not Mach-O are skipped."""
    cpu = CPU_TYPES[arch or platform.machine()]
    need = Need()
    for p in paths:
        v = macho_min_versions(p).get(cpu)
        if v is None:
            continue
        if label_only(p):
            if need.ignored is None or v > need.ignored:
                need.ignored = v
        elif v > need.version:
            need.version, need.file = v, str(p)
    return need


def bundle_files(app: str | os.PathLike):
    """Every regular file inside an .app (symlinks — framework aliases — are skipped)."""
    for root, _dirs, files in os.walk(app):
        for name in files:
            p = Path(root) / name
            if not p.is_symlink():
                yield p


def version_text(v: Version) -> str:
    """(14, 4, 0) → "14.4" (the form Info.plist uses)."""
    return f"{v[0]}.{v[1]}" + (f".{v[2]}" if v[2] else "")


def parse_version(text: str) -> Version:
    parts = [int(x) for x in str(text).split(".")[:3] if x.isdigit()]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def display_name(v: Version) -> str:
    """(14, 4, 0) → "macOS 14.4 Sonoma", (15, 0, 0) → "macOS 15 Sequoia" (for the download page)."""
    num = str(v[0]) if v[1:] == (0, 0) else version_text(v)
    name = NAMES.get(v[0])
    return f"macOS {num} {name}" if name else f"macOS {num}"


def app_arch(app: Path) -> str:
    """The architecture of the app's own executable (what the Mac runs)."""
    cpus = macho_min_versions(app / "Contents" / "MacOS" / app.stem)
    for arch, cpu in CPU_TYPES.items():
        if set(cpus) == {cpu}:
            return arch
    return platform.machine()


def check_app(app: Path) -> tuple[Version, Need, str]:
    """(Info.plist's LSMinimumSystemVersion, what the libraries need, the app's architecture)."""
    with open(app / "Contents" / "Info.plist", "rb") as f:
        claimed = parse_version(plistlib.load(f).get("LSMinimumSystemVersion", "0"))
    arch = app_arch(app)
    return claimed, minimum_macos(bundle_files(app), arch), arch


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check the lowest macOS a built .app can run on.")
    ap.add_argument("app", help="the built .app")
    ap.add_argument("--notes-out", help="write e.g. 'macOS 14.4 Sonoma' to this file")
    args = ap.parse_args(argv)
    app = Path(args.app)
    claimed, need, arch = check_app(app)
    print(f"{app.name} ({arch}): Info.plist LSMinimumSystemVersion {version_text(claimed)}")
    print(f"libraries need {display_name(need.version)}"
          + (f" ({Path(need.file).relative_to(app)})" if need.file else " (floor)"))
    if need.ignored:
        print(f"PySide6/shiboken6 binding modules say {version_text(need.ignored)}: the wheel builder's macOS, "
              "not counted")
    if args.notes_out:
        Path(args.notes_out).write_text(display_name(max(claimed, need.version)) + "\n", encoding="utf-8")
    if need.version > claimed:
        print(f"error: {need.file} needs macOS {version_text(need.version)} but Info.plist says "
              f"{version_text(claimed)}: an older Mac would start the app and it would quit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
