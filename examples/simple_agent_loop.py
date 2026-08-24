#!/usr/bin/env python3
"""Interactive example showing how to use `mada_tools.agents.MultiServerAgent`.

This script remains in `examples/` as a runnable reference application, but the
actual reusable agent implementation now lives in package code. That keeps the
example useful for humans while letting tests and extension packages import the
same underlying agent from a stable public module path.
"""

import argparse
import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from datetime import datetime

from mada_tools.agents import MultiServerAgent
from mada_tools.agents.multi_server_agent import LOGGER as AGENT_LOGGER


def configure_logging() -> logging.Logger:
    """Configure console and file logging for the interactive example.

    Returns:
        logging.Logger: Logger configured for both the example wrapper and the
        shared agent module.
    """
    logger = logging.getLogger("mada_tools.examples.simple_agent_loop")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(f"simple_agent_loop_history_{timestamp}.log")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    AGENT_LOGGER.setLevel(logging.INFO)
    AGENT_LOGGER.handlers.clear()
    AGENT_LOGGER.addHandler(stream_handler)
    AGENT_LOGGER.addHandler(file_handler)
    AGENT_LOGGER.propagate = False

    return logger


async def main():
    """Run the interactive multi-server agent example.

    The example parses the config path, initializes the shared agent inside an
    `AsyncExitStack`, and then hands off control to the interactive chat loop.
    """
    parser = argparse.ArgumentParser(description="Multi-Server Agent for MADA MCP Servers")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Configuration file path (default: config.json)",
    )
    args = parser.parse_args()

    logger = configure_logging()
    agent = MultiServerAgent(config_path=args.config)

    try:
        async with AsyncExitStack() as stack:
            await agent.initialize(stack)
            await agent.chat_loop()

    except Exception as exc:
        logger.error("Error: %s", exc)
        logger.error("\nTroubleshooting:")
        logger.error("1. Make sure the MCP servers are running")
        logger.error("2. Check your API_KEY environment variable")
        logger.error("3. Verify the MCP server URLs in config.json are correct")
        logger.error("4. Edit config.json mcp_servers section to specify which servers to connect to")


if __name__ == "__main__":
    asyncio.run(main())
