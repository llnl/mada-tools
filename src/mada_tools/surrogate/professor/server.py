# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Professor MCP Server for analysis and visualization.

This server provides MCP tools for launching Professor visualization tools
and performing data analysis tasks.
"""

import base64
import os
import subprocess

from openai import OpenAI

from ...shared.base_server import BaseMCPServer
from ...shared.exceptions import ToolExecutionError


class ProfessorServer(BaseMCPServer):
    """MCP Server for Professor analysis and visualization."""

    def __init__(self):
        super().__init__("Professor Analysis", "Professor analysis and visualization tools")

        # Initialize LLM client for image analysis
        try:
            self.llm_client = OpenAI(
                base_url=self.get_env_var("API_BASE_URL", "https://livai-api.llnl.gov"),
                api_key=self.get_env_var("API_KEY", required=True),
            )
            # Get model from environment or use default
            self.model = self.get_env_var("MODEL", "gpt-4o")
        except Exception:
            # LLM client is optional for some operations
            self.llm_client = None
            self.model = None

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
            try:
                prof_vis_path = self.get_env_var("PROF_VIS_PATH", "/usr/workspace/prof/bin/prof-vis")
                cmd = [prof_vis_path, yaml_file]

                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return "Professor GUI launched successfully"
            except Exception as e:
                raise ToolExecutionError(f"Failed to launch Professor GUI: {e}")

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
            if not self.llm_client:
                return "LLM client not configured. Please set API_KEY environment variable."

            if not os.path.isfile(image_path):
                return f"Error: File not found: {image_path}"

            try:
                # Read and encode the image
                with open(image_path, "rb") as f:
                    img_bytes = f.read()
                img_b64 = base64.b64encode(img_bytes).decode()

                # Compose messages with dynamic prompt
                messages = [
                    {"role": "user", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                            }
                        ],
                    },
                ]

                response = self.llm_client.chat.completions.create(messages=messages, model=self.model)
                return response.choices[0].message.content

            except Exception as e:
                raise ToolExecutionError(f"Failed to analyze image: {e}")


def main():
    """Main entry point for the Professor MCP server."""
    server = ProfessorServer()
    server.run_with_args("professor")


if __name__ == "__main__":
    main()
