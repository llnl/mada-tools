#!/usr/bin/env python3
"""
Simple Agent Loop for MADA MCP Servers
Example: Diagnose existing Flux run folders using JobMonitorServer.
No jobs are submitted. Only the JobMonitor server needs to be running.

This script:
  1. Connects to the JobMonitor MCP server
  2. Walks a directory with existing run_i.out and run_i.err files
  3. Calls summarize_status() for each run folder
"""

import argparse
import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ------------------------------------------------------------
# Utility function to connect to a monitor MCP server
# ------------------------------------------------------------
async def connect(url: str):
    transport = streamablehttp_client(url)
    read_stream, write_stream, _ = await transport.__aenter__()
    session = ClientSession(read_stream, write_stream)
    await session.__aenter__()
    await session.initialize()
    return session, transport


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
async def main():
    # ------------------------------------------------------------
    # Parse command line arguments
    # ------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Diagnose run folders using the JobMonitor MCP server.")

    parser.add_argument(
        "--monitor",
        required=True,
        help="URL of the JobMonitor MCP server, for example http://localhost:8006/mcp",
    )

    parser.add_argument(
        "--study",
        required=True,
        help="Path to study directory containing run_i folders, for example "
        "/usr/workspace/mada/mada_refactored/studies",
    )

    args = parser.parse_args()

    monitor_url = args.monitor
    study_dir = args.study
    # ------------------------------------------------------------
    # 1. Connect to JobMonitor server
    # ------------------------------------------------------------
    print(f"Connecting to JobMonitor server at {monitor_url} ...")
    monitor, monitor_t = await connect(monitor_url)
    print("Connected.\n")

    print(f"Scanning study directory:\n  {study_dir}")

    # ------------------------------------------------------------
    # 2. Scan for run directories
    # ------------------------------------------------------------
    run_dirs = sorted(
        d for d in os.listdir(study_dir) if os.path.isdir(os.path.join(study_dir, d)) and d.startswith("run")
    )

    if not run_dirs:
        print("No run* folders found.")
        return

    print(f"Found run directories: {run_dirs}\n")

    # ------------------------------------------------------------
    # 3. Diagnose each run folder
    # ------------------------------------------------------------
    for run in run_dirs:
        run_path = os.path.join(study_dir, run)

        # Extract numeric index: "run3" → "3"
        idx = run.replace("run", "")

        stdout_file = f"run_{idx}.out"
        stderr_file = f"run_{idx}.err"

        print("------------------------------------------------------")
        print(f"Diagnosing Run: {run}")
        print(f"Location: {run_path}")
        print(f"stdout: {stdout_file}")
        print(f"stderr: {stderr_file}")

        # ------------------------------------------------------------
        # Call summarize_status tool in MCP JobMonitor
        # ------------------------------------------------------------
        result = await monitor.call_tool(
            "summarize_status",
            {
                "run_location": run_path,
                "stdout_file": stdout_file,
                "stderr_file": stderr_file,
                "exit_code": None,
            },
        )

        print("\nSummary:")
        print(result.content[0].text)
        print("------------------------------------------------------\n")

    # ------------------------------------------------------------
    # 5. Close monitor session
    # ------------------------------------------------------------
    await monitor.__aexit__(None, None, None)
    await monitor_t.__aexit__(None, None, None)


# Run
if __name__ == "__main__":
    asyncio.run(main())
