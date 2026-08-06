# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Utilities for exporting packaged MADA Tools documentation sources.

Wheels contain a generated ``mada_tools/_docs`` resource tree created from the
repository's top-level ``docs/``, ``configs/``, and ``mkdocs.yaml`` files at
build time. This module exposes that packaged MkDocs project to downstream
packages without assuming they have a MADA Tools source checkout available.
"""

from __future__ import annotations

import shutil
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]

# ``mada_tools/_docs`` is generated into the build tree by ``setup.py``.
_DOCS_RESOURCE_NAME = "_docs"


def export_docs(destination: PathLike) -> Path:
    """Copy the packaged documentation source tree to a destination directory.

    Args:
        destination: Directory that will receive the exported documentation
            project, including ``mkdocs.yaml`` and the ``docs/`` source tree.

    Returns:
        The resolved destination path.
    """
    destination_path = Path(destination).expanduser().resolve()
    docs_root = resources.files("mada_tools").joinpath(_DOCS_RESOURCE_NAME)

    if not docs_root.is_dir():
        raise FileNotFoundError("Packaged documentation resources were not found.")

    _copy_resource_tree(docs_root, destination_path)
    return destination_path


def _copy_resource_tree(source: Traversable, destination: Path) -> None:
    """Recursively copy an importlib resource tree to the filesystem.

    Args:
        source: Resource directory to copy from. The resource may come from an
            unpacked package or another importlib resource provider.
        destination: Filesystem directory that will receive the copied tree.
    """
    destination.mkdir(parents=True, exist_ok=True)

    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
            _copy_stat_if_path(child, target)
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(child, Path):
                shutil.copy2(child, target)
            else:
                target.write_bytes(child.read_bytes())

    _copy_stat_if_path(source, destination)


def _copy_stat_if_path(source: Traversable, destination: Path) -> None:
    """Copy filesystem metadata when the resource has a concrete path.

    Args:
        source: Resource whose metadata should be copied when it is backed by a
            local ``Path``.
        destination: Filesystem path that receives the metadata.
    """
    if isinstance(source, Path):
        shutil.copystat(source, destination, follow_symlinks=False)
