"""
End-to-end tests for Vertex-CFD MCP Server with LLM Interaction
"""

from pathlib import Path

import pytest


@pytest.mark.requires_env("MCP_SERVER:vertex_cfd")
@pytest.mark.requires_gitlab_runner
@pytest.mark.asyncio
async def test_vertex_cfd_prompt(
    agent_test_runner,
    simulation_testing_dir: Path,
):
    """
    Verify the Vertex-CFD MCP server can generate runs, submit jobs,
    check job status, and post-process results through LLM prompts.

    Args:
        agent_test_runner: Fixture that returns an async test runner for the MCP server.
        simulation_testing_dir (Path): Base directory for simulation test outputs.

    """
    runner = await agent_test_runner(
        "vertex_cfd_servers.json",
        "config_vertex_cfd.json",
    )
    async with runner:
        runs = 10
        sims_dir = simulation_testing_dir / "vertex_cfd"
        param_names = [
            "velocity_0",
            "velocity_1",
            "Exodus Write Frequency",
            "Minimum Time Step",
            "Maximum Time Step",
            "Initial Time Step",
            "Final Time Index",
        ]
        lower_bounds = [0, 5, 10, 1e-4, 1e-3, 1e-3, 100]
        upper_bounds = [5, 10, 10, 1e-4, 1e-3, 1e-3, 100]
        queue = "pdebug"
        minutes = 15
        tasks = 16

        # vertext_cfd.generate_parameter_runs
        prompt = (
            f"Generate {runs} runs in {sims_dir} with parameters "
            f"{' and '.join(param_names)} with lower bounds "
            f"{', '.join(map(str, lower_bounds))} and upper bounds "
            f"{', '.join(map(str, upper_bounds))}."
        )
        response = await runner.process_query(prompt)
        assert response
        assert "Executed tool: generate_parameter_runs" in response
        assert f"'num_samples': {runs}" in response
        assert f"'parameter_names': {param_names}" in response
        assert f"'lower_bounds': {lower_bounds}" in response
        assert f"'upper_bounds': {upper_bounds}" in response
        assert f"'output_dir': '{sims_dir}'" in response

        # flux.submit_jobs
        prompt = f"Submit jobs with queue {queue} for {minutes} minutes with {tasks} tasks."
        response = await runner.process_query(prompt)
        assert response
        assert "Executed tool: submit_jobs" in response
        assert f"{queue}" in response
        assert f"{minutes}m" in response
        assert f"{tasks}" in response

        for i in range(runs):
            assert f"run{i:02d}" in response

        # flux.check_job_status
        response = await runner.process_query("Check job status.")
        assert response
        assert "Executed tool: check_job_status" in response
        assert f"{runs}" in response

        # vertext_cfd.post_process_runs
        response = await runner.process_query("Post process runs.")
        assert response
        assert "Executed tool: post_process_runs" in response
        assert f"'output_dir': '{sims_dir}'" in response

        # TODO: Add cancel jobs tool to flux and slurm
