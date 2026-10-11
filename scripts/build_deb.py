#!/usr/bin/env python3
"""Build a .deb package for UbDict.

Python runtime dependencies are bundled at build time so installation does not
depend on Python packages being available in a particular Ubuntu release.
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if sys.implementation.name != "cpython" or getattr(sys, "abiflags", ""):
    raise RuntimeError("Build Debian packages with standard CPython, not another ABI")
VERSION = "0.1.12"
PKG_NAME = "ubdict"
_DEB_ARCHES = {
    "x86_64": "amd64",
    "aarch64": "arm64",
    "armv7l": "armhf",
    "i686": "i386",
}
PKG_ARCH = _DEB_ARCHES.get(platform.machine())
if not PKG_ARCH:
    raise RuntimeError(f"Unsupported Debian package architecture: {platform.machine()}")
DEB_DIR = PROJECT_ROOT / "dist" / f"{PKG_NAME}_{VERSION}_{PKG_ARCH}"
DEB_PATH = PROJECT_ROOT / "dist" / f"{PKG_NAME}_{VERSION}_{PKG_ARCH}.deb"

_DEB_RUNTIME_DEPS = (
    f"python3 (>= {sys.version_info.major}.{sys.version_info.minor})",
    f"python3 (<< {sys.version_info.major}.{sys.version_info.minor + 1})",
    "python3-pyqt6",
    "python3-pyqt6.qtmultimedia",
    "libxcb-cursor0",
    "xclip",
    "wl-clipboard",
    "grim",
    "tesseract-ocr",
    "tesseract-ocr-eng",
    "espeak-ng",
    "gstreamer1.0-plugins-ugly",
)

_PYTHON_VENDOR_DEPS = (
    "pytesseract>=0.3.10",
    "PyMuPDF>=1.23",
    "mss>=9.0",
    "python-xlib>=0.33",
    "httpx>=0.27",
    "pydantic>=2.0",
    "loguru>=0.7",
    "selectolax>=0.3",
    "tomli_w>=1.0",
    'tomli>=2.0; python_version < "3.11"',
)

_ICON_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" '
    'viewBox="0 0 128 128">\n'
    '  <rect width="128" height="128" rx="16" fill="#2563eb"/>\n'
    '  <text x="64" y="86" font-family="serif" font-size="72" '
    'font-weight="bold" text-anchor="middle" fill="white">U</text>\n'
    '</svg>\n'
)

_MAN_PAGE = (
    f'.TH UBDICT 1 "{time.strftime("%Y-%m-%d")}" "ubdict {VERSION}" '
    '"User Commands"\n'
    ".SH NAME\n"
    "ubdict \\- Intelligent English-Chinese dictionary for Ubuntu\n"
    ".SH SYNOPSIS\n"
    ".B ubdict\n"
    ".RI [ OPTIONS ]\n"
    ".SH DESCRIPTION\n"
    "UbDict is a desktop dictionary that supports text-selection capture, "
    "image OCR, and PDF word lookup. It queries Bing dictionary online and "
    "falls back to a local ECDICT database when offline.\n"
    ".SH FILES\n"
    ".TP\n"
    ".I ~/.config/ubdict/config.toml\n"
    "User configuration.\n"
    ".TP\n"
    ".I ~/.local/share/ubdict/logs/ubdict.log\n"
    "Rotating log file.\n"
    ".SH SEE ALSO\n"
    ".BR tesseract (1)\n"
    ".SH AUTHOR\n"
    "UbDict project.\n"
)


def _control_text(installed_kb: int) -> str:
    deps = ", ".join(_DEB_RUNTIME_DEPS)
    return (
        f"Package: {PKG_NAME}\n"
        f"Version: {VERSION}\n"
        f"Architecture: {PKG_ARCH}\n"
        "Maintainer: UbDict <ubdict@example.com>\n"
        f"Installed-Size: {installed_kb}\n"
        "Section: utils\n"
        "Priority: optional\n"
        "Homepage: https://example.com/ubdict\n"
        f"Depends: {deps}\n"
        "Description: Intelligent English-Chinese dictionary for Ubuntu\n"
        " UbDict supports text selection, image OCR, and PDF word capture\n"
        " with Bing dictionary and local ECDICT fallback.\n"
    )


def _validate_ecdict(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"Offline dictionary not found: {path}. "
            "Build the ECDICT database before packaging."
        )
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise ValueError(f"SQLite integrity check failed for {path}: {check}")
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ecdict)").fetchall()
            }
            required = {"word", "phonetic", "definition", "translation"}
            if not required.issubset(columns):
                raise ValueError(
                    f"Invalid ECDICT schema in {path}; missing "
                    f"{', '.join(sorted(required - columns))}"
                )
            if conn.execute("SELECT COUNT(*) FROM ecdict").fetchone()[0] == 0:
                raise ValueError(f"Offline dictionary is empty: {path}")
    except sqlite3.Error as exc:
        raise ValueError(f"Unable to validate ECDICT database {path}: {exc}") from exc


_PRERM = (
    "#!/bin/sh\n"
    "set -e\n"
    "if [ -d /usr/share/ubdict ]; then\n"
    "  find /usr/share/ubdict -maxdepth 2 -type d -name '__pycache__' -prune -exec rm -rf {} +\n"
    "fi\n"
)


def _assemble_tree() -> int:
    """Assemble the package filesystem tree under DEB_DIR; return installed KB."""
    ecdict_db = PROJECT_ROOT / "config" / "ecdict.db"
    _validate_ecdict(ecdict_db)
    if DEB_DIR.exists():
        shutil.rmtree(DEB_DIR)
    for d in [
        "usr/bin",
        "usr/share/ubdict",
        "usr/share/applications",
        "usr/share/icons/hicolor/scalable/apps",
        "usr/share/man/man1",
        "DEBIAN",
    ]:
        (DEB_DIR / d).mkdir(parents=True, exist_ok=True)

    wrapper = DEB_DIR / "usr/bin/ubdict"
    wrapper.write_text(
        "#!/bin/sh\n"
        'PYTHONPATH=/usr/share/ubdict/vendor:/usr/share/ubdict '
        'exec /usr/bin/python3 -m ubdict.main "$@"\n'
    )
    wrapper.chmod(0o755)

    src = PROJECT_ROOT / "src" / "ubdict"
    dst = DEB_DIR / "usr/share/ubdict" / "ubdict"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))

    vendor_dir = DEB_DIR / "usr/share/ubdict/vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--target",
            str(vendor_dir),
            *_PYTHON_VENDOR_DEPS,
        ],
        check=True,
    )
    for cache_dir in vendor_dir.rglob("__pycache__"):
        shutil.rmtree(cache_dir)
    for bytecode in vendor_dir.rglob("*.pyc"):
        bytecode.unlink()

    config_src = PROJECT_ROOT / "config"
    if config_src.exists():
        config_dst = DEB_DIR / "usr/share/ubdict" / "config"
        shutil.copytree(
            config_src,
            config_dst,
            ignore=shutil.ignore_patterns("stardict.*"),
        )

    desktop_src = PROJECT_ROOT / "assets" / "ubdict.desktop"
    if desktop_src.exists():
        shutil.copy(desktop_src, DEB_DIR / "usr/share/applications/ubdict.desktop")

    (DEB_DIR / "usr/share/icons/hicolor/scalable/apps/ubdict.svg").write_text(
        _ICON_SVG
    )
    (DEB_DIR / "usr/share/man/man1/ubdict.1").write_text(_MAN_PAGE)

    total = sum(f.stat().st_size for f in DEB_DIR.rglob("*") if f.is_file())
    installed_kb = total // 1024

    (DEB_DIR / "DEBIAN/control").write_text(_control_text(installed_kb))
    prerm = DEB_DIR / "DEBIAN/prerm"
    prerm.write_text(_PRERM)
    prerm.chmod(0o755)
    return installed_kb


def _build_with_dpkg_deb() -> int:
    result = subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(DEB_DIR), str(DEB_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"dpkg-deb failed: {result.stderr}")
        return 1
    print(f"Built (dpkg-deb): {DEB_PATH} ({DEB_PATH.stat().st_size // 1024} KB)")
    return 0


def _is_executable(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("DEBIAN/") and name in ("postinst", "prerm", "preinst", "postrm"):
        return True
    if rel.startswith("usr/bin/"):
        return True
    return False


def _add_tree_to_tar(tf: tarfile.TarFile, root: Path, sub: str) -> None:
    """Add all entries under root/sub into tar with arcname prefixed by './'."""
    base = root / sub
    if not base.exists():
        return
    all_paths: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(base):
        all_paths.append(Path(dirpath))
        for fn in filenames:
            all_paths.append(Path(dirpath) / fn)
    all_paths.sort()
    now = int(time.time())
    for p in all_paths:
        rel = p.relative_to(root)
        arcname = "./" + str(rel).replace("\\", "/")
        ti = tf.gettarinfo(str(p), arcname=arcname)
        ti.mtime = now
        ti.uid = 0
        ti.gid = 0
        ti.uname = "root"
        ti.gname = "root"
        if p.is_dir():
            ti.type = tarfile.DIRTYPE
            ti.size = 0
            ti.mode = 0o755
            tf.addfile(ti)
        else:
            ti.mode = 0o755 if _is_executable(str(rel)) else 0o644
            with open(p, "rb") as f:
                tf.addfile(ti, f)


def _write_ar_member(buf: io.BytesIO, name: str, data: bytes) -> None:
    header = (
        f"{name:<16}"
        f"{int(time.time()):<12}"
        f"{'0':<6}"
        f"{'0':<6}"
        f"{'100644':<8}"
        f"{len(data):<10}"
    ).encode("ascii") + b"`\n"
    buf.write(header)
    buf.write(data)
    if len(data) % 2 == 1:
        buf.write(b"\n")


def _build_pure_python_deb() -> int:
    ctrl_buf = io.BytesIO()
    with tarfile.open(
        fileobj=ctrl_buf, mode="w:gz", format=tarfile.GNU_FORMAT
    ) as tf:
        _add_tree_to_tar(tf, DEB_DIR, "DEBIAN")
    control_tgz = ctrl_buf.getvalue()

    data_buf = io.BytesIO()
    with tarfile.open(
        fileobj=data_buf, mode="w:gz", format=tarfile.GNU_FORMAT
    ) as tf:
        _add_tree_to_tar(tf, DEB_DIR, "usr")
    data_tgz = data_buf.getvalue()

    ar_buf = io.BytesIO()
    ar_buf.write(b"!<arch>\n")
    _write_ar_member(ar_buf, "debian-binary", b"2.0\n")
    _write_ar_member(ar_buf, "control.tar.gz", control_tgz)
    _write_ar_member(ar_buf, "data.tar.gz", data_tgz)

    DEB_PATH.write_bytes(ar_buf.getvalue())
    print(
        f"Built (pure-python): {DEB_PATH} "
        f"({DEB_PATH.stat().st_size // 1024} KB)"
    )
    return 0


def main() -> int:
    print(f"Building {PKG_NAME} v{VERSION} .deb package...")
    try:
        installed_kb = _assemble_tree()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Package input validation failed: {exc}")
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            "Failed to bundle Python dependencies. Ensure pip is available and "
            f"the build machine can reach PyPI (exit code {exc.returncode})."
        )
        return 1
    print(f"Installed-Size: {installed_kb} KB")
    if shutil.which("dpkg-deb"):
        return _build_with_dpkg_deb()
    print("dpkg-deb not found; using pure-Python fallback.")
    return _build_pure_python_deb()


if __name__ == "__main__":
    raise SystemExit(main())
