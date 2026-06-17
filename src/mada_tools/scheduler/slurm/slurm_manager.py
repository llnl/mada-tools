# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
SLURM job manager with queued `sbatch` submission and direct `srun` fallback.

This module accepts scheduler-ready run manifests and sweep-summary payloads,
writes per-run batch scripts, submits them to Slurm, and refreshes status from
`squeue`/`sacct`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from mada_tools.scheduler.base_manager import MADABaseJobManager
from mada_tools.simulation.simutils.models import RunInstance

LOG = logging.getLogger(__name__)

_SBATCH_JOB_ID_PATTERN = re.compile(r"Submitted batch job (?P<job_id>\d+)")
_TERMINAL_JOB_STATUSES = {"completed", "failed", "unknown"}
_RUNNING_JOB_STATUSES = {"running"}


@dataclass
class SlurmJobRecord:
    """
    One tracked run submitted through the Slurm backend.

    Attributes:
        local_job_id: Local MADA tracking ID.
        run_id: Run identifier from the scheduler manifest.
        run_location: Working directory for the run.
        status: Normalized job status.
        stdout_path: Path to the run stdout log.
        stderr_path: Path to the run stderr log.
        slurm_job_id: Real Slurm job ID when submitted through `sbatch`.
        script_path: Generated batch script path for queued jobs.
        raw_state: Raw Slurm job state from scheduler query.
        exit_code: Job exit code if completed.
        error_message: Error message if submission or execution failed.
        submitted_at: Timestamp when job was submitted.
        started_at: Timestamp when job started running.
        ended_at: Timestamp when job finished.

    Methods:
        to_dict: Return a JSON-serializable job record.
    """

    local_job_id: str
    run_id: str
    run_location: str
    status: str
    stdout_path: str
    stderr_path: str
    slurm_job_id: Optional[str] = None
    script_path: Optional[str] = None
    raw_state: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    submitted_at: Optional[float] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the job record.

        Returns:
            Dictionary containing all job record fields.
        """
        return asdict(self)


@dataclass
class SlurmJobSetRecord:
    """
    One tracked collection of runs submitted together.

    Attributes:
        job_set_id: Local MADA tracking ID for the submitted collection.
        submission_mode: Execution mode, such as queued `sbatch` or direct fallback.
        total_runs: Number of runs in the collection.
        requested_resources: Scheduler resource request used for submission.
        submitted_at: Submission timestamp.
        jobs: Per-run job records.
        max_parallel: Direct execution concurrency limit, if applicable.
        error: Collection-level error message, if any.
    """

    job_set_id: str
    submission_mode: str
    total_runs: int
    requested_resources: Dict[str, Any]
    submitted_at: float
    jobs: list[SlurmJobRecord] = field(default_factory=list)
    max_parallel: Optional[int] = None
    error: Optional[str] = None


class SlurmJobManager(MADABaseJobManager):
    """
    Slurm job manager that supports queued `sbatch` and direct `srun` execution.

    Attributes:
        aggregate_manifest_fields: Accepted aggregate manifest reference fields.
        per_run_manifest_fields: Accepted per-run manifest reference fields.
        job_sets: Local MADA job set ID to Slurm job set metadata mapping.
        sbatch_available: Whether `sbatch` is available on this host.
        srun_available: Whether `srun` is available on this host.
        squeue_available: Whether `squeue` is available on this host.
        sacct_available: Whether `sacct` is available on this host.

    Methods:
        submit_jobs: Submit generated run manifests through `sbatch` by default,
            or execute directly when `blocking=True`.
        get_job_status: Refresh and return tracked Slurm job status.
        continuously_check_job_status: Poll Slurm status until a bounded wait
            condition is met.
        run_command: Execute one command through `srun`.
        list_queue: Return current `squeue` output.
        get_cluster_info: Return current `sinfo` output.
    """

    aggregate_manifest_fields = (
        "aggregate_scheduler_manifest_file",
        "aggregate_slurm_manifest_file",
    )
    per_run_manifest_fields = (
        "scheduler_manifest_file",
        "slurm_manifest_file",
    )

    def __init__(self):
        super().__init__()

        self.job_sets: Dict[str, SlurmJobSetRecord] = {}
        self.job_counter = 0
        self.job_set_counter = 0
        self.jobs_lock = threading.Lock()

        self.sbatch_available = self._command_available(["sbatch", "--help"])
        self.srun_available = self._command_available(["srun", "--help"])
        self.squeue_available = self._command_available(["squeue", "--help"])
        self.sacct_available = self._command_available(["sacct", "--help"])

        LOG.info(
            "SlurmJobManager initialized "
            "(sbatch_available=%s, srun_available=%s, squeue_available=%s, sacct_available=%s)",
            self.sbatch_available,
            self.srun_available,
            self.squeue_available,
            self.sacct_available,
        )

    def stage(
        self,
        dims: int,
        num_samples: int,
        lower_bounds: List[float],
        upper_bounds: List[float],
        output_dir: str,
        parameter_file: str,
    ) -> Tuple[bool, str]:
        """Staging is handled by simulation servers, not the scheduler.

        Args:
            dims: Number of parameter dimensions.
            num_samples: Number of parameter sets to generate.
            lower_bounds: Lower bounds for each dimension.
            upper_bounds: Upper bounds for each dimension.
            output_dir: Directory for output files.
            parameter_file: Name of parameter file.

        Returns:
            Tuple of (False, error_message) since staging is not supported.
        """
        return False, "Staging should be done by simulation servers. Use submission tools instead."

    def execute(self) -> Generator[str, None, None]:
        """The Slurm backend does not support scheduler-side staging/execute flow.

        Returns:
            Generator yielding error message.
        """
        yield (
            "Error: Use `submit_jobs(blocking=False)` for queued jobs "
            "or `submit_jobs(blocking=True)` for direct debugging."
        )

    def submit_jobs(
        self,
        run_info_json: str,
        *,
        blocking: bool = False,
        nodes: int = 1,
        tasks: int = 1,
        time_limit: str = "01:00:00",
        account: Optional[str] = None,
        partition: Optional[str] = None,
        exclusive: bool = False,
        cpus_per_task: Optional[int] = None,
        job_name_prefix: str = "mada",
    ) -> Tuple[bool, str]:
        """Submit batch jobs from a run manifest file or JSON string.

        This is the primary method for submitting generated simulation runs. It accepts
        run manifests in multiple formats: inline JSON with {"runs": [...]}, a bare list
        like run_instances.json, or a file path to either format.

        Args:
            run_info_json: JSON string, list, or file path (e.g., "run_instances.json").
            blocking: If False (default), submit to queue via sbatch and return immediately.
                      If True, use direct execution for small debugging runs (not for production).
            nodes: Number of nodes per job.
            tasks: Number of tasks per job.
            time_limit: Time limit string (e.g., "01:00:00").
            account: Slurm account name.
            partition: Slurm partition name.
            exclusive: Whether to request exclusive node access.
            cpus_per_task: Number of CPUs per task.
            job_name_prefix: Prefix for job names.

        Returns:
            Tuple of (success, payload) where payload is JSON submission summary.
        """
        if blocking:
            # Use direct execution with limited parallelism for debugging
            return self._execute_direct(run_info_json, max_parallel=32)
        else:
            # Use sbatch for queued submission (production mode)
            return self._submit_batch(
                run_info_json,
                nodes=nodes,
                tasks=tasks,
                time_limit=time_limit,
                account=account,
                partition=partition,
                exclusive=exclusive,
                cpus_per_task=cpus_per_task,
                job_name_prefix=job_name_prefix,
            )

    def submit_jobs_async(
        self,
        run_info_json: str,
        *,
        nodes: int = 1,
        tasks: int = 1,
        time_limit: str = "01:00:00",
        account: Optional[str] = None,
        partition: Optional[str] = None,
        exclusive: bool = False,
        cpus_per_task: Optional[int] = None,
        job_name_prefix: str = "mada",
    ) -> Tuple[bool, str]:
        """Submit each run as a queued Slurm batch job and return immediately."""
        return self.submit_jobs(
            run_info_json,
            blocking=False,
            nodes=nodes,
            tasks=tasks,
            time_limit=time_limit,
            account=account,
            partition=partition,
            exclusive=exclusive,
            cpus_per_task=cpus_per_task,
            job_name_prefix=job_name_prefix,
        )

    def _submit_batch(
        self,
        run_info_json: str,
        *,
        nodes: int = 1,
        tasks: int = 1,
        time_limit: str = "01:00:00",
        account: Optional[str] = None,
        partition: Optional[str] = None,
        exclusive: bool = False,
        cpus_per_task: Optional[int] = None,
        job_name_prefix: str = "mada",
    ) -> Tuple[bool, str]:
        """Submit each run as a queued Slurm batch job via sbatch."""
        if not self.sbatch_available:
            return False, "Slurm `sbatch` is not available in the current runtime environment."

        try:
            runs = self._load_runs(run_info_json)
            self._validate_submission_request(
                nodes=nodes,
                tasks=tasks,
                time_limit=time_limit,
                cpus_per_task=cpus_per_task,
                job_name_prefix=job_name_prefix,
            )
        except ValueError as exc:
            return False, str(exc)
        except json.JSONDecodeError:
            return False, "Invalid JSON format"
        except Exception as exc:
            return False, f"Error loading runs: {exc}"

        requested_resources = {
            "nodes": nodes,
            "tasks": tasks,
            "time_limit": time_limit,
            "account": account,
            "partition": partition,
            "exclusive": exclusive,
            "cpus_per_task": cpus_per_task,
            "job_name_prefix": job_name_prefix,
        }

        with self.jobs_lock:
            self.job_set_counter += 1
            job_set_id = f"jobset_{self.job_set_counter:06d}"

        job_set = SlurmJobSetRecord(
            job_set_id=job_set_id,
            submission_mode="sbatch",
            total_runs=len(runs),
            requested_resources=requested_resources,
            submitted_at=time.time(),
        )

        response_jobs: list[Dict[str, Any]] = []
        failed_jobs: list[Dict[str, Any]] = []

        for run in runs:
            job_record = self._submit_single_batch_run(
                run,
                nodes=nodes,
                tasks=tasks,
                time_limit=time_limit,
                account=account,
                partition=partition,
                exclusive=exclusive,
                cpus_per_task=cpus_per_task,
                job_name_prefix=job_name_prefix,
            )
            job_set.jobs.append(job_record)

            job_info = {
                "job_id": job_record.local_job_id,
                "slurm_job_id": job_record.slurm_job_id,
                "run_id": job_record.run_id,
                "run_location": job_record.run_location,
                "status": job_record.status,
                "stdout_path": job_record.stdout_path,
                "stderr_path": job_record.stderr_path,
                "sbatch_script": job_record.script_path,
                "error_message": job_record.error_message,
            }
            response_jobs.append(job_info)

            if job_record.status == "failed":
                failed_jobs.append(
                    {
                        "job_id": job_record.local_job_id,
                        "slurm_job_id": job_record.slurm_job_id,
                        "run_id": job_record.run_id,
                        "run_location": job_record.run_location,
                        "error_message": job_record.error_message,
                    }
                )

        with self.jobs_lock:
            self.job_sets[job_set_id] = job_set

        result = {
            "job_set_id": job_set_id,
            "submission_mode": "sbatch",
            "total_runs": len(runs),
            "submitted_jobs": len(runs) - len(failed_jobs),
            "failed_submissions": len(failed_jobs),
            "failed_jobs": failed_jobs,
            "requested_resources": requested_resources,
            "jobs": response_jobs,
        }

        if len(failed_jobs) == len(runs):
            return False, json.dumps(result, indent=2)
        return True, json.dumps(result, indent=2)

    def _execute_direct(
        self,
        run_info_json: str,
        *,
        max_parallel: int = 32,
    ) -> Tuple[bool, str]:
        """Execute runs directly with `srun` or raw subprocess as a fallback."""
        try:
            runs = self._load_runs(run_info_json)
            if not isinstance(max_parallel, int) or max_parallel <= 0:
                raise ValueError("`max_parallel` must be a positive integer.")
        except ValueError as exc:
            return False, str(exc)
        except json.JSONDecodeError:
            return False, "Invalid JSON format"
        except Exception as exc:
            return False, f"Error loading runs: {exc}"

        with self.jobs_lock:
            self.job_set_counter += 1
            job_set_id = f"jobset_{self.job_set_counter:06d}"

        job_set = SlurmJobSetRecord(
            job_set_id=job_set_id,
            submission_mode="direct",
            total_runs=len(runs),
            requested_resources={
                "max_parallel": min(len(runs), max_parallel),
                "launcher": "srun" if self.srun_available else "direct",
            },
            submitted_at=time.time(),
            max_parallel=min(len(runs), max_parallel),
        )

        for run in runs:
            stdout_path, stderr_path = self._output_paths(run)
            job_set.jobs.append(
                SlurmJobRecord(
                    local_job_id=self._next_job_id(),
                    run_id=run.id,
                    run_location=run.run_location,
                    status="pending",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    submitted_at=time.time(),
                )
            )

        with self.jobs_lock:
            self.job_sets[job_set_id] = job_set

        thread = threading.Thread(
            target=self._execute_job_set_direct,
            args=(job_set_id, runs, min(len(runs), max_parallel)),
            daemon=True,
        )
        thread.start()

        result = {
            "job_set_id": job_set_id,
            "submission_mode": "direct",
            "total_runs": len(runs),
            "max_parallel": min(len(runs), max_parallel),
            "status": "submitted",
        }
        return True, json.dumps(result, indent=2)

    def get_job_status(
        self,
        job_set_id: Optional[str] = None,
        slurm_job_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Return scheduler-backed status for one job set, one Slurm job, or all job sets.

        Args:
            job_set_id: Local job set ID to query.
            slurm_job_id: Slurm job ID to query directly.

        Returns:
            Tuple of (success, JSON string containing job status information).
        """
        if job_set_id and slurm_job_id:
            return (
                False,
                json.dumps(
                    {"error": "Pass either `job_set_id` or `slurm_job_id`, not both."},
                    indent=2,
                ),
            )

        if slurm_job_id:
            result = self._get_single_slurm_job_status(slurm_job_id)
            return (True, result)

        with self.jobs_lock:
            if job_set_id:
                job_set = self.job_sets.get(job_set_id)
                if job_set is None:
                    return (False, json.dumps({"error": f"Job set {job_set_id} not found"}, indent=2))
                job_sets = [job_set]
            else:
                job_sets = list(self.job_sets.values())

        for job_set in job_sets:
            self._refresh_job_set_status(job_set)

        if job_set_id:
            return (True, json.dumps(self._job_set_summary(job_sets[0]), indent=2))

        return (
            True,
            json.dumps(
                {
                    "total_job_sets": len(job_sets),
                    "job_sets": [self._job_set_summary(job_set) for job_set in job_sets],
                },
                indent=2,
            ),
        )

    def continuously_check_job_status(
        self,
        job_set_id: Optional[str] = None,
        slurm_job_id: Optional[str] = None,
        *,
        wait_until: str = "terminal",
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 3600.0,
    ) -> Tuple[bool, str]:
        """
        Poll Slurm job status until a bounded wait condition is met.

        Args:
            job_set_id: Job set ID to monitor. If not provided, monitors all tracked job sets.
            slurm_job_id: Real Slurm job ID to monitor. Mutually exclusive with `job_set_id`.
            wait_until: `terminal` waits for selected jobs to finish; `any_running`
                returns once any selected job is running, or when all selected jobs
                have already reached terminal states.
            poll_interval_seconds: Seconds between status checks.
            timeout_seconds: Maximum seconds to wait before returning.

        Returns:
            Tuple of (success, JSON containing polling metadata plus the last status response).
        """
        result = self._poll_status_until(
            status_reader=lambda: self.get_job_status(job_set_id=job_set_id, slurm_job_id=slurm_job_id)[1],
            status_extractor=self._extract_statuses_from_status_payload,
            terminal_statuses=_TERMINAL_JOB_STATUSES,
            running_statuses=_RUNNING_JOB_STATUSES,
            wait_until=wait_until,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        return (True, result)

    def _submit_single_batch_run(
        self,
        run: RunInstance,
        *,
        nodes: int,
        tasks: int,
        time_limit: str,
        account: Optional[str],
        partition: Optional[str],
        exclusive: bool,
        cpus_per_task: Optional[int],
        job_name_prefix: str,
    ) -> SlurmJobRecord:
        """Write a batch script for one run and submit it with `sbatch`."""
        local_job_id = self._next_job_id()
        stdout_path, stderr_path = self._output_paths(run)
        submitted_at = time.time()

        try:
            command_tokens = self._command_tokens_for_run(run)
            run_directory = Path(run.run_location).expanduser().resolve()
            run_directory.mkdir(parents=True, exist_ok=True)

            script_path = self._write_sbatch_script(
                run,
                command_tokens=command_tokens,
                nodes=nodes,
                tasks=tasks,
                time_limit=time_limit,
                account=account,
                partition=partition,
                exclusive=exclusive,
                cpus_per_task=cpus_per_task,
                job_name_prefix=job_name_prefix,
            )

            result = subprocess.run(
                ["sbatch", str(script_path)],
                cwd=str(run_directory),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "sbatch failed")

            slurm_job_id = self._parse_sbatch_job_id(result.stdout)
            if slurm_job_id is None:
                raise RuntimeError(f"Could not parse Slurm job ID from sbatch output: {result.stdout!r}")

            return SlurmJobRecord(
                local_job_id=local_job_id,
                run_id=run.id,
                run_location=run.run_location,
                status="submitted",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                slurm_job_id=slurm_job_id,
                script_path=str(script_path),
                submitted_at=submitted_at,
            )
        except Exception as exc:
            LOG.error("Failed to submit Slurm batch job for run %s: %s", run.id, exc)
            return SlurmJobRecord(
                local_job_id=local_job_id,
                run_id=run.id,
                run_location=run.run_location,
                status="failed",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                error_message=str(exc),
                submitted_at=submitted_at,
            )

    def _write_sbatch_script(
        self,
        run: RunInstance,
        *,
        command_tokens: list[str],
        nodes: int,
        tasks: int,
        time_limit: str,
        account: Optional[str],
        partition: Optional[str],
        exclusive: bool,
        cpus_per_task: Optional[int],
        job_name_prefix: str,
    ) -> Path:
        """Write one self-contained Slurm batch script for the run."""
        run_directory = Path(run.run_location).expanduser().resolve()
        run_directory.mkdir(parents=True, exist_ok=True)

        script_path = run_directory / "submit_run.sbatch"
        stdout_path, stderr_path = self._output_paths(run)
        job_name = f"{job_name_prefix}_run_{run.id}" if job_name_prefix else f"run_{run.id}"

        script_lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --time={time_limit}",
            f"#SBATCH --nodes={nodes}",
            f"#SBATCH --ntasks={tasks}",
            f"#SBATCH --output={stdout_path}",
            f"#SBATCH --error={stderr_path}",
        ]
        if account:
            script_lines.append(f"#SBATCH --account={account}")
        if partition:
            script_lines.append(f"#SBATCH --partition={partition}")
        if exclusive:
            script_lines.append("#SBATCH --exclusive")
        if cpus_per_task is not None:
            script_lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")

        # Keep logs beside the run directory so queue-visible output and local
        # postmortem inspection both point to the same files.
        script_lines.extend(
            [
                "",
                "set -e",
                f"cd {shlex.quote(str(run_directory))}",
                f"srun -N {nodes} -n {tasks} {shlex.join(command_tokens)}",
                "",
            ]
        )

        script_path.write_text("\n".join(script_lines), encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _get_single_slurm_job_status(self, slurm_job_id: str) -> str:
        """Return one tracked job by real Slurm job ID."""
        with self.jobs_lock:
            matches = [
                (job_set, job)
                for job_set in self.job_sets.values()
                for job in job_set.jobs
                if job.slurm_job_id == slurm_job_id
            ]

        if not matches:
            return json.dumps({"error": f"Slurm job {slurm_job_id} not found"}, indent=2)

        job_set, job = matches[0]
        self._refresh_job_set_status(job_set)
        return json.dumps(
            {
                "job_set_id": job_set.job_set_id,
                "submission_mode": job_set.submission_mode,
                **job.to_dict(),
            },
            indent=2,
        )

    def _refresh_job_set_status(self, job_set: SlurmJobSetRecord) -> None:
        """Refresh one job set in place using scheduler data when possible."""
        if job_set.submission_mode != "sbatch":
            return

        active_jobs = [
            job
            for job in job_set.jobs
            if job.slurm_job_id and (job.status not in _TERMINAL_JOB_STATUSES or job.exit_code is None)
        ]
        if not active_jobs:
            return

        slurm_job_ids = [job.slurm_job_id for job in active_jobs if job.slurm_job_id]
        squeue_states = self._query_squeue_states(slurm_job_ids)
        sacct_states = self._query_sacct_states(slurm_job_ids)

        now = time.time()
        for job in active_jobs:
            if not job.slurm_job_id:
                continue

            squeue_state = squeue_states.get(job.slurm_job_id)
            if squeue_state is not None:
                job.raw_state = squeue_state
                job.status = self._map_slurm_state_to_status(squeue_state)
                if job.status == "running" and job.started_at is None:
                    job.started_at = now
                continue

            sacct_state = sacct_states.get(job.slurm_job_id)
            if sacct_state is not None:
                raw_state = sacct_state.get("state")
                job.raw_state = raw_state
                job.status = self._map_slurm_state_to_status(raw_state)
                job.exit_code = self._parse_exit_code(sacct_state.get("exit_code"))
                if job.status == "running" and job.started_at is None:
                    job.started_at = now
                if job.status in {"completed", "failed"} and job.ended_at is None:
                    job.ended_at = now
                continue

            if job.status == "running":
                job.status = "unknown"
                job.raw_state = "MISSING_FROM_SCHEDULER"
                if job.ended_at is None:
                    job.ended_at = now

    def _query_squeue_states(self, slurm_job_ids: list[str]) -> Dict[str, str]:
        """Query `squeue` for active jobs and return `job_id -> state`."""
        if not self.squeue_available or not slurm_job_ids:
            return {}

        states: Dict[str, str] = {}
        for chunk in self._chunked(slurm_job_ids, 200):
            result = subprocess.run(
                ["squeue", "-h", "-o", "%i|%T", "-j", ",".join(chunk)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                LOG.warning("squeue failed while checking Slurm jobs: %s", result.stderr.strip())
                continue
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                job_id, _, state = line.partition("|")
                if job_id and state:
                    states[job_id.strip()] = state.strip()
        return states

    def _query_sacct_states(self, slurm_job_ids: list[str]) -> Dict[str, Dict[str, Optional[str]]]:
        """Query `sacct` for jobs that already left the queue."""
        if not self.sacct_available or not slurm_job_ids:
            return {}

        states: Dict[str, Dict[str, Optional[str]]] = {}
        for chunk in self._chunked(slurm_job_ids, 200):
            result = subprocess.run(
                [
                    "sacct",
                    "-n",
                    "-P",
                    "-j",
                    ",".join(chunk),
                    "--format=JobIDRaw,State,ExitCode,Elapsed",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                LOG.warning("sacct failed while checking Slurm jobs: %s", result.stderr.strip())
                continue
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                fields = line.split("|")
                if len(fields) < 4:
                    continue
                job_id = fields[0].strip()
                if not job_id.isdigit():
                    continue
                states[job_id] = {
                    "state": fields[1].strip() or None,
                    "exit_code": fields[2].strip() or None,
                    "elapsed": fields[3].strip() or None,
                }
        return states

    def _execute_job_set_direct(
        self,
        job_set_id: str,
        runs: List[RunInstance],
        max_parallel: int,
    ) -> None:
        """Execute a direct, non-queued job set in the background."""
        LOG.info(
            "Starting direct Slurm execution of job set %s with %d runs",
            job_set_id,
            len(runs),
        )

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_to_run = {executor.submit(self._execute_single_run_direct, job_set_id, run): run for run in runs}
            for future in as_completed(future_to_run):
                run = future_to_run[future]
                try:
                    future.result()
                    LOG.info("Direct Slurm execution finished for run %s", run.id)
                except Exception as exc:
                    LOG.error("Direct Slurm execution failed for run %s: %s", run.id, exc)

    def _execute_single_run_direct(self, job_set_id: str, run: RunInstance) -> None:
        """Execute a single run through `srun` or direct subprocess fallback."""
        job_record = self._find_job_record(job_set_id, run.id)
        if job_record is None:
            raise RuntimeError(f"Could not find tracked job for run {run.id}")

        command_tokens = self._command_tokens_for_run(run)
        os.makedirs(run.run_location, exist_ok=True)

        with self.jobs_lock:
            job_record.status = "running"
            job_record.started_at = time.time()

        try:
            if self.srun_available:
                cmd = ["srun", "-N1", "-n1", *command_tokens]
            else:
                cmd = command_tokens

            with open(job_record.stdout_path, "w", encoding="utf-8") as stdout_file:
                with open(job_record.stderr_path, "w", encoding="utf-8") as stderr_file:
                    result = subprocess.run(
                        cmd,
                        cwd=run.run_location,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        timeout=3600,
                    )

            with self.jobs_lock:
                job_record.exit_code = result.returncode
                job_record.ended_at = time.time()
                if result.returncode == 0:
                    job_record.status = "completed"
                else:
                    job_record.status = "failed"
                    job_record.error_message = f"Process exited with code {result.returncode}"
        except subprocess.TimeoutExpired:
            with self.jobs_lock:
                job_record.status = "failed"
                job_record.error_message = "Run timed out"
                job_record.ended_at = time.time()
        except Exception as exc:
            with self.jobs_lock:
                job_record.status = "failed"
                job_record.error_message = str(exc)
                job_record.ended_at = time.time()

    def _job_set_summary(self, job_set: SlurmJobSetRecord) -> Dict[str, Any]:
        """Return a JSON-serializable summary for one job set."""
        jobs = [job.to_dict() for job in job_set.jobs]
        counts = {
            "submitted": sum(1 for job in job_set.jobs if job.status == "submitted"),
            "pending": sum(1 for job in job_set.jobs if job.status == "pending"),
            "running": sum(1 for job in job_set.jobs if job.status == "running"),
            "completed": sum(1 for job in job_set.jobs if job.status == "completed"),
            "failed": sum(1 for job in job_set.jobs if job.status == "failed"),
            "unknown": sum(1 for job in job_set.jobs if job.status == "unknown"),
        }

        if counts["failed"] and counts["completed"] + counts["failed"] == job_set.total_runs:
            overall_status = "failed"
        elif counts["completed"] == job_set.total_runs:
            overall_status = "completed"
        elif counts["running"] or counts["pending"] or counts["submitted"]:
            overall_status = "running"
        elif counts["unknown"]:
            overall_status = "unknown"
        else:
            overall_status = "submitted"

        result = {
            "job_set_id": job_set.job_set_id,
            "submission_mode": job_set.submission_mode,
            "total_runs": job_set.total_runs,
            "status": overall_status,
            "submitted_at": job_set.submitted_at,
            "requested_resources": job_set.requested_resources,
            **counts,
            "jobs": jobs,
        }
        if job_set.max_parallel is not None:
            result["max_parallel"] = job_set.max_parallel
        if job_set.error is not None:
            result["error"] = job_set.error
        return result

    def _extract_statuses_from_status_payload(self, payload: Dict[str, Any]) -> list[str]:
        """
        Extract normalized job statuses from a Slurm status response.

        Args:
            payload: Decoded JSON response from `get_job_status`.

        Returns:
            A list of normalized status strings.
        """
        job_sets = payload.get("job_sets")
        if isinstance(job_sets, list):
            statuses: list[str] = []
            for job_set in job_sets:
                if isinstance(job_set, dict):
                    statuses.extend(self._extract_statuses_from_job_set_payload(job_set))
            return statuses

        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            return self._extract_statuses_from_job_set_payload(payload)

        status = payload.get("status")
        if isinstance(status, str):
            return [status]
        return []

    @staticmethod
    def _extract_statuses_from_job_set_payload(payload: Dict[str, Any]) -> list[str]:
        """
        Extract per-run statuses from one Slurm job-set response.

        Args:
            payload: Decoded Slurm job-set status payload.

        Returns:
            A list of normalized per-run status strings.
        """
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            status = payload.get("status")
            return [status] if isinstance(status, str) else []
        return [job["status"] for job in jobs if isinstance(job, dict) and isinstance(job.get("status"), str)]

    def _find_job_record(self, job_set_id: str, run_id: str) -> Optional[SlurmJobRecord]:
        """Find one tracked job inside one job set."""
        with self.jobs_lock:
            job_set = self.job_sets.get(job_set_id)
            if job_set is None:
                return None
            for job in job_set.jobs:
                if job.run_id == run_id:
                    return job
        return None

    def _validate_submission_request(
        self,
        *,
        nodes: int,
        tasks: int,
        time_limit: str,
        cpus_per_task: Optional[int],
        job_name_prefix: str,
    ) -> None:
        """Validate queued submission arguments before touching the filesystem."""
        if not isinstance(nodes, int) or nodes <= 0:
            raise ValueError("`nodes` must be a positive integer.")
        if not isinstance(tasks, int) or tasks <= 0:
            raise ValueError("`tasks` must be a positive integer.")
        if not isinstance(time_limit, str) or not time_limit.strip():
            raise ValueError("`time_limit` must be a non-empty string.")
        if cpus_per_task is not None and (not isinstance(cpus_per_task, int) or cpus_per_task <= 0):
            raise ValueError("`cpus_per_task` must be a positive integer when provided.")
        if not isinstance(job_name_prefix, str):
            raise ValueError("`job_name_prefix` must be a string.")

    def _command_available(self, command: list[str]) -> bool:
        """Return whether a scheduler command appears available."""
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as exc:
            LOG.debug("Command probe failed for %s: %s", command, exc)
            return False

    def _parse_sbatch_job_id(self, sbatch_output: str) -> Optional[str]:
        """Parse the Slurm job ID from standard `sbatch` output."""
        match = _SBATCH_JOB_ID_PATTERN.search(sbatch_output)
        if match is None:
            return None
        return match.group("job_id")

    def _map_slurm_state_to_status(self, raw_state: Optional[str]) -> str:
        """Map Slurm state names to the scheduler server's normalized status set."""
        if raw_state is None:
            return "unknown"

        normalized = raw_state.strip().upper().split()[0].rstrip("+")
        if normalized in {"PENDING", "CONFIGURING", "REQUEUED", "SUSPENDED"}:
            return "pending"
        if normalized in {"RUNNING", "COMPLETING", "STAGE_OUT"}:
            return "running"
        if normalized == "COMPLETED":
            return "completed"
        if normalized in {
            "BOOT_FAIL",
            "CANCELLED",
            "DEADLINE",
            "FAILED",
            "NODE_FAIL",
            "OUT_OF_MEMORY",
            "PREEMPTED",
            "REVOKED",
            "STOPPED",
            "TIMEOUT",
        }:
            return "failed"
        return "unknown"

    def _parse_exit_code(self, raw_exit_code: Optional[str]) -> Optional[int]:
        """Parse the primary integer exit code from `sacct` output like `0:0`."""
        if raw_exit_code is None:
            return None
        try:
            return int(raw_exit_code.split(":", 1)[0])
        except (TypeError, ValueError):
            return None

    def _chunked(self, values: list[str], size: int) -> list[list[str]]:
        """Split a list into fixed-size chunks."""
        return [values[index : index + size] for index in range(0, len(values), size)]

    def submit_command(
        self, command: str, nodes: int, tasks: int, working_directory: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Submit one ad hoc command using `srun`.

        Use this for running a single known command, not for generated run manifests
        or parameter sweeps. For batch simulation runs, use `submit_jobs` instead.

        Args:
            command: Command to execute
            nodes: Number of nodes (default: 1)
            tasks: Number of tasks (default: 1)
            working_directory: Working directory for the command (optional)

        Returns:
            Tuple of (success, command output and status)
        """
        # Build srun command
        srun_cmd = ["srun", f"-N{nodes}", f"-n{tasks}"] + command.split()

        # Execute command
        result = subprocess.run(
            srun_cmd,
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=3600,  # 60 minute timeout for single commands
        )

        output = []
        output.append(f"Command: {' '.join(srun_cmd)}")
        output.append(f"Exit code: {result.returncode}")

        if result.stdout:
            output.append(f"Stdout:\n{result.stdout}")
        if result.stderr:
            output.append(f"Stderr:\n{result.stderr}")

        return True, "\n".join(output)

    def list_queue(self) -> Tuple[bool, str]:
        """
        List all jobs in the SLURM queue using squeue.

        Returns:
            A tuple of (success, status message).
        """
        cmd = ["squeue"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, f"Queue status:\n{result.stdout}"
        else:
            return False, f"Failed to list queue: {result.stderr.strip()}"

    def get_cluster_info(self) -> Tuple[bool, str]:
        """
        Get information about the cluster nodes using sinfo.

        Returns:
            A tuple of (success, status message).
        """
        cmd = ["sinfo"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, f"Cluster information:\n{result.stdout}"
        else:
            return False, f"Failed to get cluster info: {result.stderr.strip()}"
