"""macos_bundle.py: the lowest macOS the Mac app runs on, read from the Mach-O libraries
inside it (Info.plist LSMinimumSystemVersion, the download page). Plain file reading,
so this runs on every platform with Mach-O files made here."""
import plistlib
import re
import struct
from pathlib import Path

import pytest

import macos_bundle as mb

ROOT = Path(__file__).resolve().parents[1]
ARM64, X86_64 = mb.CPU_TYPES["arm64"], mb.CPU_TYPES["x86_64"]


def _enc(v):
    x, y, z = (list(v) + [0, 0])[:3]
    return (x << 16) | (y << 8) | z


def thin(cpu, minos=None, old_style=None, platform=mb.PLATFORM_MACOS, endian="<", bits=64):
    """A minimal Mach-O image: a UUID command, then the version command(s)."""
    cmds = struct.pack(endian + "II", 0x1B, 24) + bytes(16)                 # LC_UUID
    n = 1
    if minos is not None:
        cmds += struct.pack(endian + "IIIIII", mb.LC_BUILD_VERSION, 24, platform, _enc(minos), _enc((26, 0)), 0)
        n += 1
    if old_style is not None:
        cmds += struct.pack(endian + "IIII", mb.LC_VERSION_MIN_MACOSX, 16, _enc(old_style), _enc((10, 15)))
        n += 1
    magic = mb.MH_MAGIC_64 if bits == 64 else mb.MH_MAGIC
    head = struct.pack(endian + "IiiIIII", magic, cpu, 0, 6, n, len(cmds), 0) + (bytes(4) if bits == 64 else b"")
    return head + cmds + bytes(64)


def fat(*slices, wide=False):
    """A universal binary with each slice at a 4 KiB boundary."""
    entry = 32 if wide else 20
    out = bytearray(struct.pack(">II", mb.FAT_MAGIC_64 if wide else mb.FAT_MAGIC, len(slices)))
    offset = 4096
    body = bytearray()
    for cpu, data in slices:
        if wide:
            out += struct.pack(">iiQQII", cpu, 0, offset, len(data), 12, 0)
        else:
            out += struct.pack(">iiIII", cpu, 0, offset, len(data), 12)
        pad = offset - (8 + entry * len(slices)) - len(body)
        body += bytes(pad) + data
        offset += 4096 * (1 + len(data) // 4096)
    return bytes(out + body)


@pytest.fixture
def write(tmp_path):
    def _write(rel, data):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    return _write


def test_thin_build_version(write):
    assert mb.macho_min_versions(write("a.dylib", thin(ARM64, (14, 4)))) == {ARM64: (14, 4, 0)}
    assert mb.macho_min_versions(write("b.so", thin(X86_64, old_style=(10, 13)))) == {X86_64: (10, 13, 0)}
    big = write("c.so", thin(X86_64, (12, 3, 1), endian=">", bits=32))
    assert mb.macho_min_versions(big) == {X86_64: (12, 3, 1)}


def test_build_version_for_another_platform_is_not_macos(write):
    ios = write("ios.dylib", thin(ARM64, (17, 0), platform=2))
    assert mb.macho_min_versions(ios) == {ARM64: None}
    assert mb.minimum_macos([ios], "arm64").version == mb.FLOOR


@pytest.mark.parametrize("wide", [False, True])
def test_universal_binary_per_architecture(write, wide):
    p = write("u.dylib", fat((X86_64, thin(X86_64, old_style=(10, 9))), (ARM64, thin(ARM64, (14, 4))), wide=wide))
    assert mb.macho_min_versions(p) == {X86_64: (10, 9, 0), ARM64: (14, 4, 0)}
    assert mb.minimum_macos([p], "arm64").version == (14, 4, 0)
    assert mb.minimum_macos([p], "x86_64").version == mb.FLOOR       # never below macOS 11


def test_not_mach_o(write):
    java = write("A.class", struct.pack(">IHH", 0xCAFEBABE, 0, 52) + bytes(64))   # same magic as fat
    assert mb.macho_min_versions(java) == {}
    assert mb.macho_min_versions(write("style.qss", b"QWidget { color: white; }")) == {}
    assert mb.macho_min_versions(write("empty", b"")) == {}
    assert mb.macho_min_versions(write("cut.dylib", thin(ARM64, (14, 0))[:20])) == {}
    assert mb.macho_min_versions(write("broken.dylib", fat((ARM64, b"\0" * 10)))) == {}


def test_bindings_labelled_with_the_build_machine_do_not_count(write):
    files = [
        write("Frameworks/PySide6/QtCore.abi3.so", thin(ARM64, (26, 0))),
        write("Frameworks/PySide6/libpyside6.abi3.6.12.dylib", thin(ARM64, (26, 0))),
        write("Frameworks/shiboken6/libshiboken6.abi3.6.12.dylib", thin(ARM64, (26, 0))),
        write("Frameworks/PySide6/Qt/lib/QtCore.framework/Versions/A/QtCore", thin(ARM64, (14, 4))),
        write("Frameworks/numpy/_core/_multiarray_umath.cpython-312-darwin.so", thin(ARM64, (14, 0))),
        write("Frameworks/fundusview/ui/style.qss", b"/* not a library */"),
    ]
    need = mb.minimum_macos(files, "arm64")
    assert need.version == (14, 4, 0)
    assert Path(need.file).parts[-4:] == ("QtCore.framework", "Versions", "A", "QtCore")
    assert need.ignored == (26, 0, 0)
    assert mb.label_only("PySide6/QtGui.abi3.so") and mb.label_only("x/shiboken6/Shiboken.abi3.so")
    assert not mb.label_only("PySide6/Qt/plugins/platforms/libqcocoa.dylib")
    assert not mb.label_only("cv2/cv2.abi3.so")


def test_a_real_need_above_the_bindings_counts(write):
    files = [write("PySide6/QtCore.abi3.so", thin(ARM64, (15, 0))),
             write("cv2/cv2.abi3.so", thin(ARM64, (15, 2)))]
    need = mb.minimum_macos(files, "arm64")
    assert need.version == (15, 2, 0) and need.file.endswith("cv2.abi3.so")


def test_version_texts():
    assert mb.version_text((14, 4, 0)) == "14.4"
    assert mb.version_text((11, 0, 0)) == "11.0"
    assert mb.version_text((10, 13, 2)) == "10.13.2"
    assert mb.parse_version("14.4") == (14, 4, 0) and mb.parse_version("11") == (11, 0, 0)
    assert mb.display_name((14, 4, 0)) == "macOS 14.4 Sonoma"
    assert mb.display_name((15, 0, 0)) == "macOS 15 Sequoia"
    assert mb.display_name((26, 1, 0)) == "macOS 26.1 Tahoe"
    assert mb.display_name((27, 0, 0)) == "macOS 27"


def _app(tmp_path, claimed, need):
    app = tmp_path / "FundusViewer.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "FundusViewer").write_bytes(thin(X86_64, (10, 13)))
    qt = app / "Contents" / "Frameworks" / "PySide6" / "Qt" / "lib" / "QtGui.framework" / "Versions" / "A"
    qt.mkdir(parents=True)
    (qt / "QtGui").write_bytes(fat((X86_64, thin(X86_64, need)), (ARM64, thin(ARM64, (26, 0)))))
    (app / "Contents" / "Frameworks" / "PySide6" / "QtGui.abi3.so").write_bytes(thin(X86_64, (26, 0)))
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleName": "FundusViewer", "LSMinimumSystemVersion": claimed}, f)
    return app


def test_check_app_fails_when_info_plist_claims_too_old(tmp_path, capsys):
    app = _app(tmp_path, "11.0", (14, 4))
    assert mb.check_app(app)[2] == "x86_64"              # from the app's own executable
    assert mb.main([str(app)]) == 1
    assert "needs macOS 14.4" in capsys.readouterr().err


def test_check_app_writes_the_version_for_the_download_page(tmp_path, capsys):
    app = _app(tmp_path, "14.4", (14, 4))
    notes = tmp_path / "mac-min-Intel.txt"
    assert mb.main([str(app), "--notes-out", str(notes)]) == 0
    assert notes.read_text(encoding="utf-8").strip() == "macOS 14.4 Sonoma"
    out = capsys.readouterr().out
    assert "(x86_64)" in out and "26.0" in out                    # the binding labels are reported


def test_only_windows_is_built_and_published_and_the_page_says_mac_stopped():
    """0.13.14: Windows only (the owner asked). The workflow no longer builds a Mac app or waits for one
    to publish, the download page has no Mac version left to fill in, and it says the Mac file there
    is the last one (0.13.13). build_mac.sh stays, to build on a Mac by hand."""
    workflow = (ROOT / ".github" / "workflows" / "fundus-viewer.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"^  ([\w-]+):\s*$", workflow.split("\njobs:\n", 1)[1], re.M)
    assert jobs == ["test-linux", "build-windows", "publish"]
    assert not re.search(r"runs-on:.*macos", workflow) and "macmin-" not in workflow
    assert re.search(r"needs:\s*\[build-windows\]", workflow)
    notes = (ROOT / "docs" / "release_notes.md").read_text(encoding="utf-8")
    assert "@MAC_MIN_" not in notes
    head = notes.split("### 버전", 1)[0]
    assert "0.13.13" in head and "새로 만들지 않습니다" in head
    script = (ROOT / "build_mac.sh").read_text(encoding="utf-8")
    assert 'DMG="dist/FundusViewer-mac-$LABEL.dmg"' in script
