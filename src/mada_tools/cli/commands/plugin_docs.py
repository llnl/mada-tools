# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""CLI commands for staging and running plugin-local documentation sites."""

import logging
from argparse import REMAINDER, ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.docs import build_plugin_docs, clean_plugin_docs, prepare_plugin_docs_site, serve_plugin_docs

LOG = logging.getLogger(__name__)


class PluginDocsCmd(BaseCmd):
    """Manage combined core/plugin MkDocs documentation sites."""

    def add_parser(self, subparsers: ArgumentParser):
        """Add the ``plugin-docs`` command group to the main parser."""
        plugin_docs_parser: ArgumentParser = subparsers.add_parser(
            "plugin-docs",
            help="Manage a combined core/plugin documentation site.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        plugin_docs_subparsers = plugin_docs_parser.add_subparsers(dest="plugin_docs_command", required=True)

        for command, help_text, accepts_mkdocs_args in (
            ("prepare", "Stage a combined core/plugin documentation source tree.", False),
            ("build", "Stage and build a combined core/plugin documentation site.", True),
            ("serve", "Stage and serve a combined core/plugin documentation site.", True),
            ("clean", "Remove the staged plugin documentation source tree.", False),
        ):
            command_parser = plugin_docs_subparsers.add_parser(
                command,
                help=help_text,
                formatter_class=ArgumentDefaultsHelpFormatter,
            )
            command_parser.add_argument(
                "--config",
                default="docs/plugin_docs.yaml",
                help="Path to the plugin docs configuration file.",
            )
            if accepts_mkdocs_args:
                command_parser.add_argument(
                    "mkdocs_args",
                    nargs=REMAINDER,
                    help="Additional arguments passed to the underlying mkdocs command.",
                )
            command_parser.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """Run the selected plugin docs subcommand."""
        command = args.plugin_docs_command
        config_path = args.config

        if command == "prepare":
            generated_root = prepare_plugin_docs_site(config_path)
            LOG.info("Prepared plugin documentation source tree at %s", generated_root)
        elif command == "build":
            build_plugin_docs(config_path, *_mkdocs_args(args))
            LOG.info("Built plugin documentation site using %s", config_path)
        elif command == "serve":
            serve_plugin_docs(config_path, *_mkdocs_args(args))
        elif command == "clean":
            generated_root = clean_plugin_docs(config_path)
            LOG.info("Removed plugin documentation source tree at %s", generated_root)
        else:
            raise ValueError(f"Unknown plugin docs command: {command}")


def _mkdocs_args(args: Namespace) -> list[str]:
    """Return pass-through MkDocs args, dropping an optional separator."""
    mkdocs_args = list(getattr(args, "mkdocs_args", []) or [])
    if mkdocs_args and mkdocs_args[0] == "--":
        return mkdocs_args[1:]
    return mkdocs_args
