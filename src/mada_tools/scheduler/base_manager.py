# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Base job manager utilities for MADA MCP scheduler servers."""

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from mada_tools.simulation.simutils.models import RunInstance


class MADABaseJobManager(ABC):
    """
    Abstract base class for job manager backends in MADA MCP scheduler servers.

    This class defines the interface required to support different job execution
    systems for staging and running parameterized workflows. It also provides
    shared helpers for decoding scheduler-ready run manifests.

    Attributes:
        aggregate_manifest_fields: Ordered field names accepted for an aggregate
            JSON file containing a scheduler-ready `{"runs": [...]}` payload.
        per_run_manifest_fields: Ordered field names accepted on per-run summary
            objects for scheduler-ready manifest files.

    Methods:
        stage: Generate and store parameterized job runs based on sampled input data.
        execute: Submit and monitor the staged runs, yielding status updates during execution.
        _load_runs: Decode inline JSON, bare run lists, or manifest file paths into
            `RunInstance` objects.
        _poll_status_until: Poll a backend status reader until a bounded wait
            condition is met.
        _command_tokens_for_run: Validate and assemble command tokens for one run.
        _output_paths: Return absolute stdout/stderr paths for one run.
    """

    aggregate_manifest_fields: Tuple[str, ...] = ("aggregate_scheduler_manifest_file",)
    per_run_manifest_fields: Tuple[str, ...] = ("scheduler_manifest_file",)

    @abstractmethod
    def stage(
        self,
        dims: int,
        num_samples: int,
        lower_bounds: List[float],
        upper_bounds: List[float],
        output_dir: str,
        parameter_file: str,
    ) -> Tuple[bool, str]:
        """
        Stage a workflow but don't execute it yet.

        Args:
            dims (int): The number of parameter dimensions.
            num_samples (int): The number of parameter sets (runs) to generate.
            lower_bounds (List[float]): Lower bounds for each parameter dimension.
            upper_bounds (List[float]): Upper bounds for each parameter dimension.
            output_dir (str): Path to the directory where run files will be stored.
            parameter_file (str): Name of the parameter file to write for each run.

        Returns:
            Tuple[bool, str]: A tuple containing a success flag and a status message.

        Raises:
            NotImplementedError: If called directly on the base class.
        """
        raise NotImplementedError("Subclasses must implement a `stage` method.")

    @abstractmethod
    def execute(self) -> Generator[str, None, None]:
        """
        Execute the previously staged workflow.

        This method is responsible for submitting and optionally monitoring the execution
        of the staged workflow prepared during the `stage` phase. Implementations should yield
        progress updates or log messages that indicate the status of job submissions and completions.

        Yields:
            str: Progress or status messages during execution.

        Raises:
            NotImplementedError: If called directly on the base class.
        """
        raise NotImplementedError("Subclasses must implement an `execute` method.")

    def _load_runs(self, run_info_json: str) -> list[RunInstance]:
        """
        Parse supported run payload shapes into `RunInstance` objects.

        Args:
            run_info_json: Inline JSON text or a path to a JSON run manifest file.

        Returns:
            A list of scheduler-ready run instances.
        """
        run_info = self._decode_run_info_input(run_info_json)
        normalized_run_info = self._normalize_run_info_payload(run_info)
        runs = normalized_run_info.get("runs")
        if not isinstance(runs, list) or not runs:
            raise ValueError("Input JSON must contain a non-empty `runs` list.")
        return [RunInstance.from_dict(run_dict) for run_dict in runs]

    def _decode_run_info_input(self, run_info_json: str) -> Any:
        """
        Decode inline JSON run info or load it from an existing JSON file path.

        Args:
            run_info_json: Inline JSON text or a path to a JSON file.

        Returns:
            The decoded JSON object.
        """
        if not isinstance(run_info_json, str) or not run_info_json.strip():
            raise ValueError("`run_info_json` must be a JSON payload string or an existing JSON file path.")

        raw_input = run_info_json.strip()
        if raw_input[0] not in "[{":
            manifest_path = Path(raw_input).expanduser()
            if manifest_path.is_file():
                return self._load_run_info_file(raw_input, field_name="run_info_json")

        try:
            return json.loads(raw_input)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "`run_info_json` must be valid JSON or a path to an existing JSON run manifest file."
            ) from exc

    def _normalize_run_info_payload(self, run_info: Any) -> Dict[str, Any]:
        """
        Normalize scheduler input into a canonical `{"runs": [...]}` payload.

        Args:
            run_info: Decoded scheduler payload.

        Returns:
            A dictionary containing a scheduler-ready `runs` list.
        """
        scheduler_payload = self._coerce_scheduler_runs_payload(run_info)
        if scheduler_payload is not None:
            return scheduler_payload

        if not isinstance(run_info, dict):
            raise ValueError("Input JSON must decode to an object or a list of scheduler-ready runs.")

        runs = run_info.get("runs")
        aggregate_manifest_file, aggregate_field_name = self._first_manifest_reference(
            run_info,
            *self.aggregate_manifest_fields,
        )
        if aggregate_manifest_file is not None:
            aggregate_payload = self._load_run_info_file(
                aggregate_manifest_file,
                field_name=aggregate_field_name or self.aggregate_manifest_fields[0],
            )
            normalized_aggregate = self._coerce_scheduler_runs_payload(aggregate_payload)
            if normalized_aggregate is not None:
                return normalized_aggregate
            raise ValueError(
                f"The file referenced by `{aggregate_field_name}` did not contain a valid non-empty `runs` list."
            )

        if isinstance(runs, list) and runs:
            manifest_payload = self._load_runs_from_per_run_scheduler_manifests(runs)
            if manifest_payload["runs"]:
                return manifest_payload

        raise ValueError(
            "Input JSON must contain a non-empty `runs` list with `id`, "
            "`run_location`, `command`, and `args`, or a sweep summary "
            "with aggregate/per-run scheduler manifest file entries."
        )

    def _coerce_scheduler_runs_payload(self, run_info: Any) -> Optional[Dict[str, Any]]:
        """
        Return a canonical runs payload if input is already scheduler-ready.

        Args:
            run_info: Decoded JSON object to inspect.

        Returns:
            A canonical `{"runs": [...]}` payload, or `None` if the payload is
            not already scheduler-ready.
        """
        if isinstance(run_info, list) and self._payload_has_scheduler_runs(run_info):
            return {"runs": run_info}
        if isinstance(run_info, dict) and self._payload_has_scheduler_runs(run_info.get("runs")):
            return run_info
        return None

    def _payload_has_scheduler_runs(self, runs: Any) -> bool:
        """
        Return whether a payload already looks like scheduler-ready run info.

        Args:
            runs: Potential list of run dictionaries.

        Returns:
            True when every entry has the fields needed to construct a
            `RunInstance`.
        """
        if not isinstance(runs, list) or not runs:
            return False
        return all(
            isinstance(run_dict, dict)
            and isinstance(run_dict.get("id"), str)
            and isinstance(run_dict.get("run_location"), str)
            and isinstance(run_dict.get("command"), str)
            and ("args" not in run_dict or isinstance(run_dict.get("args"), list))
            for run_dict in runs
        )

    def _load_run_info_file(self, raw_path: str, *, field_name: str) -> Any:
        """
        Load one JSON manifest file referenced by a scheduler input object.

        Args:
            raw_path: Path string from the scheduler input payload.
            field_name: Name of the field used in error messages.

        Returns:
            The decoded JSON object from `raw_path`.
        """
        manifest_path = Path(raw_path).expanduser()
        if not manifest_path.is_file():
            raise ValueError(f"`{field_name}` referenced a JSON file that does not exist: {raw_path}")
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"`{field_name}` referenced invalid JSON at {raw_path}: {exc}") from exc

    @staticmethod
    def _first_manifest_reference(
        source: Dict[str, Any],
        *field_names: str,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Return the first non-empty manifest path and the field it came from.

        Args:
            source: Decoded summary object to inspect.
            field_names: Field names to inspect in priority order.

        Returns:
            A `(path, field_name)` tuple, or `(None, None)` when no field is present.
        """
        for field_name in field_names:
            value = source.get(field_name)
            if isinstance(value, str) and value.strip():
                return value, field_name
        return None, None

    def _load_runs_from_per_run_scheduler_manifests(
        self,
        runs: list[Dict[str, Any]],
    ) -> Dict[str, list[Dict[str, Any]]]:
        """
        Expand per-run scheduler manifest references into one aggregate runs list.

        Args:
            runs: Sweep summary run entries that reference scheduler manifest files.

        Returns:
            A canonical `{"runs": [...]}` payload assembled from per-run manifests.
        """
        normalized_runs: list[Dict[str, Any]] = []

        for index, run_summary in enumerate(runs, start=1):
            if not isinstance(run_summary, dict):
                raise ValueError(f"Run entry {index} was not an object.")

            manifest_file, manifest_field_name = self._first_manifest_reference(
                run_summary,
                *self.per_run_manifest_fields,
            )
            if manifest_file is None:
                raise ValueError(
                    "Input `runs` entries were not scheduler-ready and did not provide a valid scheduler manifest file."
                )

            manifest_payload = self._load_run_info_file(
                manifest_file,
                field_name=f"runs[{index - 1}].{manifest_field_name}",
            )
            manifest_runs = manifest_payload.get("runs")
            if not self._payload_has_scheduler_runs(manifest_runs):
                raise ValueError(
                    f"`{manifest_field_name}` for run entry {index} did not contain "
                    "a valid scheduler-ready `runs` list."
                )
            normalized_runs.extend(manifest_runs)

        return {"runs": normalized_runs}

    def _next_job_id(self) -> str:
        """
        Allocate the next local tracking ID.

        Returns:
            A local job tracking ID such as `job_000001`.
        """
        with self.jobs_lock:
            self.job_counter += 1
            return f"job_{self.job_counter:06d}"

    def _poll_status_until(
        self,
        *,
        status_reader: Callable[[], str],
        status_extractor: Callable[[Dict[str, Any]], list[str]],
        terminal_statuses: set[str],
        running_statuses: set[str],
        wait_until: str,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> str:
        """
        Poll scheduler status until a bounded wait condition is satisfied.

        Args:
            status_reader: Callable returning the same JSON text as `check_job_status`.
            status_extractor: Callable extracting normalized statuses from the
                decoded status payload.
            terminal_statuses: Normalized statuses considered finished.
            running_statuses: Normalized statuses considered actively running.
            wait_until: `terminal` to wait for all selected jobs to finish, or
                `any_running` to return when at least one selected job starts running.
            poll_interval_seconds: Seconds to wait between status checks.
            timeout_seconds: Maximum seconds to wait before returning.

        Returns:
            JSON text with the final status payload and polling metadata.
        """
        self._validate_status_polling_request(
            wait_until=wait_until,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )

        normalized_wait_until = wait_until.strip().lower()
        start_time = time.monotonic()
        deadline = start_time + float(timeout_seconds)
        poll_attempts = 0

        while True:
            poll_attempts += 1
            status_payload = json.loads(status_reader())
            statuses = status_extractor(status_payload)
            condition_met = self._status_wait_condition_met(
                statuses,
                wait_until=normalized_wait_until,
                terminal_statuses=terminal_statuses,
                running_statuses=running_statuses,
            )
            now = time.monotonic()
            timed_out = not condition_met and now >= deadline
            has_error = isinstance(status_payload.get("error"), str)

            if condition_met or timed_out or has_error or not statuses:
                response = {
                    "condition_met": condition_met,
                    "timed_out": timed_out,
                    "wait_until": normalized_wait_until,
                    "poll_attempts": poll_attempts,
                    "elapsed_seconds": max(0.0, now - start_time),
                    "status": status_payload,
                }
                if has_error:
                    response["error"] = status_payload["error"]
                elif not statuses:
                    response["error"] = "No matching jobs were available to monitor."
                return json.dumps(response, indent=2)

            sleep_seconds = min(float(poll_interval_seconds), max(0.0, deadline - now))
            time.sleep(sleep_seconds)

    def _validate_status_polling_request(
        self,
        *,
        wait_until: str,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> None:
        """
        Validate common scheduler status polling arguments.

        Args:
            wait_until: Polling condition name.
            poll_interval_seconds: Seconds between status checks.
            timeout_seconds: Maximum seconds to wait.
        """
        if not isinstance(wait_until, str) or wait_until.strip().lower() not in {"terminal", "any_running"}:
            raise ValueError("`wait_until` must be either `terminal` or `any_running`.")
        if not isinstance(poll_interval_seconds, (int, float)) or poll_interval_seconds <= 0:
            raise ValueError("`poll_interval_seconds` must be a positive number.")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("`timeout_seconds` must be a positive number.")

    @staticmethod
    def _status_wait_condition_met(
        statuses: list[str],
        *,
        wait_until: str,
        terminal_statuses: set[str],
        running_statuses: set[str],
    ) -> bool:
        """
        Return whether normalized job statuses satisfy a wait condition.

        Args:
            statuses: Normalized job statuses from a scheduler response.
            wait_until: Polling condition name.
            terminal_statuses: Statuses considered complete.
            running_statuses: Statuses considered actively running.

        Returns:
            True when the selected wait condition is satisfied.
        """
        if not statuses:
            return False
        if wait_until == "terminal":
            return all(status in terminal_statuses for status in statuses)
        if wait_until == "any_running":
            return any(status in running_statuses for status in statuses) or all(
                status in terminal_statuses for status in statuses
            )
        return False

    def _command_tokens_for_run(self, run: RunInstance) -> list[str]:
        """
        Validate and assemble the command tokens for one run.

        Args:
            run: Run instance containing command, args, and metadata.

        Returns:
            List of command tokens [command, *args].

        Raises:
            ValueError: If run is missing required fields or has invalid values.
        """
        if not isinstance(run.command, str) or not run.command.strip():
            raise ValueError(f"Run {run.id!r} is missing a valid `command`.")
        if not isinstance(run.run_location, str) or not run.run_location.strip():
            raise ValueError(f"Run {run.id!r} is missing a valid `run_location`.")
        if not isinstance(run.id, str) or not run.id.strip():
            raise ValueError("Every run must have a non-empty string `id`.")
        args = run.args or []
        if not isinstance(args, list) or any(not isinstance(arg, str) or not arg.strip() for arg in args):
            raise ValueError(f"Run {run.id!r} has invalid `args`.")
        return [run.command, *args]

    def _output_paths(self, run: RunInstance) -> tuple[str, str]:
        """
        Return absolute stdout/stderr paths for one run.

        Args:
            run: Run instance containing run location and ID.

        Returns:
            Tuple of (stdout_path, stderr_path).
        """
        run_path = Path(run.run_location).expanduser().resolve()
        # Strip "run_" prefix if present to avoid "run_run_" in filenames
        output_id = run.id[4:] if run.id.startswith("run_") else run.id
        return (
            str(run_path / f"run_{output_id}.out"),
            str(run_path / f"run_{output_id}.err"),
        )
