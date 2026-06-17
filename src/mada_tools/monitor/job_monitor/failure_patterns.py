# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Failure pattern definitions for job monitoring.
These patterns are matched against combined stdout and stderr logs.
"""

FAILURE_PATTERNS = {
    "segmentation_fault": {
        "pattern": r"(segmentation fault|segfault)",
        "recommendation": (
            "Program accessed invalid memory. Check array bounds, uninitialized pointers, or memory corruption."
        ),
    },
    "mpi_abort": {
        "pattern": r"(MPI_Abort|MPI_ABORT|MPI_ABORT was invoked|Rank \d+ died)",
        "recommendation": (
            "An MPI rank aborted. Inspect communication paths, domain "
            "decomposition, or rank-level floating point failures."
        ),
    },
    "file_not_found": {
        "pattern": r"(file not found|No such file or directory)",
        "recommendation": ("A required file was missing. Check run_location content and input paths."),
    },
    "permission_error": {
        "pattern": r"(permission denied|EACCES)",
        "recommendation": ("Job attempted to access files or directories without sufficient permissions."),
    },
    "killed_by_system": {
        "pattern": r"(Killed|OOM|out of memory)",
        "recommendation": (
            "Job exceeded memory or was terminated by the OS. Reduce problem size or request more memory."
        ),
    },
    "scheduler_preemption": {
        "pattern": r"(preempted|suspended by scheduler|node failure)",
        "recommendation": ("The scheduler terminated the job. Resubmit or use a queue less likely to preempt jobs."),
    },
}

UNCLASSIFIED_FAILURE = {
    "failure_type": "unclassified_failure",
    "recommendation": (
        "No known failure pattern detected. The issue is not identifiable from the available log excerpt."
    ),
}
