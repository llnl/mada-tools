# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Tests for plugin documentation staging helpers."""

import re
import shutil
from pathlib import Path

import pytest

from mada_tools.docs import (
    PluginDocsConfig,
    build_plugin_docs,
    clean_plugin_docs,
    load_plugin_docs_config,
    merge_mkdocs_config,
    prepare_plugin_docs_site,
    serve_plugin_docs,
)


def test_load_plugin_docs_config_resolves_paths(tmp_path: Path):
    """Config paths should resolve relative to config and project roots."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    config_path = docs_dir / "plugin_docs.yaml"
    config_path.write_text(
        """
project_root: ..
generated_root: .generated_docs
plugin_docs_dir: docs
site_name: Plugin
""",
        encoding="utf-8",
    )

    config = load_plugin_docs_config(config_path)

    assert config.config_path == config_path.resolve()
    assert config.project_root == tmp_path.resolve()
    assert config.generated_root == (tmp_path / ".generated_docs").resolve()
    assert config.plugin_docs_dir == (tmp_path / "docs").resolve()


def test_load_plugin_docs_config_uses_defaults(tmp_path: Path):
    """Omitted config fields should use documented defaults."""
    config_path = tmp_path / "plugin_docs.yaml"
    config_path.write_text("{}", encoding="utf-8")

    config = load_plugin_docs_config(config_path)

    assert config.project_root == tmp_path.resolve()
    assert config.generated_root == (tmp_path / ".generated_docs").resolve()
    assert config.plugin_docs_dir == (tmp_path / "docs").resolve()
    assert config.extensions == {}


def test_merge_mkdocs_config_preserves_core_and_appends_plugin_fields():
    core = {
        "site_name": "MADA Tools",
        "nav": [{"Core": "index.md"}],
        "plugins": [{"gen-files": {"scripts": ["docs/gen_ref_pages.py"]}}],
        "extra": {"social": [{"name": "Core"}]},
        "theme": {"name": "material"},
    }
    plugin = {
        "site_name": "Plugin",
        "nav": [{"Plugin": "plugin/index.md"}],
        "gen_files": {"scripts": ["docs/plugin_gen_ref_pages.py"]},
        "extra": {"social": [{"name": "Plugin"}]},
    }

    merged = merge_mkdocs_config(core, plugin)

    assert merged["site_name"] == "Plugin"
    assert merged["nav"] == [{"Core": "index.md"}, {"Plugin": "plugin/index.md"}]
    assert merged["plugins"][0]["gen-files"]["scripts"] == ["docs/gen_ref_pages.py", "docs/plugin_gen_ref_pages.py"]
    assert merged["extra"]["social"] == [{"name": "Core"}, {"name": "Plugin"}]
    assert core["nav"] == [{"Core": "index.md"}]


@pytest.mark.parametrize(
    "config_text",
    ["bad_field: true", "nav: invalid", "gen_files: {scripts: nope}"],
)
def test_load_plugin_docs_config_rejects_unsupported_or_malformed_fields(tmp_path: Path, config_text: str):
    config_path = tmp_path / "plugin_docs.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_plugin_docs_config(config_path)


def test_prepare_plugin_docs_site_stages_core_docs_plugin_docs_and_landing_page(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Preparing should export core docs and copy plugin docs."""
    _write_plugin_docs_project(tmp_path)
    config = load_plugin_docs_config(tmp_path / "docs" / "plugin_docs.yaml")

    def fake_export_docs(destination: Path):
        (destination / "docs").mkdir(parents=True)
        (destination / "docs" / "core.md").write_text("core docs\n", encoding="utf-8")
        (destination / "mkdocs.yaml").write_text("site_name: Core\n", encoding="utf-8")
        return destination

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "export_docs", fake_export_docs)

    generated_root = prepare_plugin_docs_site(config)

    assert generated_root == tmp_path / ".generated_docs"
    assert (generated_root / "docs" / "core.md").read_text(encoding="utf-8") == "core docs\n"
    assert (generated_root / "docs" / "example_plugin_index.md").read_text(encoding="utf-8") == "plugin landing\n"
    assert (generated_root / "docs" / "example_plugin_user_guide" / "usage.md").read_text(encoding="utf-8") == "usage\n"
    assert not (generated_root / "docs" / "plugin_docs.yaml").exists()
    assert (generated_root / "mkdocs.yaml").read_text(encoding="utf-8") == "site_name: Plugin\n"


def test_prepare_merges_core_config_without_plugin_mkdocs_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "plugin.md").write_text("plugin\n", encoding="utf-8")
    (docs_dir / "plugin_docs.yaml").write_text(
        "project_root: ..\n"
        "generated_root: .generated_docs\n"
        "plugin_docs_dir: docs\n"
        "site_name: Plugin\n"
        "nav:\n"
        "  - Plugin: plugin.md\n"
        "gen_files:\n"
        "  scripts:\n"
        "    - docs/plugin_gen_ref_pages.py\n"
        "extra:\n"
        "  social:\n"
        "    - name: Plugin\n"
        "      link: https://example.test/plugin\n",
        encoding="utf-8",
    )
    config = load_plugin_docs_config(docs_dir / "plugin_docs.yaml")

    def fake_export_docs(destination: Path):
        (destination / "docs").mkdir(parents=True)
        (destination / "docs" / "core.md").write_text("core\n", encoding="utf-8")
        (destination / "mkdocs.yaml").write_text(
            "site_name: Core\n"
            "nav:\n"
            "  - Core: core.md\n"
            "plugins:\n"
            "  - gen-files:\n"
            "      scripts:\n"
            "        - docs/gen_ref_pages.py\n",
            encoding="utf-8",
        )
        return destination

    import yaml

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "export_docs", fake_export_docs)
    prepare_plugin_docs_site(config)

    generated = yaml.safe_load((tmp_path / ".generated_docs" / "mkdocs.yaml").read_text())
    assert generated["site_name"] == "Plugin"
    assert generated["nav"] == [{"Core": "core.md"}, {"Plugin": "plugin.md"}]
    assert generated["plugins"][0]["gen-files"]["scripts"] == ["docs/gen_ref_pages.py", "docs/plugin_gen_ref_pages.py"]
    assert (tmp_path / ".generated_docs" / "docs" / "plugin.md").exists()
    assert not (tmp_path / "mkdocs.yaml").exists()


def test_prepare_plugin_docs_site_excludes_python_cache_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Local docs directory copies should not include Python cache artifacts."""
    _write_plugin_docs_project(tmp_path)
    config = load_plugin_docs_config(tmp_path / "docs" / "plugin_docs.yaml")

    def fake_export_docs(destination: Path):
        (destination / "docs").mkdir(parents=True)
        (destination / "mkdocs.yaml").write_text("site_name: Core\n", encoding="utf-8")
        return destination

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "export_docs", fake_export_docs)

    prepare_plugin_docs_site(config)

    assert not (tmp_path / ".generated_docs" / "docs" / "example_plugin_user_guide" / "__pycache__").exists()
    assert not (tmp_path / ".generated_docs" / "docs" / "example_plugin_user_guide" / "compiled.pyc").exists()


def test_prepare_plugin_docs_site_reports_missing_plugin_docs_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Missing plugin docs directories should fail with the missing source path."""
    _write_plugin_docs_project(tmp_path)
    config = load_plugin_docs_config(tmp_path / "docs" / "plugin_docs.yaml")
    missing_source = tmp_path / "docs"
    shutil.rmtree(missing_source)

    def fake_export_docs(destination: Path):
        (destination / "docs").mkdir(parents=True)
        (destination / "mkdocs.yaml").write_text("site_name: Core\n", encoding="utf-8")
        return destination

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "export_docs", fake_export_docs)

    with pytest.raises(FileNotFoundError, match=re.escape(str(missing_source))):
        prepare_plugin_docs_site(config)


def test_prepare_plugin_docs_site_reports_core_docs_collision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Plugin docs should not overwrite exported core docs paths."""
    _write_plugin_docs_project(tmp_path)
    (tmp_path / "docs" / "index.md").write_text("conflicting plugin index\n", encoding="utf-8")
    config = load_plugin_docs_config(tmp_path / "docs" / "plugin_docs.yaml")

    def fake_export_docs(destination: Path):
        (destination / "docs").mkdir(parents=True)
        (destination / "docs" / "index.md").write_text("core index\n", encoding="utf-8")
        (destination / "mkdocs.yaml").write_text("site_name: Core\n", encoding="utf-8")
        return destination

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "export_docs", fake_export_docs)

    with pytest.raises(FileExistsError, match="overwrite exported core docs"):
        prepare_plugin_docs_site(config)


def test_prepare_plugin_docs_site_accepts_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The prepare helper should accept either a loaded config or a config path."""
    expected_root = tmp_path / ".generated_docs"

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(
        docs_mod,
        "load_plugin_docs_config",
        lambda config_path: PluginDocsConfig(
            config_path=Path(config_path),
            project_root=tmp_path,
            generated_root=expected_root,
            plugin_docs_dir=tmp_path / "docs",
        ),
    )
    monkeypatch.setattr(docs_mod, "export_docs", lambda destination: destination)
    monkeypatch.setattr(docs_mod, "_write_staged_mkdocs_config", lambda config: None)
    monkeypatch.setattr(docs_mod, "_copy_plugin_docs_dir", lambda config: None)

    assert prepare_plugin_docs_site(tmp_path / "docs" / "plugin_docs.yaml") == expected_root


def test_build_and_serve_plugin_docs_pass_mkdocs_args_after_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Build and serve should stage docs before delegating to MkDocs."""
    config_path = tmp_path / "docs" / "plugin_docs.yaml"
    config = PluginDocsConfig(
        config_path=config_path,
        project_root=tmp_path,
        generated_root=tmp_path / ".generated_docs",
        plugin_docs_dir=tmp_path / "docs",
    )
    calls = []

    import mada_tools.docs as docs_mod

    monkeypatch.setattr(docs_mod, "load_plugin_docs_config", lambda path: config)
    monkeypatch.setattr(docs_mod, "prepare_plugin_docs_site", lambda cfg: calls.append(("prepare", cfg)))
    monkeypatch.setattr(docs_mod, "_run_mkdocs", lambda cfg, command, *args: calls.append((command, cfg, args)))

    build_plugin_docs(config_path, "--strict")
    serve_plugin_docs(config_path, "--dev-addr", "127.0.0.1:9000")

    assert calls == [
        ("prepare", config),
        ("build", config, ("--strict",)),
        ("prepare", config),
        ("serve", config, ("--dev-addr", "127.0.0.1:9000")),
    ]


def test_clean_plugin_docs_removes_generated_root(tmp_path: Path):
    """Clean should remove the configured generated docs tree."""
    generated_root = tmp_path / ".generated_docs"
    generated_root.mkdir()
    (generated_root / "stale.md").write_text("stale\n", encoding="utf-8")
    config = PluginDocsConfig(
        config_path=tmp_path / "docs" / "plugin_docs.yaml",
        project_root=tmp_path,
        generated_root=generated_root,
        plugin_docs_dir=tmp_path / "docs",
    )

    cleaned_root = clean_plugin_docs(config)

    assert cleaned_root == generated_root
    assert not generated_root.exists()


def _write_plugin_docs_project(project_root: Path) -> None:
    """Create a minimal plugin docs project for staging tests."""
    docs_dir = project_root / "docs"
    guide_dir = docs_dir / "example_plugin_user_guide"
    cache_dir = guide_dir / "__pycache__"
    cache_dir.mkdir(parents=True)
    (docs_dir / "example_plugin_index.md").write_text("plugin landing\n", encoding="utf-8")
    (guide_dir / "usage.md").write_text("usage\n", encoding="utf-8")
    (guide_dir / "compiled.pyc").write_bytes(b"cache")
    (cache_dir / "ignored.py").write_text("cache\n", encoding="utf-8")
    (docs_dir / "plugin_docs.yaml").write_text(
        """
project_root: ..
generated_root: .generated_docs
plugin_docs_dir: docs
site_name: Plugin
""",
        encoding="utf-8",
    )
