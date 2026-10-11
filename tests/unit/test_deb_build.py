import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import build_deb


def test_deb_python_dependency_matches_the_build_interpreter_minor_version():
    major = sys.version_info.major
    minor = sys.version_info.minor
    dependencies = build_deb._DEB_RUNTIME_DEPS

    assert f"python3 (>= {major}.{minor})" in dependencies
    assert f"python3 (<< {major}.{minor + 1})" in dependencies
    assert "python3" not in dependencies
