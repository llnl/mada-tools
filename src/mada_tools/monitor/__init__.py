# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""
Monitoring package exposing the JobMonitorServer.
"""

# Explicitly import the subpackage so Python registers it
from . import job_monitor

# Re-export the server class for convenience
from .job_monitor.server import JobMonitorServer

__all__ = ["job_monitor", "JobMonitorServer"]
