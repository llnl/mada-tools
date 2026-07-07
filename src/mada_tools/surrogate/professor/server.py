# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Professor MCP Server for analysis and visualization.

This server provides MCP tools for launching Professor visualization tools
and performing data analysis tasks.
"""

from mada_tools.shared.base_server import BaseMCPServer
from mada_tools.surrogate.professor.professor_helper import ProfessorHelper


class ProfessorServer(BaseMCPServer):
    """MCP Server for Professor analysis and visualization."""

    def __init__(self):
        super().__init__("Professor Analysis", "Professor analysis and visualization tools")

        self.professor_helper = ProfessorHelper()

    def _register_tools(self):
        """Register MCP tools for Professor operations."""

        @self.mcp.tool()
        def launch_professor_gui(yaml_file: str) -> str:
            """
            Launch Professor GUI from the given YAML config.

            Args:
                yaml_file: Path to Professor YAML config file

            Returns:
                str: Confirmation message once GUI process has started
            """
            return self.run_tool(self.professor_helper.launch_professor_gui, yaml_file)

        @self.mcp.tool()
        def analyze_image_with_llm(image_path: str, prompt: str) -> str:
            """
            Use an LLM to analyze and describe an image based on a prompt.

            Args:
                image_path: Local file path to the image
                prompt: Question or instruction about the image

            Returns:
                str: LLM-generated description or error message
            """
            return self.run_tool(self.professor_helper.analyze_image_with_llm, image_path, prompt)


def main():
    """Main entry point for the Professor MCP server."""
    server = ProfessorServer()
    server.run_with_args("professor")


if __name__ == "__main__":
    main()
