# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Helper class for Professor tools.

This module contains the non-MCP business logic used by `ProfessorServer` so
the server can delegate tool execution through `BaseMCPServer.run_tool()` while
keeping tool registration focused on MCP wiring.
"""

import base64
import os
import subprocess

from openai import OpenAI

from mada_tools.shared.env import get_env_var


class ProfessorHelper:
    """Encapsulate Professor tool implementations behind the run_tool contract.

    Attributes:
        llm_client: Configured OpenAI-compatible client used for image analysis,
            or None when LLM access is unavailable.
        model: Model name used for image-analysis requests, or None when no LLM
            client is configured.

    Methods:
        launch_professor_gui: Start the Professor GUI process for a YAML config.
        analyze_image_with_llm: Submit an image and prompt to the configured
            multimodal LLM.
    """

    def __init__(self):
        """Initialize the helper with optional LLM client configuration.

        The helper attempts to construct an OpenAI-compatible client from the
        environment. If the required API configuration is absent, image analysis
        remains disabled while the rest of the helper stays usable.
        """
        try:
            self.llm_client = OpenAI(
                base_url=get_env_var("API_BASE_URL", "https://livai-api.llnl.gov", False),
                api_key=get_env_var("API_KEY", None, True),
            )
            # Get model from environment or use default
            self.model = get_env_var("MODEL", "gpt-4o", False)
        except Exception:
            # LLM client is optional for some operations
            self.llm_client = None
            self.model = None

    def launch_professor_gui(self, yaml_file: str) -> tuple[bool, str]:
        """Launch the Professor GUI for the given YAML config.

        Args:
            yaml_file: Path to the Professor YAML configuration file.

        Returns:
            A `(success, payload)` tuple where `success` is always `True` and
            `payload` is a confirmation message once the GUI process has been
            started.
        """
        prof_vis_path = get_env_var("PROF_VIS_PATH", "/usr/workspace/prof/bin/prof-vis", False)
        cmd = [prof_vis_path, yaml_file]

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, "Professor GUI launched successfully"

    def analyze_image_with_llm(self, image_path: str, prompt: str) -> tuple[bool, str]:
        """Use the configured LLM to analyze an image from a local path.

        Args:
            image_path: Path to the local image file to analyze.
            prompt: User prompt or analysis instruction to send with the image.

        Returns:
            A `(success, payload)` tuple. `success` is always `True`; `payload`
            is either the model response or an informational message explaining
            why analysis could not be performed.
        """
        if not self.llm_client:
            return True, "LLM client not configured. Please set API_KEY environment variable."

        if not os.path.isfile(image_path):
            return True, f"Error: File not found: {image_path}"

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
        return True, response.choices[0].message.content
