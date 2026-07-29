# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for packaging and exporting MADA Tools documentation resources."""

import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from importlib import metadata
from pathlib import Path

import pytest


@pytest.mark.unit
def test_export_docs_copies_packaged_docs_from_installed_wheel(tmp_path):
    """Verify a built wheel can export its packaged MkDocs project."""
    repo_root = Path(__file__).resolve().parents[2]
    wheel_path = _build_wheel(repo_root, tmp_path / "build-export-test")
    install_target = tmp_path / "installed-wheel"
    export_path = tmp_path / "exported-docs"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--target",
            str(install_target),
            str(wheel_path),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, " + json.dumps(str(install_target)) + "); "
            "from mada_tools.docs import export_docs; export_docs(" + json.dumps(str(export_path)) + ")",
        ],
        cwd=tmp_path,
        check=True,
    )

    assert (export_path / "mkdocs.yaml").is_file()
    assert (export_path / "configs" / "development.json").is_file()
    assert (export_path / "docs" / "index.md").is_file()
    assert (export_path / "docs" / "gen_ref_pages.py").is_file()
    assert (export_path / "docs" / "assets" / "images" / "avail-servers.png").is_file()


@pytest.mark.unit
def test_wheel_includes_packaged_docs(tmp_path):
    """Verify key documentation resources are present inside the wheel."""
    repo_root = Path(__file__).resolve().parents[2]
    wheel_path = _build_wheel(repo_root, tmp_path / "build-content-test")

    with zipfile.ZipFile(wheel_path) as wheel:
        wheel_files = set(wheel.namelist())

    assert "mada_tools/_docs/mkdocs.yaml" in wheel_files
    assert "mada_tools/_docs/configs/development.json" in wheel_files
    assert "mada_tools/_docs/docs/index.md" in wheel_files
    assert "mada_tools/_docs/docs/gen_ref_pages.py" in wheel_files
    assert "mada_tools/_docs/docs/assets/images/avail-servers.png" in wheel_files


def _build_wheel(repo_root: Path, workspace: Path) -> Path:
    """Build a wheel from a temporary source copy.

    The test uses ``--no-isolation`` so it does not depend on ``venv`` support
    in the test interpreter. Skip clearly when the active environment does not
    satisfy this project's build backend requirements.

    Args:
        repo_root: Repository root containing ``pyproject.toml``.
        workspace: Temporary workspace that receives the source copy, backend
            build directory, and generated wheel.

    Returns:
        Path to the built wheel.
    """
    _skip_if_no_isolation_build_backend_is_unavailable(repo_root)

    source_dir = workspace / "source"
    dist_dir = workspace / "dist"
    shutil.copytree(
        repo_root,
        source_dir,
        ignore=shutil.ignore_patterns(
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv*",
            "__pycache__",
            "*.egg-info",
            "*.pyc",
            "build",
            "dist",
            "public",
        ),
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(dist_dir),
        ],
        cwd=source_dir,
        check=True,
    )
    return next(dist_dir.glob("*.whl"))


def _skip_if_no_isolation_build_backend_is_unavailable(repo_root: Path) -> None:
    """Skip when the active environment cannot satisfy ``build-system.requires``.

    ``python -m build --no-isolation`` uses the current Python environment
    instead of creating an isolated build environment. This helper derives the
    required setuptools version from ``pyproject.toml`` so the test does not
    duplicate the project metadata.
    """
    required_setuptools = _required_setuptools_version(repo_root / "pyproject.toml")
    if required_setuptools is None:
        return

    try:
        installed_setuptools = metadata.version("setuptools")
    except metadata.PackageNotFoundError:
        pytest.skip(f"setuptools>={required_setuptools} is required for no-isolation wheel build tests")

    if _version_tuple(installed_setuptools) < _version_tuple(required_setuptools):
        pytest.skip(
            f"setuptools>={required_setuptools} is required for no-isolation wheel build tests; "
            f"found setuptools {installed_setuptools}"
        )


def _required_setuptools_version(pyproject_path: Path) -> str | None:
    """Return the minimum setuptools version declared by ``build-system.requires``."""
    pyproject = tomllib.loads(pyproject_path.read_text())
    for requirement in pyproject.get("build-system", {}).get("requires", []):
        match = re.fullmatch(r"setuptools\s*>=\s*([0-9][A-Za-z0-9.!+_-]*)", requirement)
        if match:
            return match.group(1)
    return None


def _version_tuple(version: str) -> tuple[int, ...]:
    """Return the numeric release prefix of a Python package version."""
    numeric_parts = []
    for part in version.split("."):
        match = re.match(r"\d+", part)
        if not match:
            break
        numeric_parts.append(int(match.group()))
    return tuple(numeric_parts)
