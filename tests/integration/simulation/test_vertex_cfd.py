"""
Integration tests for the Vertex-CFD MCP server to verify required tools are available.
"""

import pytest


@pytest.mark.requires_env("MCP_SERVER:vertex_cfd")
@pytest.mark.requires_gitlab_runner
@pytest.mark.asyncio
async def test_vertex_cfd_server_connection(validated_server_group):
    """
    Verify the Vertex-CFD server group exposes the expected MCP tools.

    Args:
        validated_server_group: Fixture that validates a server group and returns results.
    """
    servers = {
        "vertex_cfd": {"generate_parameter_runs", "post_process_runs", "in_situ_viz"},
        "flux": {"submit_command", "continuously_check_job_status", "check_job_status", "submit_jobs"},
    }

    results = await validated_server_group("vertex_cfd", servers)

    for server in servers:
        assert server in results
