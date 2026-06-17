# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
MCP Server for Vertex-CFD mini-application.

This server provides MCP tools for setting up, running, and analyzing
Vertex-CFD simulations.
"""

from typing import List

from mada_tools.shared.base_server import BaseMCPServer
from mada_tools.simulation.vertex_cfd.helper_classes.vertex_cfd_helper import (
    VertexCFDHelper,
)


class VertexCFDServer(BaseMCPServer):
    """MCP Server for Vertex-CFD application."""

    def __init__(self):
        super().__init__("Vertex-CFD Application", "Vertex-CFD application tools")

        self.vertex_cfd_helper = VertexCFDHelper()

    def _register_tools(self):
        """Register MCP tools for Vertex-CFD operations."""

        @self.mcp.tool()
        def generate_parameter_runs(
            num_samples: int,
            parameter_names: List[str],
            lower_bounds: List[float],
            upper_bounds: List[float],
            output_dir: str,
            input_deck_location: str | None = None,
            mesh_file_location: str | None = None,
        ) -> str:
            """
            Generate parameter runs for a Vertex-CFD parameter sweep study.

            Creates a structured directory with parameter files for each run,
            ready for job submission to a scheduler like Flux.

            Args:
                num_samples: Number of parameter sets to generate
                parameter_names: List of parameter names (e.g. ["vinit", "porosity"])
                lower_bounds: Lower bounds for each parameter dimension
                upper_bounds: Upper bounds for each parameter dimension
                output_dir: Directory where run folders will be created
                input_deck_location: Location of input deck; defaults to None
                mesh_file_location: Location of mesh file; defaults to None

            Returns:
                str: JSON string with run information for job submission
            """
            return self.run_tool(
                self.vertex_cfd_helper.generate_parameter_runs,
                num_samples,
                parameter_names,
                lower_bounds,
                upper_bounds,
                output_dir,
                input_deck_location,
                mesh_file_location,
            )

        @self.mcp.tool()
        def post_process_runs(
            output_dir: str,
        ) -> str:
            """
            Post process parameter runs for a Vertex-CFD parameter sweep study.

            Looks through structured directory with parameter files for each run
            and post proccesses them.

            Args:
                output_dir: Directory where run folders were created

            Returns:
                str: Success string
            """
            return self.run_tool(self.vertex_cfd_helper.post_process_runs, output_dir)

        @self.mcp.tool()
        def in_situ_viz() -> dict:
            """
            Create In Situ Visualization for GUI Chat Interface.

            Looks through run00 and creates pngs that get fed into gradio.

            Returns:
                str: Success string
            """
            return self.run_tool(self.vertex_cfd_helper.in_situ_viz)


def main():
    """Main entry point for the Vertex-CFD MCP server."""
    server = VertexCFDServer()
    server.run_with_args("vertex_cfd")


if __name__ == "__main__":
    main()
