# Copyright 2026, Lawrence Livermore National Security, LLC and MADA contributors
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

"""Shared execution helpers for MADA tool and helper call contracts."""

import traceback
from typing import Any, Callable, TypeVar

ExecutionErrorT = TypeVar("ExecutionErrorT", bound=Exception)


def execute_tool_contract(
    func: Callable[..., tuple[bool, Any]],
    *args: Any,
    error_type: type[ExecutionErrorT] = RuntimeError,
    **kwargs: Any,
) -> Any:
    """Execute one MADA tool/helper callable using the `(success, payload)` contract.

    Args:
        func: Callable that returns a `(success, payload)` tuple.
        *args: Positional arguments forwarded to `func`.
        error_type: Exception type used when normalizing failures.
        **kwargs: Keyword arguments forwarded to `func`.

    Returns:
        Any: Successful payload returned by `func`.

    Raises:
        ExecutionErrorT: Raised when the callable reports failure or raises an
            exception during execution.
    """
    try:
        success, payload = func(*args, **kwargs)
        if success:
            return payload
        raise error_type(str(payload))
    except Exception as exc:
        last = traceback.extract_tb(exc.__traceback__)[-1]
        raise error_type(f"Tool execution failed at {last.filename}:{last.lineno} in {last.name}: {exc}") from exc
