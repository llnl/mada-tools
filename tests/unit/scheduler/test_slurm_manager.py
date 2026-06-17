# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import json
import os
import shlex
import subprocess
import threading

from mada_tools.scheduler import base_manager
from mada_tools.scheduler.slurm.slurm_manager import SlurmJobManager
from mada_tools.simulation.simutils.models import RunInstance


def _manager_without_slurm_commands() -> SlurmJobManager:
    manager = SlurmJobManager.__new__(SlurmJobManager)
    manager.job_sets = {}
    manager.job_counter = 0
    manager.job_set_counter = 0
    manager.jobs_lock = threading.Lock()
    manager.sbatch_available = True
    manager.srun_available = False
    manager.squeue_available = False
    manager.sacct_available = False
    return manager


def test_write_sbatch_script_uses_debuggable_run_directory_script(tmp_path):
    manager = SlurmJobManager.__new__(SlurmJobManager)
    run_directory = tmp_path / "run00"
    run = RunInstance(
        id="00",
        run_location=str(run_directory),
        command="/bin/echo",
        args=["hello"],
    )

    script_path = manager._write_sbatch_script(
        run,
        command_tokens=["/bin/echo", "hello"],
        nodes=2,
        tasks=4,
        time_limit="00:30:00",
        account="account1",
        partition="debug",
        exclusive=True,
        cpus_per_task=3,
        job_name_prefix="mada",
    )

    resolved_run_directory = run_directory.resolve()
    assert script_path == resolved_run_directory / "submit_run.sbatch"
    assert script_path.exists()
    assert os.access(script_path, os.X_OK)

    contents = script_path.read_text(encoding="utf-8")
    assert f"#SBATCH --output={resolved_run_directory / 'run_00.out'}" in contents
    assert f"#SBATCH --error={resolved_run_directory / 'run_00.err'}" in contents
    assert f"cd {shlex.quote(str(resolved_run_directory))}" in contents
    assert "srun -N 2 -n 4 /bin/echo hello" in contents


def test_submit_jobs_returns_and_reports_real_slurm_ids(monkeypatch, tmp_path):
    manager = _manager_without_slurm_commands()
    run_directory = tmp_path / "run00"
    run_info_json = json.dumps(
        {
            "runs": [
                {
                    "id": "00",
                    "run_location": str(run_directory),
                    "command": "/bin/echo",
                    "args": ["hello"],
                }
            ]
        }
    )

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "sbatch"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="Submitted batch job 98765\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    success, payload = manager.submit_jobs(run_info_json)

    assert success is True
    response = json.loads(payload)
    assert response["job_set_id"] == "jobset_000001"
    assert response["submitted_jobs"] == 1
    assert response["failed_submissions"] == 0

    job = response["jobs"][0]
    assert job["job_id"] == "job_000001"
    assert job["run_id"] == "00"
    assert job["run_location"] == str(run_directory)
    assert job["status"] == "submitted"
    assert job["slurm_job_id"] == "98765"

    _, status_json = manager.get_job_status(job_set_id="jobset_000001")
    status = json.loads(status_json)
    assert status["job_set_id"] == "jobset_000001"
    assert status["jobs"][0]["local_job_id"] == "job_000001"
    assert status["jobs"][0]["slurm_job_id"] == "98765"


def test_continuously_check_job_status_returns_when_any_job_running(monkeypatch):
    manager = SlurmJobManager.__new__(SlurmJobManager)
    responses = iter(
        [
            {
                "job_set_id": "jobset_000001",
                "jobs": [{"status": "pending"}, {"status": "pending"}],
            },
            {
                "job_set_id": "jobset_000001",
                "jobs": [{"status": "running"}, {"status": "pending"}],
            },
        ]
    )

    monkeypatch.setattr(base_manager.time, "sleep", lambda _: None)
    monkeypatch.setattr(manager, "get_job_status", lambda **_: (True, json.dumps(next(responses))))

    _, result_json = manager.continuously_check_job_status(
        job_set_id="jobset_000001",
        wait_until="any_running",
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )
    result = json.loads(result_json)

    assert result["condition_met"] is True
    assert result["timed_out"] is False
    assert result["poll_attempts"] == 2
    assert result["status"]["jobs"][0]["status"] == "running"
