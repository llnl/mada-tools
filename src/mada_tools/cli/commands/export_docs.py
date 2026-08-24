# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""CLI command for exporting packaged MADA Tools documentation sources."""

import logging
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser, Namespace

from mada_tools.cli.commands.base_cmd import BaseCmd
from mada_tools.docs import export_docs

LOG = logging.getLogger(__name__)


class ExportDocsCmd(BaseCmd):
    """Export the packaged MkDocs source project to a local directory."""

    def add_parser(self, subparsers: ArgumentParser):
        """Add the ``export-docs`` subcommand to the main argument parser.

        Args:
            subparsers: Subparser collection owned by the main CLI parser.
        """
        export_docs_parser: ArgumentParser = subparsers.add_parser(
            "export-docs",
            help="Export the packaged documentation source project.",
            formatter_class=ArgumentDefaultsHelpFormatter,
        )
        export_docs_parser.add_argument(
            "destination",
            help="Directory where the documentation source project will be exported.",
        )
        export_docs_parser.set_defaults(func=self.process_command)

    def process_command(self, args: Namespace):
        """Export packaged documentation sources to the requested destination.

        Args:
            args: Parsed CLI arguments containing the destination path.
        """
        destination = export_docs(args.destination)
        LOG.info("Exported documentation source to %s", destination)
