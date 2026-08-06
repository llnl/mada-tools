# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Setuptools build hooks for staging documentation package resources.

The repository keeps a single editable docs source tree at the project root.
During package builds, this module copies that source into
``mada_tools/_docs`` inside the build directory so wheels expose a stable
resource tree for ``mada_tools.docs.export_docs()``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    """Stage docs resources into the package build tree."""

    def run(self) -> None:
        """Build Python modules, then copy docs resources into the build tree."""
        super().run()
        self._copy_docs_resources()

    def _copy_docs_resources(self) -> None:
        """Copy the MkDocs project files into ``mada_tools/_docs``.

        The generated resource tree includes ``mkdocs.yaml``, the ``docs/``
        source directory, and ``configs/`` fragments referenced by Markdown
        snippets. Existing staged resources are removed first so repeated local
        builds cannot leave stale files behind.
        """
        project_root = Path(__file__).parent.resolve()
        destination = Path(self.build_lib) / "mada_tools" / "_docs"

        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)

        shutil.copy2(project_root / "mkdocs.yaml", destination / "mkdocs.yaml")
        shutil.copytree(project_root / "docs", destination / "docs")
        shutil.copytree(project_root / "configs", destination / "configs")


setup(cmdclass={"build_py": build_py})
