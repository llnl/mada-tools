# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import importlib
import json
import sys
import threading
import types

from mada_tools.scheduler import base_manager


class _FakeFluxExecutor:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class _FakeJobID(int):
    def __new__(cls, value):
        return int.__new__(cls, int(value))

    def __str__(self):
        if int(self) == 12345:
            return "f4fr"
        return str(int(self))


class _FakeJobspecV1:
    @classmethod
    def from_command(cls, *args, **kwargs):
        return cls()

    def setattr(self, name, value):
        setattr(self, name.replace(".", "_"), value)


class _FakeJobList:
    def __init__(self, *args, **kwargs):
        pass

    def jobs(self):
        return []


fake_flux = types.ModuleType("flux")
fake_flux_job = types.ModuleType("flux.job")
fake_flux_job_list = types.ModuleType("flux.job.list")
fake_flux_job.submit = lambda handle, jobspec, urgency: 12345
fake_flux_job.FluxExecutor = _FakeFluxExecutor
fake_flux_job.JobID = _FakeJobID
fake_flux_job.JobspecV1 = _FakeJobspecV1
fake_flux_job_list.JobList = _FakeJobList
fake_flux_job_list.get_job = lambda handle, job_id: None
fake_flux.job = fake_flux_job
fake_flux.Flux = lambda *args, **kwargs: object()
sys.modules["flux"] = fake_flux
sys.modules["flux.job"] = fake_flux_job
sys.modules["flux.job.list"] = fake_flux_job_list

flux_manager = importlib.import_module("mada_tools.scheduler.flux.flux_manager")
FluxJobManager = flux_manager.FluxJobManager


def _manager_without_flux_connection() -> FluxJobManager:
    manager = FluxJobManager.__new__(FluxJobManager)
    manager.run_info_json = None
    manager.loaded_runs = None
    manager.persistent_executor = None
    manager.jobs = {}
    manager.job_counter = 0
    manager.jobs_lock = threading.Lock()
    manager.use_persistent_executor = False
    manager.flux_url = None
    manager.flux_handle = object()
    return manager


def test_submit_jobs_returns_real_flux_ids(monkeypatch, tmp_path):
    manager = _manager_without_flux_connection()
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

    monkeypatch.setattr(manager, "_open_flux_handle", lambda: object())
    monkeypatch.setattr(flux_manager.flux.job, "submit", lambda handle, jobspec, urgency: 12345)

    success, payload = manager.submit_jobs(run_info_json)

    assert success is True
    response = json.loads(payload)
    assert response["submitted_jobs"] == 1
    assert response["failed_submissions"] == 0

    job = response["jobs"][0]
    assert job["job_id"] == "job_000001"
    assert job["run_id"] == "00"
    assert job["run_location"] == str(run_directory.resolve())
    assert job["status"] == "pending"
    assert job["flux_job_id"] == 12345
    assert job["flux_job_id_f58"] == "f4fr"


def test_check_job_status_returns_tracked_flux_ids(monkeypatch, tmp_path):
    manager = _manager_without_flux_connection()
    run_info_json = json.dumps(
        {
            "runs": [
                {
                    "id": "00",
                    "run_location": str(tmp_path / "run00"),
                    "command": "/bin/echo",
                    "args": ["hello"],
                }
            ]
        }
    )

    monkeypatch.setattr(manager, "_open_flux_handle", lambda: object())
    monkeypatch.setattr(flux_manager.flux.job, "submit", lambda handle, jobspec, urgency: 12345)
    monkeypatch.setattr(manager, "_refresh_jobs", lambda jobs: None)
    success, _ = manager.submit_jobs(run_info_json)

    _, status_json = manager.get_job_status(job_id="job_000001")
    status = json.loads(status_json)

    assert success is True
    assert status["job_id"] == "job_000001"
    assert status["flux_job_id"] == 12345
    assert status["flux_job_id_f58"] == "f4fr"


def test_continuously_check_job_status_waits_until_terminal(monkeypatch):
    manager = _manager_without_flux_connection()
    responses = iter(
        [
            {"job_id": "job_000001", "status": "running"},
            {"job_id": "job_000001", "status": "completed"},
        ]
    )

    monkeypatch.setattr(base_manager.time, "sleep", lambda _: None)
    monkeypatch.setattr(manager, "get_job_status", lambda **_: (True, json.dumps(next(responses))))

    _, result_json = manager.continuously_check_job_status(
        job_id="job_000001",
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
    )
    result = json.loads(result_json)

    assert result["condition_met"] is True
    assert result["timed_out"] is False
    assert result["poll_attempts"] == 2
    assert result["status"]["status"] == "completed"
