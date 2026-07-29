# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for packaging and exporting MADA Tools documentation resources."""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.mark.unit
def test_export_docs_copies_packaged_docs_from_installed_wheel(tmp_path):
    """Verify a built wheel can export its packaged MkDocs project."""
    repo_root = Path(__file__).resolve().parents[2]
    wheel_path = _build_wheel(repo_root, tmp_path / "build-export-test")
    venv_path = tmp_path / "venv"
    export_path = tmp_path / "exported-docs"

    subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
    python = _venv_python(venv_path)
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel_path)], check=True)
    subprocess.run(
        [
            str(python),
            "-c",
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

    Args:
        repo_root: Repository root containing ``pyproject.toml``.
        workspace: Temporary workspace that receives the source copy, backend
            build directory, and generated wheel.

    Returns:
        Path to the built wheel.
    """
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
            "--outdir",
            str(dist_dir),
        ],
        cwd=source_dir,
        check=True,
    )
    return next(dist_dir.glob("*.whl"))


def _venv_python(venv_path: Path) -> Path:
    """Return the Python executable path for a virtual environment."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"
