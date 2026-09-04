# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Utilities for exporting packaged MADA Tools documentation sources.

Wheels contain a generated ``mada_tools/_docs`` resource tree created from the
repository's top-level ``docs/``, ``configs/``, and ``mkdocs.yaml`` files at
build time. This module exposes that packaged MkDocs project to downstream
packages without assuming they have a MADA Tools source checkout available.
"""

from __future__ import annotations

import copy
import shutil
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Iterable, Mapping, Union

import yaml

PathLike = Union[str, Path]

# ``mada_tools/_docs`` is generated into the build tree by ``setup.py``.
_DOCS_RESOURCE_NAME = "_docs"


@dataclass(frozen=True)
class ApiReferenceMapping:
    """Configuration for generating mkdocstrings reference pages for a package."""

    package_name: str
    api_reference_path: Path = Path("developer_guide")
    source_path: Path | None = None
    ignore_patterns: tuple[Path, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PluginDocsConfig:
    """Resolved configuration for staging a combined core/plugin docs site.

    Defaults used by `load_plugin_docs_config()`:
    - `project_root`: the directory containing `plugin_docs.yaml`
    - `generated_root`: `project_root / ".generated_docs"`
    - `plugin_docs_dir`: `project_root / "docs"`

    Plugin docs are staged by copying the contents of `plugin_docs_dir` into
    `generated_root / "docs"`. This replaces separate file and directory
    mappings because files and directories can be handled uniformly as one docs
    tree. Plugin-owned files and directories should therefore be named so they
    do not collide with the exported core docs tree.
    """

    config_path: Path
    project_root: Path
    generated_root: Path
    plugin_docs_dir: Path
    extensions: Mapping[str, Any] = field(default_factory=dict)

    @property
    def staged_mkdocs_config(self) -> Path:
        """Return the MkDocs config copied into the generated docs project.

        `build` and `serve` use this path, not the source config, so MkDocs runs
        from the self-contained staged tree that contains both exported core
        docs and copied plugin docs.
        """
        return self.generated_root / "mkdocs.yaml"


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


def load_plugin_docs_config(config_path: PathLike) -> PluginDocsConfig:
    """Load and resolve a plugin docs staging configuration file.

    Relative `project_root` is resolved against the config file directory.
    Relative `generated_root` and `plugin_docs_dir` paths are
    then resolved against that project root because they point to files and
    directories in the plugin repository. The destination is fixed as the staged
    MkDocs `docs/` directory, so there is no separate target path to resolve.

    Args:
        config_path: Path to a YAML plugin docs configuration file.

    Returns:
        Resolved plugin docs configuration.
    """
    resolved_config_path = Path(config_path).expanduser().resolve()
    with resolved_config_path.open("r", encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file) or {}

    if not isinstance(raw_config, dict):
        raise ValueError(f"Plugin docs config must be a YAML mapping: {resolved_config_path}")

    project_root = _resolve_path(
        raw_config.get("project_root", "."),
        base=resolved_config_path.parent,
    )

    _validate_plugin_extension_config(raw_config)
    return PluginDocsConfig(
        config_path=resolved_config_path,
        project_root=project_root,
        generated_root=_resolve_path(raw_config.get("generated_root", ".generated_docs"), base=project_root),
        plugin_docs_dir=_resolve_path(raw_config.get("plugin_docs_dir", "docs"), base=project_root),
        extensions={
            key: copy.deepcopy(value)
            for key, value in raw_config.items()
            if key not in {"project_root", "generated_root", "plugin_docs_dir"}
        },
    )


def prepare_plugin_docs_site(
    config: PluginDocsConfig | PathLike,
    *,
    clean: bool = True,
) -> Path:
    """Stage a combined core/plugin MkDocs source tree.

    Args:
        config: Resolved plugin docs configuration or path to a configuration file.
        clean: Whether to remove the existing generated root before staging.

    Returns:
        The generated docs root.
    """
    resolved_config = load_plugin_docs_config(config) if not isinstance(config, PluginDocsConfig) else config

    if clean:
        clean_plugin_docs(resolved_config)
    _validate_plugin_docs_config(resolved_config)
    resolved_config.generated_root.mkdir(parents=True, exist_ok=True)

    export_docs(resolved_config.generated_root)
    _write_staged_mkdocs_config(resolved_config)
    _copy_plugin_docs_dir(resolved_config)

    return resolved_config.generated_root


def build_plugin_docs(config_path: PathLike, *mkdocs_args: str) -> subprocess.CompletedProcess:
    """Stage and build a combined core/plugin docs site with MkDocs.

    This calls `prepare_plugin_docs_site()` before invoking `mkdocs build`, so
    callers do not need to prepare the generated docs tree separately.

    Args:
        config_path: Path to a plugin docs configuration file.
        *mkdocs_args: Extra arguments forwarded to `mkdocs build`.
    """
    config = load_plugin_docs_config(config_path)
    prepare_plugin_docs_site(config)
    return _run_mkdocs(config, "build", *mkdocs_args)


def serve_plugin_docs(config_path: PathLike, *mkdocs_args: str) -> subprocess.CompletedProcess:
    """Stage and serve a combined core/plugin docs site with MkDocs.

    This calls `prepare_plugin_docs_site()` before invoking `mkdocs serve`, so
    callers do not need to prepare the generated docs tree separately.

    Args:
        config_path: Path to a plugin docs configuration file.
        *mkdocs_args: Extra arguments forwarded to `mkdocs serve`.
    """
    config = load_plugin_docs_config(config_path)
    prepare_plugin_docs_site(config)
    return _run_mkdocs(config, "serve", *mkdocs_args)


def clean_plugin_docs(config: PluginDocsConfig | PathLike) -> Path:
    """Remove the configured generated docs directory if it exists.

    Args:
        config: Resolved plugin docs config or path to a config file.

    Returns:
        The generated docs root that was removed or found absent.
    """
    resolved_config = load_plugin_docs_config(config) if not isinstance(config, PluginDocsConfig) else config

    _validate_plugin_docs_config(resolved_config)

    if resolved_config.generated_root.exists():
        shutil.rmtree(resolved_config.generated_root)

    return resolved_config.generated_root


def generate_api_reference_pages(api_reference_mappings: Iterable[ApiReferenceMapping]) -> None:
    """Generate mkdocstrings reference pages for one or more packages.

    This helper is intended for MkDocs ``gen-files`` scripts in plugin
    repositories. The caller supplies package mappings, and this function
    handles package discovery, ``__init__``/``__main__`` conventions, literate
    navigation, and edit-path registration.
    """
    import importlib.util

    try:
        import mkdocs_gen_files
    except ImportError as exc:
        raise RuntimeError(
            "mkdocs-gen-files is required to generate API reference pages. "
            "Install MADA Tools with the docs extra, for example `pip install 'mada_tools[docs]'`."
        ) from exc

    for mapping in api_reference_mappings:
        nav = mkdocs_gen_files.Nav()
        package_spec = importlib.util.find_spec(mapping.package_name)
        if package_spec is None or package_spec.submodule_search_locations is None:
            raise RuntimeError(f"Unable to find installed package {mapping.package_name!r}.")

        top_level_module = Path(next(iter(package_spec.submodule_search_locations))).resolve()
        api_reference_path = Path(mapping.api_reference_path)

        for path in sorted(top_level_module.rglob("*.py")):
            relative_path = path.relative_to(top_level_module)
            if _should_ignore_api_path(relative_path, mapping.ignore_patterns):
                continue

            module_path = relative_path.with_suffix("")
            doc_path = relative_path.with_suffix(".md")
            full_doc_path = api_reference_path / doc_path
            parts = list(module_path.parts)

            if parts[-1] == "__init__":
                parts = parts[:-1]
                doc_path = doc_path.with_name("index.md")
                full_doc_path = full_doc_path.with_name("index.md")
                if not parts:
                    continue
            elif parts[-1] == "__main__":
                continue

            nav[parts] = doc_path.as_posix()
            with mkdocs_gen_files.open(full_doc_path, "w") as doc_file:
                identifier = ".".join([mapping.package_name, *parts])
                print("::: " + identifier, file=doc_file)

            mkdocs_gen_files.set_edit_path(
                full_doc_path,
                _api_edit_path(mapping) / relative_path,
            )

        with mkdocs_gen_files.open(api_reference_path / "SUMMARY.md", "w") as nav_file:
            nav_file.writelines(nav.build_literate_nav())


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
            local `Path`.
        destination: Filesystem path that receives the metadata.
    """
    if isinstance(source, Path):
        shutil.copystat(source, destination, follow_symlinks=False)


def _resolve_path(path: PathLike, *, base: Path) -> Path:
    """Resolve a possibly relative path against `base`."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


class _TaggedScalar(str):
    """String value that retains a YAML tag while configs are merged.

    The core MkDocs config uses `!!python/name` tags for Material's emoji
    extensions. Keeping the tag on a string lets PyYAML safely load, copy, and
    write the config without importing arbitrary Python objects.
    """

    def __new__(cls, value: str, tag: str):
        result = super().__new__(cls, value)
        result.yaml_tag = tag
        return result

    def __getnewargs__(self):
        """Give `deepcopy` both constructor arguments."""
        return str(self), self.yaml_tag

    @classmethod
    def from_yaml(cls, loader, _tag_suffix, node):
        """Load an otherwise unsupported YAML tag as a preserved string."""
        return cls(loader.construct_scalar(node), node.tag)

    @classmethod
    def to_yaml(cls, dumper, value):
        """Emit the YAML tag retained by a ``_TaggedScalar`` value."""
        return dumper.represent_scalar(value.yaml_tag, str(value))


class _MkdocsLoader(yaml.SafeLoader):
    """Safe loader isolated for MkDocs YAML tag handling.

    The core config uses `!!python/name` tags for Material extensions.
    Registering the handler on this subclass lets us preserve those tags
    without changing PyYAML's process-wide `SafeLoader` behavior.
    """


class _MkdocsDumper(yaml.SafeDumper):
    """Safe dumper isolated for writing preserved MkDocs YAML tags.

    This subclass keeps the custom `_TaggedScalar` representer local to
    staged MkDocs configs instead of changing PyYAML's process-wide
    `SafeDumper` behavior.
    """


_MkdocsLoader.add_multi_constructor("tag:yaml.org,2002:python/name:", _TaggedScalar.from_yaml)
_MkdocsDumper.add_representer(_TaggedScalar, _TaggedScalar.to_yaml)


_SUPPORTED_PLUGIN_FIELDS = {"nav", "gen_files", "extra", "site_name"}


def _validate_plugin_extension_config(raw_config: Mapping[str, Any]) -> None:
    """Validate the intentionally limited plugin MkDocs extension schema."""

    # Keep the plugin contract deliberately small. Plugins contribute to the
    # shared config instead of replacing core MkDocs behavior.
    unsupported = set(raw_config) - {
        "project_root",
        "generated_root",
        "plugin_docs_dir",
        *_SUPPORTED_PLUGIN_FIELDS,
    }

    if unsupported:
        raise ValueError(f"Unsupported plugin docs config fields: {', '.join(sorted(unsupported))}")

    # Navigation is copied directly into the core nav, so it must have the
    # list shape expected by MkDocs.
    if "nav" in raw_config and not isinstance(raw_config["nav"], list):
        raise ValueError("plugin docs 'nav' must be a list")

    # Only script contributions are supported under gen_files. Each script is
    # staged below docs/ and must therefore be a string path.
    gen_files = raw_config.get("gen_files", {})
    if not isinstance(gen_files, dict) or set(gen_files) - {"scripts"}:
        raise ValueError("plugin docs 'gen_files' must contain only 'scripts'")
    if "scripts" in gen_files and (
        not isinstance(gen_files["scripts"], list) or not all(isinstance(item, str) for item in gen_files["scripts"])
    ):
        raise ValueError("plugin docs 'gen_files.scripts' must be a list of strings")

    # Social links are appended to the core list. Other extra MkDocs settings
    # are intentionally rejected in this first schema version.
    extra = raw_config.get("extra", {})
    if not isinstance(extra, dict) or set(extra) - {"social"}:
        raise ValueError("plugin docs 'extra' must contain only 'social'")
    if "social" in extra and (
        not isinstance(extra["social"], list) or not all(isinstance(item, dict) for item in extra["social"])
    ):
        raise ValueError("plugin docs 'extra.social' must be a list of mappings")

    if "site_name" in raw_config and not isinstance(raw_config["site_name"], str):
        raise ValueError("plugin docs 'site_name' must be a string")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a MkDocs YAML mapping while preserving supported custom tags."""
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.load(stream, Loader=_MkdocsLoader) or {}
    if not isinstance(value, dict):
        raise ValueError(f"MkDocs config must be a YAML mapping: {path}")
    return value


def merge_mkdocs_config(core_config: Mapping[str, Any], plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a combined MkDocs config without mutating either input.

    Plugin documentation extends the packaged core site rather than defining
    a second MkDocs project. Core settings are preserved, while supported
    plugin contributions are applied as follows:

    * `site_name` replaces the core title when supplied.
    * `nav` entries are appended after the core navigation.
    * `gen_files.scripts` are appended to the core `gen-files` plugin.
    * `extra.social` entries are appended to the core social links.

    Unsupported fields are rejected before the merge occurs.
    """

    _validate_plugin_extension_config(plugin_config)
    merged = copy.deepcopy(dict(core_config))

    if "site_name" in plugin_config:
        merged["site_name"] = plugin_config["site_name"]

    if "nav" in plugin_config:
        merged.setdefault("nav", []).extend(copy.deepcopy(plugin_config["nav"]))

    scripts = plugin_config.get("gen_files", {}).get("scripts", [])

    if scripts:
        plugins = merged.setdefault("plugins", [])
        gen_files = next((item for item in plugins if isinstance(item, dict) and "gen-files" in item), None)

        if gen_files is None:
            gen_files = {"gen-files": {"scripts": []}}
            plugins.append(gen_files)

        gen_files["gen-files"].setdefault("scripts", []).extend(copy.deepcopy(scripts))

    social = plugin_config.get("extra", {}).get("social", [])

    if social:
        merged.setdefault("extra", {}).setdefault("social", []).extend(copy.deepcopy(social))

    return merged


def _write_staged_mkdocs_config(config: PluginDocsConfig) -> None:
    """Merge plugin extensions and write the staged MkDocs config."""

    core_config = _load_yaml_mapping(config.staged_mkdocs_config)
    merged_config = merge_mkdocs_config(core_config, config.extensions)
    config.staged_mkdocs_config.write_text(
        yaml.dump(merged_config, Dumper=_MkdocsDumper, sort_keys=False),
        encoding="utf-8",
    )


def _validate_plugin_docs_config(config: PluginDocsConfig) -> None:
    """Validate path relationships that could make staging destructive or recursive."""
    if config.generated_root == config.project_root:
        raise ValueError("generated_root must not be the same directory as project_root.")
    if _is_relative_to(config.generated_root, config.plugin_docs_dir):
        raise ValueError("generated_root must not be inside plugin_docs_dir.")


def _copy_plugin_docs_dir(config: PluginDocsConfig) -> None:
    """Copy plugin docs into the staged docs directory without overwriting core docs.

    `plugin_docs_dir` is a source path in the plugin repository. Its contents
    are copied directly into the staged MkDocs `docs/` directory, so plugin
    docs must use namespaced filenames/directories such as
    `example_plugin_index.md` and `example_plugin_user_guide/`.
    """
    if not config.plugin_docs_dir.exists():
        raise FileNotFoundError(f"Plugin docs directory does not exist: {config.plugin_docs_dir}")
    if not config.plugin_docs_dir.is_dir():
        raise NotADirectoryError(f"Plugin docs path is not a directory: {config.plugin_docs_dir}")

    docs_root = config.generated_root / "docs"
    for source_path in sorted(config.plugin_docs_dir.rglob("*")):
        relative_path = source_path.relative_to(config.plugin_docs_dir)
        if _should_ignore_local_docs_path(relative_path) or source_path == config.config_path:
            continue

        destination = docs_root / relative_path
        if source_path.is_dir():
            if destination.exists() and not destination.is_dir():
                raise FileExistsError(f"Plugin docs path collides with an exported core docs file: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            continue

        if destination.exists():
            raise FileExistsError(
                "Plugin docs path would overwrite exported core docs: "
                f"{destination}. Rename the plugin docs path or use a namespaced directory."
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _run_mkdocs(config: PluginDocsConfig, command: str, *mkdocs_args: str) -> subprocess.CompletedProcess:
    """Run a MkDocs command against the staged MkDocs config.

    `mkdocs_args` is intentionally unrestricted so callers can use any options
    supported by the installed MkDocs version.
    """
    try:
        return subprocess.run(
            ["mkdocs", command, "-f", str(config.staged_mkdocs_config), *mkdocs_args],
            cwd=config.generated_root,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "mkdocs is required to build or serve plugin documentation. "
            "Install MADA Tools with the docs extra, for example `pip install 'mada_tools[docs]'`."
        ) from exc


def _api_edit_path(mapping: ApiReferenceMapping) -> Path:
    """Return the source path used for generated API reference edit links."""
    if mapping.source_path is not None:
        return Path(mapping.source_path)
    return Path("src").joinpath(*mapping.package_name.split("."))


def _should_ignore_local_docs_path(path: Path) -> bool:
    """Return whether a plugin docs file should be excluded from staging."""
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether `path` is contained by `parent`."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _should_ignore_api_path(path: Path, ignore_patterns: Iterable[PathLike]) -> bool:
    """Return whether an API source path should be excluded."""
    if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
        return True

    for raw_pattern in ignore_patterns:
        pattern = Path(raw_pattern)
        if path.is_relative_to(pattern):
            return True
        if path.match(str(pattern)):
            return True
    return False
