# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import json
import threading
from typing import Generator, List, Tuple

from mada_tools.scheduler import base_manager
from mada_tools.scheduler.base_manager import MADABaseJobManager


class DummyJobManager(MADABaseJobManager):
    aggregate_manifest_fields = (
        "aggregate_scheduler_manifest_file",
        "aggregate_flux_manifest_file",
    )
    per_run_manifest_fields = (
        "scheduler_manifest_file",
        "flux_manifest_file",
    )

    def __init__(self):
        self.job_counter = 0
        self.jobs_lock = threading.Lock()

    def stage(
        self,
        dims: int,
        num_samples: int,
        lower_bounds: List[float],
        upper_bounds: List[float],
        output_dir: str,
        parameter_file: str,
    ) -> Tuple[bool, str]:
        return True, "staged"

    def execute(self) -> Generator[str, None, None]:
        yield "executed"


def _run_dict(run_id: str = "00") -> dict:
    return {
        "id": run_id,
        "run_location": f"/tmp/run{run_id}",
        "command": "/bin/echo",
        "args": ["hello"],
    }


def test_load_runs_accepts_inline_runs_object():
    manager = DummyJobManager()

    runs = manager._load_runs(json.dumps({"runs": [_run_dict()]}))

    assert len(runs) == 1
    assert runs[0].id == "00"
    assert runs[0].args == ["hello"]


def test_load_runs_accepts_bare_run_instances_file(tmp_path):
    manager = DummyJobManager()
    run_instances_file = tmp_path / "run_instances.json"
    run_instances_file.write_text(json.dumps([_run_dict("01")]), encoding="utf-8")

    runs = manager._load_runs(str(run_instances_file))

    assert len(runs) == 1
    assert runs[0].id == "01"


def test_load_runs_accepts_aggregate_manifest_reference(tmp_path):
    manager = DummyJobManager()
    aggregate_manifest_file = tmp_path / "scheduler_runs.json"
    aggregate_manifest_file.write_text(json.dumps({"runs": [_run_dict("02")]}), encoding="utf-8")

    runs = manager._load_runs(
        json.dumps(
            {
                "aggregate_scheduler_manifest_file": str(aggregate_manifest_file),
            }
        )
    )

    assert len(runs) == 1
    assert runs[0].id == "02"


def test_load_runs_accepts_per_run_manifest_reference(tmp_path):
    manager = DummyJobManager()
    run_manifest_file = tmp_path / "run_03.json"
    run_manifest_file.write_text(json.dumps({"runs": [_run_dict("03")]}), encoding="utf-8")

    runs = manager._load_runs(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "summary-03",
                        "scheduler_manifest_file": str(run_manifest_file),
                    }
                ]
            }
        )
    )

    assert len(runs) == 1
    assert runs[0].id == "03"


def test_load_runs_accepts_legacy_flux_manifest_alias(tmp_path):
    manager = DummyJobManager()
    run_manifest_file = tmp_path / "run_04.json"
    run_manifest_file.write_text(json.dumps({"runs": [_run_dict("04")]}), encoding="utf-8")

    runs = manager._load_runs(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "summary-04",
                        "flux_manifest_file": str(run_manifest_file),
                    }
                ]
            }
        )
    )

    assert len(runs) == 1
    assert runs[0].id == "04"


def test_next_job_id_allocates_sequential_local_ids():
    manager = DummyJobManager()

    assert manager._next_job_id() == "job_000001"
    assert manager._next_job_id() == "job_000002"


def test_poll_status_until_waits_for_terminal_status(monkeypatch):
    manager = DummyJobManager()
    responses = iter(
        [
            {"jobs": [{"status": "running"}]},
            {"jobs": [{"status": "completed"}]},
        ]
    )

    monkeypatch.setattr(base_manager.time, "sleep", lambda _: None)

    result = json.loads(
        manager._poll_status_until(
            status_reader=lambda: json.dumps(next(responses)),
            status_extractor=lambda payload: [job["status"] for job in payload["jobs"]],
            terminal_statuses={"completed", "failed", "unknown"},
            running_statuses={"running"},
            wait_until="terminal",
            poll_interval_seconds=0.01,
            timeout_seconds=1.0,
        )
    )

    assert result["condition_met"] is True
    assert result["timed_out"] is False
    assert result["poll_attempts"] == 2
    assert result["status"]["jobs"][0]["status"] == "completed"
