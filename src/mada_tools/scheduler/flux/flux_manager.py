# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Flux job manager with resource-aware submission and real Flux job tracking.

The public API in this module is responsible for turning staged run manifests
into Flux jobspecs, submitting them, and refreshing status from Flux instead of
inventing local queue state.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import shlex
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import flux
from flux.job import FluxExecutor, JobID, JobspecV1
from flux.job.list import JobList, get_job

from mada_tools.scheduler.base_manager import MADABaseJobManager
from mada_tools.shared.exceptions import ConfigurationError
from mada_tools.simulation.simutils.models import RunInstance

LOG = logging.getLogger(__name__)


class JobStatus(Enum):
    """Normalized job states exposed by the Flux MCP server."""

    SUBMITTED = "submitted"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


_TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.UNKNOWN.value,
}
_RUNNING_JOB_STATUSES = {JobStatus.RUNNING.value}


@dataclass
class JobInfo:
    """
    Tracked Flux job metadata.

    Attributes:
        job_id: Local MADA tracking ID.
        run_id: Run identifier from the scheduler manifest.
        run_location: Working directory for the run.
        job_name: Scheduler-visible Flux job name.
        status: Normalized job status.
        flux_job_id: Integer Flux job ID used by Flux Python APIs.
        flux_job_id_f58: Flux CLI-friendly encoded job ID.
        raw_state: Raw Flux job state from scheduler query.
        raw_result: Raw Flux job result status.
        exit_code: Job exit code if completed.
        error_message: Error message if submission or execution failed.
        submitted_at: Timestamp when job was submitted.
        start_time: Timestamp when job started running.
        end_time: Timestamp when job finished.
        stdout_path: Path to the run stdout log.
        stderr_path: Path to the run stderr log.
        queue: Flux queue name if specified.
        bank: Flux bank/account name if specified.
        nodelist: Comma-separated list of nodes where job ran.
        flux_reported_nodes: Number of nodes reported by Flux.
        flux_reported_tasks: Number of tasks reported by Flux.
        flux_reported_cores: Number of cores reported by Flux.
        time_limit: Time limit string for the job.
        requested_nodes: Number of nodes requested.
        requested_tasks: Number of tasks requested.
        requested_cores_per_task: Number of cores per task requested.
        requested_gpus_per_task: Number of GPUs per task requested.
        exclusive: Whether exclusive node access was requested.
        runtime: Computed job runtime in seconds (property, available after completion).

    Methods:
        to_dict: Return a JSON-serializable job record.
    """

    job_id: str
    run_id: str
    run_location: str
    job_name: str
    status: JobStatus
    flux_job_id: Optional[int] = None
    flux_job_id_f58: Optional[str] = None
    raw_state: Optional[str] = None
    raw_result: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None
    submitted_at: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    queue: Optional[str] = None
    bank: Optional[str] = None
    nodelist: Optional[str] = None
    flux_reported_nodes: Optional[int] = None
    flux_reported_tasks: Optional[int] = None
    flux_reported_cores: Optional[int] = None
    time_limit: Optional[str] = None
    requested_nodes: Optional[int] = None
    requested_tasks: Optional[int] = None
    requested_cores_per_task: Optional[int] = None
    requested_gpus_per_task: Optional[int] = None
    exclusive: bool = False

    @property
    def runtime(self) -> Optional[float]:
        """Return completed job runtime in seconds when start and end times are known.

        Returns:
            Job runtime in seconds, or None if start/end times are not available.
        """
        if self.start_time is None or self.end_time is None:
            return None
        return max(0.0, self.end_time - self.start_time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable job record.

        Returns:
            Dictionary containing all job metadata fields.
        """
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "run_location": self.run_location,
            "job_name": self.job_name,
            "status": self.status.value,
            "flux_job_id": self.flux_job_id,
            "flux_job_id_f58": self.flux_job_id_f58,
            "raw_state": self.raw_state,
            "raw_result": self.raw_result,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "submitted_at": self.submitted_at,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "runtime": self.runtime,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "queue": self.queue,
            "bank": self.bank,
            "nodelist": self.nodelist,
            "time_limit": self.time_limit,
            "requested_resources": {
                "nodes": self.requested_nodes,
                "tasks": self.requested_tasks,
                "cores_per_task": self.requested_cores_per_task,
                "gpus_per_task": self.requested_gpus_per_task,
                "exclusive": self.exclusive,
            },
            "flux_reported_resources": {
                "nodes": self.flux_reported_nodes,
                "tasks": self.flux_reported_tasks,
                "cores": self.flux_reported_cores,
            },
            "exclusive": self.exclusive,
        }


class FluxJobManager(MADABaseJobManager):
    """
    Flux-backed scheduler for MADA.

    The async submission path records real Flux job IDs immediately and refreshes
    state from Flux itself instead of inventing queue IDs.

    Attributes:
        aggregate_manifest_fields: Accepted aggregate manifest reference fields.
        per_run_manifest_fields: Accepted per-run manifest reference fields.
        jobs: Local MADA job ID to Flux job metadata mapping.
        use_persistent_executor: Whether explicit FluxExecutor mode is enabled.
        flux_url: Flux broker URI or handle target, if configured.

    Methods:
        submit_command: Submit one command as a Flux job.
        submit_jobs: Submit generated run manifests and return real Flux job IDs.
        execute_jobs_from_json: Submit generated runs and wait for completion.
        get_job_status: Refresh and return tracked or direct Flux job status.
        continuously_check_job_status: Poll Flux status until a bounded wait
            condition is met.
        start_persistent_executor: Start optional shared FluxExecutor mode.
        stop_persistent_executor: Stop optional shared FluxExecutor mode.
    """

    aggregate_manifest_fields = (
        "aggregate_scheduler_manifest_file",
        "aggregate_flux_manifest_file",
    )
    per_run_manifest_fields = (
        "scheduler_manifest_file",
        "flux_manifest_file",
    )

    def __init__(self):
        super().__init__()
        # Preserve the raw run payload for the legacy load/execute workflow.
        self.run_info_json: Optional[str] = None
        self.loaded_runs: Optional[list[RunInstance]] = None

        # Optional shared FluxExecutor mode. Direct submit remains the default
        # path so login-node submissions return real Flux job IDs immediately.
        self.persistent_executor = None

        # Job tracking system: local MADA job ID -> scheduler-backed job record.
        self.jobs: Dict[str, JobInfo] = {}
        self.job_counter = 0
        self.jobs_lock = threading.Lock()

        self.use_persistent_executor = os.getenv("FLUX_USE_PERSISTENT_EXECUTOR", "false").lower() == "true"
        self.flux_url = self._resolve_flux_url()

        # Open the Flux handle after server config has applied environment
        # variables, so FLUX_URI/FLUX_HANDLE settings are honored.
        try:
            self.flux_handle = self._open_flux_handle()
        except Exception as exc:
            raise ConfigurationError(f"Failed to connect to Flux: {exc}") from exc

        LOG.info(
            "FluxJobManager initialized (persistent_executor=%s, flux_url=%s)",
            self.use_persistent_executor,
            self.flux_url or "default",
        )

    def start_persistent_executor(self) -> Tuple[bool, str]:
        """Start a reusable FluxExecutor for explicit shared-executor mode.

        Returns:
            Tuple of (success, message) indicating whether the executor started.
        """
        if not self.use_persistent_executor:
            return False, "Persistent executor mode is disabled"
        if self.persistent_executor is not None:
            return True, "Persistent executor already running"

        try:
            self.persistent_executor = FluxExecutor(
                handle_args=self._executor_handle_args(),
            )
            self.persistent_executor.__enter__()
            return True, "Persistent executor started successfully"
        except Exception as exc:
            LOG.error("Failed to start persistent executor: %s", exc)
            return False, f"Failed to start persistent executor: {exc}"

    def stop_persistent_executor(self) -> Tuple[bool, str]:
        """Stop the reusable FluxExecutor if it was started.

        Returns:
            Tuple of (success, message) indicating whether the executor stopped.
        """
        if self.persistent_executor is None:
            return True, "No persistent executor to stop"

        try:
            self.persistent_executor.__exit__(None, None, None)
            self.persistent_executor = None
            return True, "Persistent executor stopped successfully"
        except Exception as exc:
            LOG.error("Failed to stop persistent executor: %s", exc)
            return False, f"Failed to stop persistent executor: {exc}"

    def stage(
        self,
        dims: int,
        num_samples: int,
        lower_bounds: List[float],
        upper_bounds: List[float],
        output_dir: str,
        parameter_file: str,
    ) -> Tuple[bool, str]:
        """Staging is handled by simulation servers, not the Flux scheduler.

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
        """Execute previously loaded run information synchronously.

        Returns:
            Generator yielding status messages during execution.
        """
        if self.loaded_runs is None:
            yield "Error: No run information loaded. Use load_run_info() first."
            return
        yield from self._execute_run_instances(self.loaded_runs)

    def load_run_info(self, run_info_json: str) -> Tuple[bool, str]:
        """Load run information from JSON for later execution.

        Args:
            run_info_json: JSON string or file path containing run information.

        Returns:
            Tuple of (success, message) indicating whether runs were loaded.
        """
        try:
            runs = self._load_runs(run_info_json)
            self.run_info_json = run_info_json
            self.loaded_runs = runs
            return True, f"Loaded run information for {len(runs)} runs"
        except json.JSONDecodeError as exc:
            return False, f"Invalid JSON format: {exc}"
        except Exception as exc:
            return False, f"Failed to load run info: {exc}"

    def execute_jobs_from_json(
        self,
        run_info_json: str,
        *,
        nodes: int = 1,
        tasks: int = 1,
        cores_per_task: int = 1,
        gpus_per_task: int = 0,
        time_limit: str = "1h",
        queue: Optional[str] = None,
        bank: Optional[str] = None,
        exclusive: bool = False,
        job_name_prefix: str = "mada",
        urgency: int = 16,
    ) -> Generator[str, None, None]:
        """Submit jobs and wait synchronously for completion.

        Args:
            run_info_json: JSON string or file path containing run information.
            nodes: Number of nodes per job.
            tasks: Number of tasks per job.
            cores_per_task: Number of cores per task.
            gpus_per_task: Number of GPUs per task.
            time_limit: Time limit string (e.g., "1h", "30m").
            queue: Flux queue name.
            bank: Flux bank/account name.
            exclusive: Whether to request exclusive node access.
            job_name_prefix: Prefix for job names.
            urgency: Flux urgency value (0-31).

        Returns:
            Generator yielding status messages during execution.
        """
        try:
            runs = self._load_runs(run_info_json)
        except Exception as exc:
            yield f"Failed to load run information: {exc}"
            return

        yield from self._execute_run_instances(
            runs,
            nodes=nodes,
            tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=gpus_per_task,
            time_limit=time_limit,
            queue=queue,
            bank=bank,
            exclusive=exclusive,
            job_name_prefix=job_name_prefix,
            urgency=urgency,
        )

    def _execute_run_instances(
        self,
        runs: list[RunInstance],
        *,
        nodes: int = 1,
        tasks: int = 1,
        cores_per_task: int = 1,
        gpus_per_task: int = 0,
        time_limit: str = "1h",
        queue: Optional[str] = None,
        bank: Optional[str] = None,
        exclusive: bool = False,
        job_name_prefix: str = "mada",
        urgency: int = 16,
    ) -> Generator[str, None, None]:
        """Submit run instances and wait synchronously for completion."""
        success, result = self._submit_run_instances(
            runs,
            nodes=nodes,
            tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=gpus_per_task,
            time_limit=time_limit,
            queue=queue,
            bank=bank,
            exclusive=exclusive,
            job_name_prefix=job_name_prefix,
            urgency=urgency,
        )
        if not success:
            yield f"Failed to submit jobs: {result}"
            return

        submission = json.loads(result)
        jobs = submission.get("jobs", [])
        yield (f"Submitted {submission.get('submitted_jobs', 0)}/{submission.get('total_runs', 0)} jobs to Flux")

        completed = 0
        failed = 0
        for job in jobs:
            local_job_id = job["job_id"]
            flux_job_id = job.get("flux_job_id")
            if flux_job_id is None:
                failed += 1
                yield f"Job {local_job_id} failed before Flux accepted it: {job.get('error_message')}"
                continue

            yield f"Submitted {local_job_id} as Flux job {job['flux_job_id_f58']} ({flux_job_id})"
            final_info = flux.job.result(self._open_flux_handle(), flux_job_id)
            final_payload = final_info.to_dict(filtered=False)

            with self.jobs_lock:
                tracked = self.jobs.get(local_job_id)
            if tracked is None:
                failed += 1
                yield f"Lost local tracking for Flux job {flux_job_id}"
                continue

            self._apply_job_query_data(tracked, final_payload)
            if tracked.status == JobStatus.COMPLETED:
                completed += 1
                yield f"Flux job {tracked.flux_job_id_f58} completed successfully"
            else:
                failed += 1
                yield (
                    f"Flux job {tracked.flux_job_id_f58} failed "
                    f"(result={tracked.raw_result}, exit_code={tracked.exit_code})"
                )

        yield f"Flux execution complete: {completed} succeeded, {failed} failed"

    def submit_command(
        self,
        command: str,
        *,
        working_directory: Optional[str] = None,
        nodes: int = 1,
        tasks: int = 1,
        cores_per_task: int = 1,
        gpus_per_task: int = 0,
        time_limit: str = "1h",
        queue: Optional[str] = None,
        bank: Optional[str] = None,
        exclusive: bool = False,
        job_name: Optional[str] = None,
        urgency: int = 16,
    ) -> Tuple[bool, str]:
        """Submit one arbitrary command as a single Flux job.

        Args:
            command: Shell command string to execute.
            working_directory: Directory to execute the command in.
            nodes: Number of nodes to request.
            tasks: Number of tasks to request.
            cores_per_task: Number of cores per task.
            gpus_per_task: Number of GPUs per task.
            time_limit: Time limit string (e.g., "1h", "30m").
            queue: Flux queue name.
            bank: Flux bank/account name.
            exclusive: Whether to request exclusive node access.
            job_name: Optional job name.
            urgency: Flux urgency value (0-31).

        Returns:
            Tuple of (success, payload) where payload is JSON job record or error.
        """
        if not isinstance(command, str) or not command.strip():
            return False, "`command` must be a non-empty string."

        try:
            self._validate_submission_request(
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                urgency=urgency,
            )
        except ValueError as exc:
            return False, str(exc)

        command_tokens = shlex.split(command)
        local_job_id = self._next_job_id()
        run_location = str(Path(working_directory or os.getcwd()).expanduser().resolve())
        resolved_job_name = job_name or f"mada_command_{local_job_id.split('_')[-1]}"

        job = self._submit_job_record(
            local_job_id=local_job_id,
            run_id=resolved_job_name,
            run_location=run_location,
            job_name=resolved_job_name,
            command_tokens=command_tokens,
            nodes=nodes,
            tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=gpus_per_task,
            time_limit=time_limit,
            queue=queue,
            bank=bank,
            exclusive=exclusive,
            urgency=urgency,
        )

        if job.status == JobStatus.FAILED:
            return False, job.error_message or "Flux submission failed."
        return True, json.dumps(job.to_dict(), indent=2)

    def submit_jobs(
        self,
        run_info_json: str,
        *,
        blocking: bool = False,
        nodes: int = 1,
        tasks: int = 1,
        cores_per_task: int = 1,
        gpus_per_task: int = 0,
        time_limit: str = "1h",
        queue: Optional[str] = None,
        bank: Optional[str] = None,
        exclusive: bool = False,
        job_name_prefix: str = "mada",
        urgency: int = 16,
    ) -> Tuple[bool, str]:
        """Submit batch jobs from a run manifest file or JSON string.

        This is the primary method for submitting generated simulation runs. It accepts
        run manifests in multiple formats: inline JSON with {"runs": [...]}, a bare list
        like run_instances.json, or a file path to either format.

        Args:
            run_info_json: JSON string, list, or file path (e.g., "run_instances.json").
            blocking: If False (default), submit jobs and return immediately with job IDs.
                      If True, submit jobs and wait for all to complete before returning.
            nodes: Number of nodes per job.
            tasks: Number of tasks per job.
            cores_per_task: Number of cores per task.
            gpus_per_task: Number of GPUs per task.
            time_limit: Time limit string (e.g., "1h", "30m").
            queue: Flux queue name.
            bank: Flux bank/account name.
            exclusive: Whether to request exclusive node access.
            job_name_prefix: Prefix for job names.
            urgency: Flux urgency value (0-31).

        Returns:
            Tuple of (success, payload) where payload is JSON with submission results.
            When blocking=False: immediate return with job IDs.
            When blocking=True: return after all jobs complete with final status.
        """
        try:
            runs = self._load_runs(run_info_json)
        except json.JSONDecodeError:
            return False, "Invalid JSON format"
        except Exception as exc:
            return False, f"Error loading run information: {exc}"

        if blocking:
            return self._submit_and_wait(
                runs,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                job_name_prefix=job_name_prefix,
                urgency=urgency,
            )
        else:
            return self._submit_run_instances(
                runs,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                job_name_prefix=job_name_prefix,
                urgency=urgency,
            )

    def submit_jobs_async(
        self,
        run_info_json: str,
        *,
        nodes: int = 1,
        tasks: int = 1,
        cores_per_task: int = 1,
        gpus_per_task: int = 0,
        time_limit: str = "1h",
        queue: Optional[str] = None,
        bank: Optional[str] = None,
        exclusive: bool = False,
        job_name_prefix: str = "mada",
        urgency: int = 16,
    ) -> Tuple[bool, str]:
        """Submit generated run manifests to Flux and return immediately."""
        return self.submit_jobs(
            run_info_json,
            blocking=False,
            nodes=nodes,
            tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=gpus_per_task,
            time_limit=time_limit,
            queue=queue,
            bank=bank,
            exclusive=exclusive,
            job_name_prefix=job_name_prefix,
            urgency=urgency,
        )

    def _submit_and_wait(
        self,
        runs: list[RunInstance],
        *,
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        queue: Optional[str],
        bank: Optional[str],
        exclusive: bool,
        job_name_prefix: str,
        urgency: int,
    ) -> Tuple[bool, str]:
        """Submit runs and wait for all to complete, returning final status."""
        success, result = self._submit_run_instances(
            runs,
            nodes=nodes,
            tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=gpus_per_task,
            time_limit=time_limit,
            queue=queue,
            bank=bank,
            exclusive=exclusive,
            job_name_prefix=job_name_prefix,
            urgency=urgency,
        )
        if not success:
            return False, result

        submission = json.loads(result)
        jobs = submission.get("jobs", [])

        completed = 0
        failed = 0
        job_results = []

        for job in jobs:
            local_job_id = job["job_id"]
            flux_job_id = job.get("flux_job_id")
            if flux_job_id is None:
                failed += 1
                job_results.append(
                    {
                        "job_id": local_job_id,
                        "status": "failed",
                        "error": job.get("error_message", "Failed before Flux submission"),
                    }
                )
                continue

            try:
                final_info = flux.job.result(self._open_flux_handle(), flux_job_id)
                final_payload = final_info.to_dict(filtered=False)

                with self.jobs_lock:
                    tracked = self.jobs.get(local_job_id)
                if tracked:
                    self._apply_job_query_data(tracked, final_payload)
                    if tracked.status == JobStatus.COMPLETED:
                        completed += 1
                        job_results.append(
                            {
                                "job_id": local_job_id,
                                "flux_job_id": flux_job_id,
                                "status": "completed",
                                "exit_code": tracked.exit_code,
                            }
                        )
                    else:
                        failed += 1
                        job_results.append(
                            {
                                "job_id": local_job_id,
                                "flux_job_id": flux_job_id,
                                "status": "failed",
                                "exit_code": tracked.exit_code,
                                "error": tracked.error_message,
                            }
                        )
                else:
                    failed += 1
                    job_results.append({"job_id": local_job_id, "status": "failed", "error": "Lost tracking"})
            except Exception as exc:
                failed += 1
                job_results.append({"job_id": local_job_id, "status": "failed", "error": str(exc)})

        final_result = {
            "message": f"Completed: {completed} succeeded, {failed} failed",
            "total_jobs": len(jobs),
            "completed": completed,
            "failed": failed,
            "jobs": job_results,
        }

        return completed > 0, json.dumps(final_result, indent=2)

    def _submit_run_instances(
        self,
        runs: list[RunInstance],
        *,
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        queue: Optional[str],
        bank: Optional[str],
        exclusive: bool,
        job_name_prefix: str,
        urgency: int,
    ) -> Tuple[bool, str]:
        """Submit parsed run instances to Flux and return a JSON summary."""
        try:
            self._validate_submission_request(
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                urgency=urgency,
            )
        except ValueError as exc:
            return False, str(exc)

        submitted_jobs: list[Dict[str, Any]] = []
        failed_jobs: list[Dict[str, Any]] = []

        for run in runs:
            local_job_id = self._next_job_id()
            job_name = f"{job_name_prefix}_run_{run.id}" if job_name_prefix else f"run_{run.id}"
            job = self._submit_job_record(
                local_job_id=local_job_id,
                run_id=run.id,
                run_location=run.run_location,
                job_name=job_name,
                command_tokens=self._command_tokens_for_run(run),
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                urgency=urgency,
            )
            job_dict = job.to_dict()
            submitted_jobs.append(job_dict)
            if job.status == JobStatus.FAILED:
                failed_jobs.append(
                    {
                        "job_id": job_dict["job_id"],
                        "run_id": job_dict["run_id"],
                        "run_location": job_dict["run_location"],
                        "error_message": job_dict["error_message"],
                    }
                )

        result = {
            "message": f"Submitted {len(submitted_jobs) - len(failed_jobs)} jobs to Flux",
            "total_runs": len(submitted_jobs),
            "submitted_jobs": len(submitted_jobs) - len(failed_jobs),
            "failed_submissions": len(failed_jobs),
            "failed_jobs": failed_jobs,
            "requested_resources": {
                "nodes": nodes,
                "tasks": tasks,
                "cores_per_task": cores_per_task,
                "gpus_per_task": gpus_per_task,
                "time_limit": time_limit,
                "queue": queue,
                "bank": bank,
                "exclusive": exclusive,
                "urgency": urgency,
            },
            "jobs": submitted_jobs,
        }

        if len(failed_jobs) == len(submitted_jobs):
            return False, json.dumps(result, indent=2)
        return True, json.dumps(result, indent=2)

    def get_job_status(
        self,
        job_id: Optional[str] = None,
        flux_job_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Return status for tracked jobs or a direct Flux job ID query.

        Args:
            job_id: Local MADA job ID to query.
            flux_job_id: Flux job ID to query directly.

        Returns:
            Tuple of (success, JSON string containing job status information).
        """
        if job_id and flux_job_id:
            return (
                False,
                json.dumps(
                    {"error": "Pass either `job_id` or `flux_job_id`, not both."},
                    indent=2,
                ),
            )

        if flux_job_id:
            payload = self._query_untracked_flux_job(flux_job_id)
            return (True, json.dumps(payload, indent=2))

        if job_id:
            with self.jobs_lock:
                tracked = self.jobs.get(job_id)
            if tracked is None:
                return (False, json.dumps({"error": f"Job {job_id} not found"}, indent=2))
            self._refresh_jobs([tracked])
            return (True, json.dumps(tracked.to_dict(), indent=2))

        with self.jobs_lock:
            tracked_jobs = list(self.jobs.values())

        self._refresh_jobs(tracked_jobs)
        return (True, json.dumps(self._jobs_summary(tracked_jobs), indent=2))

    def continuously_check_job_status(
        self,
        job_id: Optional[str] = None,
        flux_job_id: Optional[str] = None,
        *,
        wait_until: str = "terminal",
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 3600.0,
    ) -> Tuple[bool, str]:
        """
        Poll Flux job status until a bounded wait condition is met.

        Args:
            job_id: Specific local MADA tracking ID to monitor.
            flux_job_id: Specific real Flux job ID to monitor.
            wait_until: `terminal` waits for selected jobs to finish; `any_running`
                returns once any selected job is running, or when all selected jobs
                have already reached terminal states.
            poll_interval_seconds: Seconds between status checks.
            timeout_seconds: Maximum seconds to wait before returning.

        Returns:
            Tuple of (success, JSON containing polling metadata plus the last status response).
        """
        result = self._poll_status_until(
            status_reader=lambda: self.get_job_status(job_id=job_id, flux_job_id=flux_job_id)[1],
            status_extractor=self._extract_statuses_from_status_payload,
            terminal_statuses=_TERMINAL_JOB_STATUSES,
            running_statuses=_RUNNING_JOB_STATUSES,
            wait_until=wait_until,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        return (True, result)

    def _write_flux_script(
        self,
        *,
        run_location: str,
        run_id: str,
        command_tokens: list[str],
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        queue: Optional[str],
        bank: Optional[str],
        exclusive: bool,
        job_name: str,
        urgency: int,
    ) -> Path:
        """Write one self-contained Flux submission script for the run."""
        run_directory = Path(run_location).expanduser().resolve()
        run_directory.mkdir(parents=True, exist_ok=True)

        script_path = run_directory / "submit_run.sh"
        # Create minimal RunInstance for _output_paths
        temp_run = RunInstance(id=run_id, command="", run_location=str(run_directory))
        stdout_path, stderr_path = self._output_paths(temp_run)

        # Build flux submit command with all parameters
        flux_cmd = ["flux", "submit"]

        # Add resource specifications
        flux_cmd.extend(["-N", str(nodes)])
        flux_cmd.extend(["-n", str(tasks)])
        flux_cmd.extend(["-c", str(cores_per_task)])
        if gpus_per_task > 0:
            flux_cmd.extend(["-g", str(gpus_per_task)])

        # Add time limit
        flux_cmd.extend(["-t", time_limit])

        # Add optional parameters
        if queue:
            flux_cmd.extend(["-q", queue])
        if bank:
            flux_cmd.extend(["--bank", bank])
        if exclusive:
            flux_cmd.append("--exclusive")

        # Add urgency
        flux_cmd.extend(["--urgency", str(urgency)])

        # Add job name
        flux_cmd.extend(["--setattr", f"user.name={job_name}"])

        # Add output/error paths
        flux_cmd.extend(["--output", str(stdout_path)])
        flux_cmd.extend(["--error", str(stderr_path)])

        # Add working directory
        flux_cmd.extend(["--cwd", str(run_directory)])

        # Add the actual command
        flux_cmd.extend(command_tokens)

        script_lines = [
            "#!/bin/bash",
            "#",
            "# Flux submission script generated by MADA MCP Flux server",
            f"# Run ID: {run_id}",
            f"# Run location: {run_directory}",
            "#",
            "",
            "set -e",
            "",
            "# Submit to Flux scheduler",
            shlex.join(flux_cmd),
            "",
        ]

        script_path.write_text("\n".join(script_lines), encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    def _submit_job_record(
        self,
        *,
        local_job_id: str,
        run_id: str,
        run_location: str,
        job_name: str,
        command_tokens: list[str],
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        queue: Optional[str],
        bank: Optional[str],
        exclusive: bool,
        urgency: int,
    ) -> JobInfo:
        """Create the jobspec, submit it to Flux, and store the tracked record."""
        run_path = Path(run_location).expanduser().resolve()
        run_path.mkdir(parents=True, exist_ok=True)

        # Create minimal RunInstance for _output_paths
        temp_run = RunInstance(id=run_id, command="", run_location=str(run_path))
        stdout_path, stderr_path = self._output_paths(temp_run)
        job = JobInfo(
            job_id=local_job_id,
            run_id=run_id,
            run_location=str(run_path),
            job_name=job_name,
            status=JobStatus.SUBMITTED,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            queue=queue,
            bank=bank,
            time_limit=time_limit,
            requested_nodes=nodes,
            requested_tasks=tasks,
            requested_cores_per_task=cores_per_task,
            requested_gpus_per_task=gpus_per_task,
            exclusive=exclusive,
            submitted_at=time.time(),
        )

        try:
            # Write a shell script with the equivalent flux submit command for manual execution
            self._write_flux_script(
                run_location=str(run_path),
                run_id=run_id,
                command_tokens=command_tokens,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
                job_name=job_name,
                urgency=urgency,
            )

            jobspec = self._create_jobspec(
                job_name=job_name,
                command_tokens=command_tokens,
                run_location=str(run_path),
                run_id=run_id,
                nodes=nodes,
                tasks=tasks,
                cores_per_task=cores_per_task,
                gpus_per_task=gpus_per_task,
                time_limit=time_limit,
                queue=queue,
                bank=bank,
                exclusive=exclusive,
            )
            flux_job_id = None
            for attempt in range(2):
                try:
                    flux_job_id = JobID(
                        flux.job.submit(
                            self._open_flux_handle(),
                            jobspec,
                            urgency=urgency,
                        )
                    )
                    break
                except Exception as exc:
                    if attempt == 0 and self._is_retryable_flux_error(exc):
                        LOG.warning(
                            "Retrying Flux submit for %s after transport error: %s",
                            local_job_id,
                            exc,
                        )
                        self._reopen_flux_handle()
                        continue
                    raise
            if flux_job_id is None:
                raise RuntimeError("Flux submission returned no job ID.")
            job.flux_job_id = int(flux_job_id)
            job.flux_job_id_f58 = str(flux_job_id)
            job.status = JobStatus.PENDING
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            LOG.error("Failed to submit Flux job for %s: %s", local_job_id, exc, exc_info=True)

        with self.jobs_lock:
            self.jobs[local_job_id] = job
        return job

    def _create_jobspec(
        self,
        *,
        job_name: str,
        command_tokens: list[str],
        run_location: str,
        run_id: str,
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        queue: Optional[str],
        bank: Optional[str],
        exclusive: bool,
    ) -> JobspecV1:
        """Create one Flux jobspec with explicit resources and scheduler metadata."""
        jobspec = JobspecV1.from_command(
            command_tokens,
            num_tasks=tasks,
            cores_per_task=cores_per_task,
            gpus_per_task=None if gpus_per_task == 0 else gpus_per_task,
            num_nodes=nodes,
            exclusive=exclusive,
        )
        jobspec.duration = time_limit
        jobspec.cwd = run_location
        jobspec.environment = dict(os.environ)
        # Flux writes stdout/stderr relative to `cwd`, so keep only file names
        # here while the tracked job record stores absolute paths.
        temp_run = RunInstance(id=run_id, command="", run_location=run_location)
        jobspec.stdout = Path(self._output_paths(temp_run)[0]).name
        jobspec.stderr = Path(self._output_paths(temp_run)[1]).name
        jobspec.setattr("system.job.name", job_name)
        if queue:
            jobspec.queue = queue
        if bank:
            jobspec.setattr("system.bank", bank)
        return jobspec

    def _refresh_jobs(self, jobs: list[JobInfo]) -> None:
        """Refresh tracked jobs from Flux."""
        if not jobs:
            return

        flux_job_ids = [job.flux_job_id for job in jobs if job.flux_job_id is not None]
        if not flux_job_ids:
            return

        payloads = self._query_many_flux_jobs(flux_job_ids)
        for job in jobs:
            if job.flux_job_id is None:
                continue
            payload = payloads.get(job.flux_job_id)
            if payload is None:
                job.status = JobStatus.UNKNOWN
                job.error_message = job.error_message or "Flux no longer reports this job ID."
                continue
            self._apply_job_query_data(job, payload)

    def _query_many_flux_jobs(self, flux_job_ids: list[int]) -> Dict[int, Dict[str, Any]]:
        """Fetch many tracked jobs from Flux."""
        results: Dict[int, Dict[str, Any]] = {}
        for attempt in range(2):
            try:
                for job_info in JobList(self._open_flux_handle(), ids=flux_job_ids).jobs():
                    payload = job_info.to_dict(filtered=False)
                    results[int(payload["id"])] = payload
                return results
            except Exception as exc:
                if attempt == 0 and self._is_retryable_flux_error(exc):
                    LOG.warning(
                        "Retrying Flux job-list query after transport error: %s",
                        exc,
                    )
                    self._reopen_flux_handle()
                    continue
                LOG.error("Failed to query Flux job list: %s", exc, exc_info=True)
        return results

    def _query_untracked_flux_job(self, flux_job_id: Any) -> Dict[str, Any]:
        """Query one Flux job directly, even if the local server did not submit it.

        This is useful on shared systems where the user may already know a real
        Flux job ID from `flux jobs`.
        """
        try:
            resolved_job_id = JobID(flux_job_id)
        except Exception as exc:
            return {"error": f"Invalid Flux job ID: {flux_job_id!r} ({exc})"}

        payload = None
        for attempt in range(2):
            try:
                payload = get_job(self._open_flux_handle(), resolved_job_id)
                break
            except Exception as exc:
                if attempt == 0 and self._is_retryable_flux_error(exc):
                    LOG.warning(
                        "Retrying Flux get_job for %s after transport error: %s",
                        resolved_job_id,
                        exc,
                    )
                    self._reopen_flux_handle()
                    continue
                return {"error": f"Failed to query Flux job {resolved_job_id}: {exc}"}
        if payload is None:
            return {"error": f"Flux job {resolved_job_id} was not found"}

        job = JobInfo(
            job_id="untracked",
            run_id="untracked",
            run_location=str(payload.get("cwd", "")),
            job_name=str(payload.get("name", "")),
            status=JobStatus.UNKNOWN,
            flux_job_id=int(resolved_job_id),
            flux_job_id_f58=str(resolved_job_id),
            submitted_at=time.time(),
        )
        self._apply_job_query_data(job, payload)
        result = job.to_dict()
        result["tracked"] = False
        return result

    def _apply_job_query_data(self, job: JobInfo, payload: Dict[str, Any]) -> None:
        """Update one tracked job from Flux job-info data."""
        job.raw_state = self._coerce_string(payload.get("state"))
        job.raw_result = self._coerce_string(payload.get("result"))
        job.status = self._map_flux_status(job.raw_state, job.raw_result)
        job.queue = self._coerce_string(payload.get("queue")) or job.queue
        job.bank = self._coerce_string(payload.get("bank")) or job.bank
        job.nodelist = self._coerce_string(payload.get("nodelist"))
        job.flux_reported_nodes = self._coerce_optional_int(payload.get("nnodes"))
        job.flux_reported_tasks = self._coerce_optional_int(payload.get("ntasks"))
        job.flux_reported_cores = self._coerce_optional_int(payload.get("ncores"))
        job.exit_code = self._coerce_optional_int(payload.get("returncode"))
        job.submitted_at = self._coerce_optional_float(payload.get("t_submit")) or job.submitted_at
        job.start_time = self._coerce_optional_float(payload.get("t_run")) or job.start_time

        cleanup_time = self._coerce_optional_float(payload.get("t_cleanup"))
        inactive_time = self._coerce_optional_float(payload.get("t_inactive"))
        end_time = inactive_time or cleanup_time
        if end_time is not None:
            job.end_time = end_time

        if job.flux_job_id is None and "id" in payload:
            flux_job_id = JobID(payload["id"])
            job.flux_job_id = int(flux_job_id)
            job.flux_job_id_f58 = str(flux_job_id)

        if job.status == JobStatus.FAILED and not job.error_message:
            inactive_reason = self._coerce_string(payload.get("inactive_reason"))
            job.error_message = inactive_reason or job.raw_result or "Flux reported job failure."
        elif job.status == JobStatus.COMPLETED:
            job.error_message = None

    def _jobs_summary(self, jobs: list[JobInfo]) -> Dict[str, Any]:
        """Build the aggregate response for all tracked jobs."""
        summary = {
            "total_jobs": len(jobs),
            "submitted": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "unknown": 0,
            "jobs": [job.to_dict() for job in jobs],
        }
        for job in jobs:
            summary[job.status.value] += 1
        return summary

    @staticmethod
    def _extract_statuses_from_status_payload(payload: Dict[str, Any]) -> list[str]:
        """
        Extract normalized job statuses from a Flux status response.

        Args:
            payload: Decoded JSON response from `get_job_status`.

        Returns:
            A list of normalized status strings.
        """
        jobs = payload.get("jobs")
        if isinstance(jobs, list):
            return [job["status"] for job in jobs if isinstance(job, dict) and isinstance(job.get("status"), str)]

        status = payload.get("status")
        if isinstance(status, str):
            return [status]
        return []

    def _validate_submission_request(
        self,
        *,
        nodes: int,
        tasks: int,
        cores_per_task: int,
        gpus_per_task: int,
        time_limit: str,
        urgency: int,
    ) -> None:
        """Validate scheduler resources before building jobspecs."""
        if not isinstance(nodes, int) or nodes <= 0:
            raise ValueError("`nodes` must be a positive integer.")
        if not isinstance(tasks, int) or tasks <= 0:
            raise ValueError("`tasks` must be a positive integer.")
        if tasks < nodes:
            raise ValueError("`tasks` must be greater than or equal to `nodes`.")
        if not isinstance(cores_per_task, int) or cores_per_task <= 0:
            raise ValueError("`cores_per_task` must be a positive integer.")
        if not isinstance(gpus_per_task, int) or gpus_per_task < 0:
            raise ValueError("`gpus_per_task` must be a non-negative integer.")
        if not isinstance(time_limit, str) or not time_limit.strip():
            raise ValueError("`time_limit` must be a non-empty string.")
        if not isinstance(urgency, int) or urgency < 0 or urgency > 31:
            raise ValueError("`urgency` must be an integer between 0 and 31.")

    def _resolve_flux_url(self) -> Optional[str]:
        """Resolve the configured Flux instance URL, if any."""
        flux_handle = os.getenv("FLUX_HANDLE")
        flux_uri = os.getenv("FLUX_URI")

        # Prefer a concrete inherited broker URI over FLUX_HANDLE=default so
        # long-lived MCP server processes can reconnect to the same instance.
        if flux_handle is not None:
            normalized_handle = flux_handle.strip()
            if normalized_handle and normalized_handle.lower() != "default":
                return normalized_handle

        if flux_uri is not None:
            normalized_uri = flux_uri.strip()
            if normalized_uri:
                return normalized_uri

        return None

    def _executor_handle_args(self) -> tuple[Any, ...]:
        """Build FluxExecutor constructor handle args."""
        if self.flux_url is None:
            return ()
        return (self.flux_url,)

    def _open_flux_handle(self):
        """Open a handle to the configured Flux instance."""
        if self.flux_url is None:
            return flux.Flux()
        return flux.Flux(self.flux_url)

    def _reopen_flux_handle(self):
        """Reopen the cached Flux handle after a broken transport error."""
        self.flux_handle = self._open_flux_handle()
        return self.flux_handle

    def _is_retryable_flux_error(self, exc: Exception) -> bool:
        """Return whether one Flux error merits a one-time handle reopen."""
        if isinstance(exc, BrokenPipeError):
            return True
        return isinstance(exc, OSError) and exc.errno == errno.EPIPE

    def _map_flux_status(self, raw_state: Optional[str], raw_result: Optional[str]) -> JobStatus:
        """Map Flux state/result strings onto the MCP server status vocabulary."""
        if raw_state is None:
            return JobStatus.UNKNOWN

        state = raw_state.upper()
        if state in {"NEW", "DEPEND", "PRIORITY", "SCHED"}:
            return JobStatus.PENDING
        if state in {"RUN", "CLEANUP"}:
            return JobStatus.RUNNING
        if state == "INACTIVE":
            result = (raw_result or "").upper()
            if result == "COMPLETED":
                return JobStatus.COMPLETED
            if result in {"FAILED", "CANCELED", "TIMEOUT"}:
                return JobStatus.FAILED
        return JobStatus.UNKNOWN

    def _coerce_optional_int(self, value: Any) -> Optional[int]:
        """Convert Flux job-info numeric values into Python ints."""
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_optional_float(self, value: Any) -> Optional[float]:
        """Convert Flux job-info numeric values into Python floats."""
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_string(self, value: Any) -> Optional[str]:
        """Normalize optional string fields."""
        if value in (None, ""):
            return None
        return str(value)
