#!/usr/bin/env python3
"""Evaluate LLM MCP tool-call selection and arguments from JSON fixtures.

This script is the main benchmark runner. It loads a fixture of prompts and
expected MCP tool calls, exposes the configured MCP server tools to an
OpenAI-compatible chat-completions model, records the first returned tool call,
and compares the tool name and JSON arguments against the fixture.

The evaluator never executes the selected MCP tool. It only evaluates tool
selection and argument construction, then writes per-attempt rows, per-case
summaries, optional plots, and an optional Markdown run report.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import os
import random
import re
import shlex
import sys
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SRC = Path(__file__).resolve().parents[1] / "src"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from eval_io import load_models_file, parse_model_level, write_csv, write_csv_row, write_json  # noqa: E402

from mada_tools.shared.config import get_config_value, load_json_object_config  # noqa: E402
from mada_tools.shared.env import expand_env_vars  # noqa: E402

if TYPE_CHECKING:
    from mcp.client.session import ClientSession
    from openai import AsyncOpenAI

DEFAULT_SYSTEM_PROMPT = """You are testing MCP tool calling.
For each user prompt, call the single best MCP tool with structured arguments.
Do not ask follow-up questions when the prompt contains enough information.
"""

ROW_FIELDS = [
    "model",
    "server",
    "case_id",
    "prompt_id",
    "sample_index",
    "passed",
    "error_type",
    "error",
    "expected_tool",
    "actual_tool",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_token_price_usd",
    "output_token_price_usd",
    "input_cost_usd",
    "output_cost_usd",
    "total_cost_usd",
    "latency_ms",
]

SUMMARY_BASE_FIELDS = [
    "model",
    "server",
    "case_id",
    "num_flavors",
    "num_samples",
    "flavor_order",
    "score_passed",
    "score_total",
    "score_rate",
    "prompts_passed",
    "prompts_total",
    "pass_rate",
    "all_passed",
    "any_passed",
]

SUMMARY_METRIC_FIELDS = [
    "total_prompt_tokens",
    "total_completion_tokens",
    "total_tokens",
    "input_cost_usd",
    "output_cost_usd",
    "total_cost_usd",
    "avg_prompt_tokens",
    "avg_completion_tokens",
    "avg_total_tokens",
    "avg_latency_ms",
]

MATCH_MODES = {"subset", "exact"}
MATCH_PROFILES = {"parameter_runs"}
DEFAULT_MODEL_PRICES_PATH = Path(__file__).resolve().with_name("model_prices_and_context_window.json")
DEFAULT_MODELS_PATH = Path(__file__).resolve().with_name("eval_models.tsv")


@dataclass(frozen=True)
class ModelPricing:
    """Per-token pricing metadata used to estimate benchmark run cost."""

    input_cost_per_token: float
    output_cost_per_token: float


@dataclass
class ToolCallResult:
    """Normalized result of one model request for an MCP tool-call prompt.

    The evaluator stores both parsed tool-call data and raw response fragments so
    failures can be debugged after a run. Error fields are populated for API
    failures, missing tool calls, and malformed JSON arguments.
    """

    tool_name: str | None
    tool_arguments: dict[str, Any] | None
    tool_arguments_raw: str | None
    assistant_text: str | None
    raw_message: dict[str, Any] | None
    raw_tool_calls: list[dict[str, Any]]
    raw_response: dict[str, Any] | None
    usage: dict[str, int | None]
    latency_ms: int
    error_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ExpectedCall:
    """Expected tool call extracted from one fixture test case."""

    tool: str
    arguments: dict[str, Any]
    match_mode: str = "subset"
    match_profile: str | None = None


@dataclass(frozen=True)
class EvalWorkItem:
    """One model/case/prompt/sample attempt scheduled by the evaluator."""

    ordinal: int
    model: str
    test_case: dict[str, Any]
    prompt: dict[str, str]
    sample_index: int


@dataclass
class CompletedWorkItem:
    """Completed evaluator attempt with output rows and pass/fail metadata."""

    work_item: EvalWorkItem
    row: dict[str, Any]
    detailed_row: dict[str, Any]
    passed: bool
    error_type: str | None
    error: str | None


@dataclass(frozen=True)
class IntegerArgumentValidator:
    """Reusable argparse integer validator with an inclusive lower bound."""

    option_name: str
    minimum: int

    def __call__(self, value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{self.option_name} must be an integer") from exc
        if parsed < self.minimum:
            raise argparse.ArgumentTypeError(f"{self.option_name} must be at least {self.minimum}")
        return parsed


def expand_env_var(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} in config values."""
    return expand_env_vars(value, missing="error")


def load_json(path: Path) -> dict[str, Any]:
    """Load and validate a benchmark fixture from disk.

    Fixtures must be JSON objects containing `mcp_servers` and `tests`. Each
    test selects one configured server, supplies prompts, and defines an
    `expected_call` used later for tool-name and argument matching.
    """
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)

    if isinstance(loaded, list):
        raise ValueError(
            "Fixture must be a JSON object with 'mcp_servers' and 'tests'. Each test should select a server by name."
        )
    if not isinstance(loaded, dict):
        raise ValueError("Fixture must be a JSON object")
    if "mcp_servers" not in loaded or "tests" not in loaded:
        raise ValueError("Fixture must contain 'mcp_servers' and 'tests'")
    validate_fixture(loaded)
    return loaded


load_config = load_json_object_config


def load_model_prices(path: Path | None) -> dict[str, ModelPricing]:
    """Load optional model pricing metadata keyed by model ID."""
    if path is None:
        return {}
    if not path.exists():
        raise ValueError(f"Model prices file does not exist: {path}")

    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: model prices file must contain a JSON object")

    prices = {}
    for model, metadata in loaded.items():
        if model in {"sample_spec", "fallback_generalizations"}:
            continue
        if not isinstance(metadata, dict):
            continue
        input_price = metadata.get("input_cost_per_token")
        output_price = metadata.get("output_cost_per_token")
        if isinstance(input_price, (int, float)) and isinstance(output_price, (int, float)):
            prices[str(model)] = ModelPricing(
                input_cost_per_token=float(input_price),
                output_cost_per_token=float(output_price),
            )
    return prices


def calculate_costs(
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model_prices: dict[str, ModelPricing],
) -> dict[str, float | None]:
    """Calculate token cost fields for one evaluator row.

    Missing pricing or missing token usage is represented with `None` cost
    values while still preserving known per-token prices when available.
    """
    pricing = model_prices.get(model)
    if pricing is None or prompt_tokens is None or completion_tokens is None:
        return {
            "input_token_price_usd": pricing.input_cost_per_token if pricing else None,
            "output_token_price_usd": pricing.output_cost_per_token if pricing else None,
            "input_cost_usd": None,
            "output_cost_usd": None,
            "total_cost_usd": None,
        }

    input_cost = prompt_tokens * pricing.input_cost_per_token
    output_cost = completion_tokens * pricing.output_cost_per_token
    return {
        "input_token_price_usd": pricing.input_cost_per_token,
        "output_token_price_usd": pricing.output_cost_per_token,
        "input_cost_usd": round(input_cost, 10),
        "output_cost_usd": round(output_cost, 10),
        "total_cost_usd": round(input_cost + output_cost, 10),
    }


def normalize_prompts(test_case: dict[str, Any]) -> list[dict[str, str]]:
    """Return fixture prompts as dictionaries with stable `id` and `text`.

    Prompt entries may already be objects or may be plain strings. Plain strings
    are assigned deterministic IDs (`prompt_1`, `prompt_2`, ...), matching the
    fixture format documented for benchmark authors.
    """
    prompts = test_case.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError(f"Test case {test_case.get('id', '<missing id>')} must contain a non-empty prompts list")

    normalized = []
    for index, prompt in enumerate(prompts, start=1):
        if isinstance(prompt, str):
            normalized.append({"id": f"prompt_{index}", "text": prompt})
            continue
        if isinstance(prompt, dict) and isinstance(prompt.get("text"), str):
            normalized.append({"id": str(prompt.get("id", f"prompt_{index}")), "text": prompt["text"]})
            continue
        raise ValueError(f"Invalid prompt in test case {test_case.get('id', '<missing id>')}: {prompt!r}")
    return normalized


def prompt_style_id(prompt_id: str) -> str:
    """Return the root prompt style by stripping a numeric suffix."""
    return re.sub(r"_\d+$", "", prompt_id)


def parse_prompt_filter_list(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("prompt filter must include at least one value")
    return values


def prompt_selected(
    prompt_id: str,
    include_prompt_ids: set[str],
    include_prompt_styles: set[str],
    exclude_prompt_ids: set[str],
    exclude_prompt_styles: set[str],
) -> bool:
    """Return whether one prompt ID passes include and exclude filters."""
    style_id = prompt_style_id(prompt_id)
    if include_prompt_ids or include_prompt_styles:
        if prompt_id not in include_prompt_ids and style_id not in include_prompt_styles:
            return False
    if prompt_id in exclude_prompt_ids or style_id in exclude_prompt_styles:
        return False
    return True


def filter_fixture_prompts(
    fixture: dict[str, Any],
    include_prompt_ids: list[str] | None = None,
    include_prompt_styles: list[str] | None = None,
    exclude_prompt_ids: list[str] | None = None,
    exclude_prompt_styles: list[str] | None = None,
) -> dict[str, Any]:
    """Apply prompt include/exclude filters to every fixture test case.

    Filters may target exact prompt IDs or root prompt styles. The function
    returns a deep copy when filtering is active and rejects filters that would
    leave any test case without prompts, because downstream summaries assume at
    least one prompt per case.
    """
    include_ids = set(include_prompt_ids or [])
    include_styles = set(include_prompt_styles or [])
    exclude_ids = set(exclude_prompt_ids or [])
    exclude_styles = set(exclude_prompt_styles or [])
    if not any((include_ids, include_styles, exclude_ids, exclude_styles)):
        return fixture

    filtered = copy.deepcopy(fixture)
    empty_cases = []
    for test_case in filtered["tests"]:
        original_prompts = normalize_prompts(test_case)
        selected_prompts = [
            prompt
            for prompt in original_prompts
            if prompt_selected(prompt["id"], include_ids, include_styles, exclude_ids, exclude_styles)
        ]
        if not selected_prompts:
            empty_cases.append(f"{test_case['server']}/{test_case['id']}")
        test_case["prompts"] = selected_prompts

    if empty_cases:
        preview = ", ".join(empty_cases[:5])
        suffix = "" if len(empty_cases) <= 5 else f", ... and {len(empty_cases) - 5} more"
        raise ValueError(f"Prompt filters removed all prompts from case(s): {preview}{suffix}")
    return filtered


parse_num_samples = IntegerArgumentValidator("--num-samples", 1)
parse_max_concurrency = IntegerArgumentValidator("--max-concurrency", 1)
parse_shard_count = IntegerArgumentValidator("--shard-count", 1)
parse_shard_index = IntegerArgumentValidator("--shard-index", 0)


def parse_level(value: str) -> int:
    try:
        return parse_model_level(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_min_pass_rate(value: str) -> float:
    """Parse a minimum pass-rate threshold in the inclusive range [0, 1]."""
    try:
        rate = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--min-pass-rate must be a number") from exc
    if rate < 0 or rate > 1:
        raise argparse.ArgumentTypeError("--min-pass-rate must be between 0 and 1")
    return rate


def flavor_field_names(prompt_id: str) -> tuple[str, str, str]:
    return (f"{prompt_id}_passed", f"{prompt_id}_total", f"{prompt_id}_rate")


def flavor_metric_field_names(prompt_id: str) -> tuple[str, str, str, str]:
    return (
        f"{prompt_id}_avg_prompt_tokens",
        f"{prompt_id}_avg_completion_tokens",
        f"{prompt_id}_avg_total_tokens",
        f"{prompt_id}_avg_latency_ms",
    )


def summary_fields_for_fixture(fixture: dict[str, Any]) -> list[str]:
    """Build the stable summary CSV field order for a fixture.

    Summary rows include fixed aggregate fields plus prompt-specific pass-rate
    and metric columns in first-seen fixture order.
    """
    flavor_fields: list[str] = []
    seen_prompt_ids: set[str] = set()
    for test_case in fixture["tests"]:
        for prompt in normalize_prompts(test_case):
            prompt_id = prompt["id"]
            if prompt_id in seen_prompt_ids:
                continue
            seen_prompt_ids.add(prompt_id)
            flavor_fields.extend(flavor_field_names(prompt_id))
            flavor_fields.extend(flavor_metric_field_names(prompt_id))
    return SUMMARY_BASE_FIELDS + flavor_fields + SUMMARY_METRIC_FIELDS


def prompt_ids_for_case(test_case: dict[str, Any]) -> list[str]:
    return [prompt["id"] for prompt in normalize_prompts(test_case)]


def prompt_ids_by_case(fixture: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    """Return prompt IDs keyed by `(server, case_id)`."""
    mapping = {}
    for test_case in fixture["tests"]:
        mapping[(test_case["server"], test_case["id"])] = prompt_ids_for_case(test_case)
    return mapping


def shard_label(shard_count: int, shard_index: int) -> str:
    return f"{shard_index + 1}/{shard_count}"


def progress_shard_suffix(shard_count: int, shard_index: int) -> str:
    if shard_count <= 1:
        return ""
    return f" shard={shard_label(shard_count, shard_index)}"


def validate_shard_args(args: argparse.Namespace) -> None:
    """Validate that a shard index selects one shard in the configured range."""
    if args.shard_index >= args.shard_count:
        raise ValueError("--shard-index must be less than --shard-count")


def expected_call_from_test_case(test_case: dict[str, Any]) -> ExpectedCall:
    """Parse and validate one test case's expected tool call contract.

    Supported match modes are `subset` and `exact`. Supported match profiles add
    domain-specific argument equivalence without changing the fixture's expected
    call shape.
    """
    case_id = test_case.get("id", "<missing id>")
    expected_call = test_case.get("expected_call")
    if not isinstance(expected_call, dict):
        raise ValueError(f"Test case {case_id} must contain an expected_call object")

    tool = expected_call.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ValueError(f"Test case {case_id} expected_call.tool must be a non-empty string")

    arguments = expected_call.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError(f"Test case {case_id} expected_call.arguments must be an object")

    match = expected_call.get("match", {})
    if match is None:
        match = {}
    if not isinstance(match, dict):
        raise ValueError(f"Test case {case_id} expected_call.match must be an object when provided")

    mode = match.get("mode", "subset")
    if not isinstance(mode, str) or mode not in MATCH_MODES:
        raise ValueError(
            f"Test case {case_id} expected_call.match.mode must be one of: {', '.join(sorted(MATCH_MODES))}"
        )

    profile = match.get("profile")
    if profile is not None and (not isinstance(profile, str) or profile not in MATCH_PROFILES):
        raise ValueError(
            f"Test case {case_id} expected_call.match.profile must be one of: {', '.join(sorted(MATCH_PROFILES))}"
        )

    return ExpectedCall(tool=tool, arguments=arguments, match_mode=mode, match_profile=profile)


def validate_fixture(fixture: dict[str, Any]) -> None:
    """Validate the fixture shape needed for live tool-call evaluation."""
    mcp_servers = fixture.get("mcp_servers")
    tests = fixture.get("tests")
    if not isinstance(mcp_servers, dict) or not mcp_servers:
        raise ValueError("Fixture 'mcp_servers' must be a non-empty object")
    if not isinstance(tests, list) or not tests:
        raise ValueError("Fixture 'tests' must be a non-empty list")

    for index, test_case in enumerate(tests, start=1):
        if not isinstance(test_case, dict):
            raise ValueError(f"Test case #{index} must be an object")
        case_id = test_case.get("id", f"case_{index}")
        server = test_case.get("server")
        if not isinstance(server, str) or not server:
            raise ValueError(f"Test case {case_id} must contain a non-empty server string")
        if server not in mcp_servers:
            raise ValueError(f"Test case {case_id} references unknown MCP server '{server}'")
        expected_call_from_test_case(test_case)
        normalize_prompts(test_case)


def tool_to_openai_format(tool: Any, server_name: str) -> dict[str, Any]:
    """Convert an MCP tool object into OpenAI chat-completions tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": f"[{server_name}] {tool.description or ''}",
            "parameters": tool.inputSchema,
        },
    }


def progress(message: str, quiet: bool = False) -> None:
    """Print a progress message unless quiet mode is enabled."""
    if not quiet:
        print(message, flush=True)


def model_dump(value: Any) -> Any:
    """Serialize Pydantic-like objects when supported."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def exception_messages(exc: BaseException) -> list[str]:
    """Flatten exception groups into readable error messages."""
    nested_exceptions = getattr(exc, "exceptions", None)
    if isinstance(nested_exceptions, tuple) and all(
        isinstance(sub_exception, BaseException) for sub_exception in nested_exceptions
    ):
        messages = []
        for sub_exception in nested_exceptions:
            messages.extend(exception_messages(sub_exception))
        return messages
    return [f"{type(exc).__name__}: {exc}"]


def load_mcp_client_dependencies() -> tuple[type["ClientSession"], Any]:
    """Import MCP client dependencies lazily for benchmark-only execution."""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "mcp package is required for live evaluator runs that connect to MCP servers"
        ) from exc
    return ClientSession, streamablehttp_client


async def connect_server(
    server_name: str,
    server_config: dict[str, Any],
    stack: AsyncExitStack,
    quiet: bool = False,
) -> tuple[ClientSession, list[dict[str, Any]]]:
    """Connect to one MCP server and return its session and OpenAI tool schemas."""
    client_session_cls, streamablehttp_client = load_mcp_client_dependencies()

    url = server_config.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"MCP server '{server_name}' must define a non-empty url")
    url = expand_env_var(url)

    progress(f"Connecting to MCP server '{server_name}' at {url} ...", quiet)
    started = time.perf_counter()
    try:
        read_stream, write_stream, _ = await stack.enter_async_context(streamablehttp_client(url))
        session = client_session_cls(read_stream, write_stream)
        await stack.enter_async_context(session)
        await session.initialize()
        tools_result = await session.list_tools()
        tools = [tool_to_openai_format(tool, server_name) for tool in tools_result.tools]
        latency_ms = round((time.perf_counter() - started) * 1000)
        progress(f"Connected to '{server_name}' with {len(tools)} tools in {latency_ms}ms.", quiet)
        return session, tools
    except Exception as e:
        latency_ms = round((time.perf_counter() - started) * 1000)
        details = "; ".join(exception_messages(e))
        raise RuntimeError(
            f"Failed to connect to MCP server '{server_name}' at {url} after {latency_ms}ms. "
            f"Details: {details}. Check that the server is running and the fixture URL is correct."
        ) from e


async def connect_required_servers(
    fixture: dict[str, Any],
    stack: AsyncExitStack,
    quiet: bool = False,
) -> dict[str, tuple[ClientSession, list[dict[str, Any]]]]:
    """Connect only to MCP servers referenced by the fixture tests."""
    server_configs = fixture["mcp_servers"]
    tests = fixture["tests"]
    required_servers = sorted({test["server"] for test in tests})

    connected = {}
    for server_name in required_servers:
        if server_name not in server_configs:
            raise ValueError(f"Test references unknown MCP server '{server_name}'")
        connected[server_name] = await connect_server(server_name, server_configs[server_name], stack, quiet)
    return connected


def usage_dict(usage: Any) -> dict[str, int | None]:
    """Normalize OpenAI usage metadata into evaluator row fields."""
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
    }


async def get_tool_call(
    client: AsyncOpenAI,
    model: str,
    tools: list[dict[str, Any]],
    prompt: str,
    system_prompt: str,
    temperature: float | None,
    capture_raw_response: bool = False,
) -> ToolCallResult:
    """Ask a model to choose an MCP tool and parse its first tool call.

    The benchmark intentionally evaluates only the first returned tool call. A
    successful result contains a tool name and object-valued JSON arguments;
    model/API failures are returned as structured `ToolCallResult` errors so the
    run can continue and record the failure.
    """
    started = time.perf_counter()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "tools": tools,
        "tool_choice": "auto",
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as e:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ToolCallResult(
            tool_name=None,
            tool_arguments=None,
            tool_arguments_raw=None,
            assistant_text=None,
            raw_message=None,
            raw_tool_calls=[],
            raw_response=None,
            usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
            latency_ms=latency_ms,
            error_type="api_error",
            error=f"{type(e).__name__}: {e}",
        )

    latency_ms = round((time.perf_counter() - started) * 1000)
    message = response.choices[0].message
    raw_message = model_dump(message)
    raw_response = model_dump(response) if capture_raw_response else None
    tool_calls = message.tool_calls or []
    raw_tool_calls = [model_dump(tool_call) for tool_call in tool_calls]
    if not tool_calls:
        return ToolCallResult(
            tool_name=None,
            tool_arguments=None,
            tool_arguments_raw=None,
            assistant_text=message.content,
            raw_message=raw_message,
            raw_tool_calls=raw_tool_calls,
            raw_response=raw_response,
            usage=usage_dict(response.usage),
            latency_ms=latency_ms,
            error_type="no_tool_call",
            error="model returned no tool call",
        )

    call = tool_calls[0]
    tool_arguments_raw = call.function.arguments or "{}"
    try:
        arguments = json.loads(tool_arguments_raw)
    except json.JSONDecodeError as e:
        return ToolCallResult(
            tool_name=call.function.name,
            tool_arguments=None,
            tool_arguments_raw=tool_arguments_raw,
            assistant_text=message.content,
            raw_message=raw_message,
            raw_tool_calls=raw_tool_calls,
            raw_response=raw_response,
            usage=usage_dict(response.usage),
            latency_ms=latency_ms,
            error_type="bad_json",
            error=f"tool arguments are not valid JSON: {e}",
        )

    if not isinstance(arguments, dict):
        return ToolCallResult(
            tool_name=call.function.name,
            tool_arguments=None,
            tool_arguments_raw=tool_arguments_raw,
            assistant_text=message.content,
            raw_message=raw_message,
            raw_tool_calls=raw_tool_calls,
            raw_response=raw_response,
            usage=usage_dict(response.usage),
            latency_ms=latency_ms,
            error_type="bad_json",
            error="tool arguments JSON must decode to an object",
        )

    return ToolCallResult(
        tool_name=call.function.name,
        tool_arguments=arguments,
        tool_arguments_raw=tool_arguments_raw,
        assistant_text=message.content,
        raw_message=raw_message,
        raw_tool_calls=raw_tool_calls,
        raw_response=raw_response,
        usage=usage_dict(response.usage),
        latency_ms=latency_ms,
    )


def compare_values(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Recursively compare expected values against actual values.

    Dictionaries use subset semantics: all expected keys must be present and
    equal, but extra actual keys are allowed. Lists and scalar values must match
    exactly.
    """
    errors = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}: expected object, got {type(actual).__name__}"]
        for key, expected_value in expected.items():
            child_path = f"{path}.{key}"
            if key not in actual:
                errors.append(f"missing {child_path}")
                continue
            errors.extend(compare_values(expected_value, actual[key], child_path))
        return errors

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{path}: expected list, got {type(actual).__name__}"]
        if len(expected) != len(actual):
            return [f"{path}: expected list length {len(expected)}, got {len(actual)}"]
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            errors.extend(compare_values(expected_item, actual_item, f"{path}[{index}]"))
        return errors

    if expected != actual:
        return [f"{path}: expected {expected!r}, got {actual!r}"]
    return []


def is_parameter_spec(value: Any, parameter_type: str | None = None) -> bool:
    """Return whether a value matches the shared parameter-spec tuple shape."""
    if not isinstance(value, list) or len(value) < 3 or not isinstance(value[0], str):
        return False
    if parameter_type is not None:
        return value[0] == parameter_type
    return value[0] in {"def", "exe", "cli"}


def is_zip_parameter_spec(value: Any, parameter_type: str | None = None) -> bool:
    """Return whether a parameter spec uses zip selection."""
    return is_parameter_spec(value, parameter_type) and len(value) >= 3 and value[1] == "zip"


def zip_group_id(spec: list[Any]) -> Any:
    """Return an explicit zip group ID, or the implicit default group."""
    return spec[3] if len(spec) >= 4 else 1


def set_zip_group_id(spec: list[Any], group_id: Any) -> None:
    if len(spec) >= 4:
        spec[3] = group_id
    else:
        spec.append(group_id)


def parameter_specs_match_ignoring_zip_group(expected: Any, actual: Any) -> bool:
    """Compare parameter specs while allowing different zip group labels."""
    if not is_parameter_spec(expected) or not is_parameter_spec(actual):
        return False
    if is_zip_parameter_spec(expected) and is_zip_parameter_spec(actual):
        return expected[:3] == actual[:3]
    return expected == actual


def same_group_id(left: Any, right: Any) -> bool:
    return left == right


def find_group_mapping(group_mappings: list[tuple[Any, Any]], expected_group: Any) -> Any | None:
    for mapped_expected_group, actual_group in group_mappings:
        if same_group_id(mapped_expected_group, expected_group):
            return actual_group
    return None


def actual_group_is_mapped(group_mappings: list[tuple[Any, Any]], actual_group: Any) -> bool:
    return any(
        same_group_id(mapped_actual_group, actual_group) for _expected_group, mapped_actual_group in group_mappings
    )


def normalize_input_deck_path(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Treat an input deck path that includes the entrypoint as equivalent."""
    expected_deck_path = expected_arguments.get("input_deck_path")
    expected_entrypoint = expected_arguments.get("input_deck_entrypoint")
    actual_deck_path = actual_arguments.get("input_deck_path")
    actual_entrypoint = actual_arguments.get("input_deck_entrypoint")

    if not all(isinstance(value, str) for value in [expected_deck_path, expected_entrypoint, actual_deck_path]):
        return
    if actual_entrypoint is not None and actual_entrypoint != expected_entrypoint:
        return

    expected_full_path = os.path.normpath(os.path.join(expected_deck_path, expected_entrypoint))
    if os.path.normpath(actual_deck_path) == expected_full_path:
        actual_arguments["input_deck_path"] = expected_deck_path
        actual_arguments["input_deck_entrypoint"] = expected_entrypoint


def normalize_dependency_paths(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Convert dependency paths made absolute under the deck path back to relative paths."""
    expected_deck_path = expected_arguments.get("input_deck_path")
    expected_dependencies = expected_arguments.get("dependency_paths")
    actual_dependencies = actual_arguments.get("dependency_paths")

    if (
        not isinstance(expected_deck_path, str)
        or not isinstance(expected_dependencies, list)
        or not isinstance(actual_dependencies, list)
        or len(expected_dependencies) != len(actual_dependencies)
    ):
        return

    normalized_dependencies = []
    changed = False
    for expected_dependency, actual_dependency in zip(expected_dependencies, actual_dependencies):
        if not isinstance(expected_dependency, str) or not isinstance(actual_dependency, str):
            return

        expected_joined_path = os.path.normpath(os.path.join(expected_deck_path, expected_dependency))
        if not os.path.isabs(expected_dependency) and os.path.normpath(actual_dependency) == expected_joined_path:
            normalized_dependencies.append(expected_dependency)
            changed = True
        else:
            normalized_dependencies.append(actual_dependency)

    if changed:
        actual_arguments["dependency_paths"] = normalized_dependencies


def normalize_executable_parameter_aliases(
    expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]
) -> None:
    """Allow executable parameters to be keyed by equivalent generated names."""
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    used_actual_keys = set()
    for expected_key, expected_value in expected_parameters.items():
        if expected_key in actual_parameters or not is_parameter_spec(expected_value, "exe"):
            continue

        for actual_key, actual_value in actual_parameters.items():
            if actual_key in used_actual_keys or not is_parameter_spec(actual_value, "exe"):
                continue
            if parameter_specs_match_ignoring_zip_group(expected_value, actual_value):
                actual_parameters[expected_key] = actual_value
                used_actual_keys.add(actual_key)
                break


def normalize_zip_group_identifiers(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Normalize zip parameter group IDs when group structure is equivalent.

    Models may choose different zip group labels while preserving the same
    grouping relationships. This maps actual group identifiers to expected ones
    only when the mapping is one-to-one and unambiguous.
    """
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    group_mappings: list[tuple[Any, Any]] = []
    matching_zip_keys = []
    for parameter_name, expected_value in expected_parameters.items():
        actual_value = actual_parameters.get(parameter_name)
        if not (
            is_zip_parameter_spec(expected_value)
            and is_zip_parameter_spec(actual_value)
            and parameter_specs_match_ignoring_zip_group(expected_value, actual_value)
        ):
            continue

        expected_group = zip_group_id(expected_value)
        actual_group = zip_group_id(actual_value)
        mapped_actual_group = find_group_mapping(group_mappings, expected_group)
        if mapped_actual_group is None:
            if actual_group_is_mapped(group_mappings, actual_group):
                return
            group_mappings.append((expected_group, actual_group))
        elif not same_group_id(mapped_actual_group, actual_group):
            return

        matching_zip_keys.append(parameter_name)

    for parameter_name in matching_zip_keys:
        expected_value = expected_parameters[parameter_name]
        actual_value = actual_parameters[parameter_name]
        set_zip_group_id(actual_value, zip_group_id(expected_value))


def cli_value_to_tokens(value: Any) -> list[str] | None:
    """Normalize a CLI value string or token list into argv tokens."""
    if isinstance(value, str):
        if not value:
            return None
        try:
            tokens = shlex.split(value)
        except ValueError:
            return None
        return tokens or None
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return value
    return None


def cli_spec_token_sequences(spec: Any) -> list[list[str]] | None:
    """Return tokenized CLI value sequences from a CLI parameter spec."""
    if not is_parameter_spec(spec, "cli"):
        return None
    values = spec[2]
    if not isinstance(values, list) or not values:
        return None

    token_sequences = []
    for value in values:
        tokens = cli_value_to_tokens(value)
        if tokens is None:
            return None
        token_sequences.append(tokens)
    return token_sequences


def contains_subsequence(tokens: list[str], expected: list[str]) -> bool:
    """Return whether `expected` appears contiguously inside `tokens`."""
    if not expected or len(expected) > len(tokens):
        return False
    return any(tokens[index : index + len(expected)] == expected for index in range(len(tokens) - len(expected) + 1))


def normalize_cli_parameter_values(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Normalize CLI parameter values that tokenize to the same argv sequence."""
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    for parameter_name, expected_value in expected_parameters.items():
        actual_value = actual_parameters.get(parameter_name)
        if not (is_parameter_spec(expected_value, "cli") and is_parameter_spec(actual_value, "cli")):
            continue
        if len(expected_value) != len(actual_value) or expected_value[:2] != actual_value[:2]:
            continue
        if len(expected_value) == 4 and expected_value[3] != actual_value[3]:
            continue

        expected_sequences = cli_spec_token_sequences(expected_value)
        actual_sequences = cli_spec_token_sequences(actual_value)
        if expected_sequences is not None and expected_sequences == actual_sequences:
            actual_parameters[parameter_name] = expected_value


def normalize_cli_parameter_aliases(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Recognize expected discrete CLI fragments embedded in actual CLI parameters."""
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    actual_cli_sequences = []
    for actual_value in actual_parameters.values():
        sequences = cli_spec_token_sequences(actual_value)
        if sequences:
            actual_cli_sequences.extend(sequences)

    if not actual_cli_sequences:
        return

    for expected_key, expected_value in expected_parameters.items():
        if expected_key in actual_parameters or not is_parameter_spec(expected_value, "cli"):
            continue
        if expected_value[1] != "discrete":
            continue
        expected_sequences = cli_spec_token_sequences(expected_value)
        if not expected_sequences or len(expected_sequences) != 1:
            continue

        expected_tokens = expected_sequences[0]
        if any(contains_subsequence(actual_tokens, expected_tokens) for actual_tokens in actual_cli_sequences):
            actual_parameters[expected_key] = expected_value


def normalize_discrete_def_numeric_strings(
    expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]
) -> None:
    """Treat numeric strings as numeric values for discrete `def` parameters."""
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    for parameter_name, expected_value in expected_parameters.items():
        actual_value = actual_parameters.get(parameter_name)
        if not (
            is_parameter_spec(expected_value, "def")
            and is_parameter_spec(actual_value, "def")
            and expected_value[1] == "discrete"
            and actual_value[1] == "discrete"
            and isinstance(expected_value[2], list)
            and isinstance(actual_value[2], list)
            and len(expected_value[2]) == len(actual_value[2])
        ):
            continue

        normalized_values = []
        changed = False
        for expected_item, actual_item in zip(expected_value[2], actual_value[2]):
            if (
                isinstance(expected_item, (int, float))
                and not isinstance(expected_item, bool)
                and isinstance(actual_item, str)
                and actual_item == str(expected_item)
            ):
                normalized_values.append(expected_item)
                changed = True
            else:
                normalized_values.append(actual_item)

        if changed:
            actual_value[2] = normalized_values


def normalize_json_string_values(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
    """Decode JSON-string lists when they match expected parameter value lists."""
    expected_parameters = expected_arguments.get("parameters")
    actual_parameters = actual_arguments.get("parameters")
    if not isinstance(expected_parameters, dict) or not isinstance(actual_parameters, dict):
        return

    for parameter_name, expected_value in expected_parameters.items():
        actual_value = actual_parameters.get(parameter_name)
        if (
            not is_parameter_spec(expected_value)
            or not is_parameter_spec(actual_value)
            or not isinstance(expected_value[2], list)
            or not isinstance(actual_value[2], str)
        ):
            continue
        try:
            parsed_values = json.loads(actual_value[2])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed_values, list) and parsed_values == expected_value[2]:
            actual_value[2] = parsed_values


def normalize_actual_arguments_for_matching(
    expected_arguments: dict[str, Any],
    actual_arguments: dict[str, Any],
    match_profile: str | None,
) -> dict[str, Any]:
    """Return actual arguments normalized for the selected match profile.

    The default profile performs no normalization. The `parameter_runs` profile
    accepts common equivalent representations produced by LLMs for simulation
    parameter generation prompts, such as split deck paths, relabeled zip groups,
    CLI strings versus token lists, and JSON-encoded value lists.
    """
    normalized = copy.deepcopy(actual_arguments)
    if match_profile is None:
        return normalized
    if match_profile != "parameter_runs":
        raise ValueError(f"Unknown match profile: {match_profile}")

    normalize_input_deck_path(expected_arguments, normalized)
    normalize_dependency_paths(expected_arguments, normalized)
    normalize_executable_parameter_aliases(expected_arguments, normalized)
    normalize_zip_group_identifiers(expected_arguments, normalized)
    normalize_cli_parameter_values(expected_arguments, normalized)
    normalize_cli_parameter_aliases(expected_arguments, normalized)
    normalize_json_string_values(expected_arguments, normalized)
    normalize_discrete_def_numeric_strings(expected_arguments, normalized)
    return normalized


def evaluate_result(
    test_case: dict[str, Any],
    result: ToolCallResult,
    strict: bool,
) -> tuple[bool, str | None, str | None]:
    """Evaluate one model response against a fixture test case."""
    if result.error_type:
        return False, result.error_type, result.error

    expected_call = expected_call_from_test_case(test_case)
    if result.tool_name != expected_call.tool:
        return False, "wrong_tool", f"expected {expected_call.tool!r}, got {result.tool_name!r}"

    expected_arguments = expected_call.arguments
    actual_arguments = result.tool_arguments or {}
    match_mode = "exact" if strict else expected_call.match_mode

    if match_mode == "exact" and expected_arguments != actual_arguments:
        return False, "arg_mismatch", "actual arguments do not exactly match expected arguments"
    if match_mode == "subset":
        actual_arguments = normalize_actual_arguments_for_matching(
            expected_arguments,
            actual_arguments,
            expected_call.match_profile,
        )

    errors = compare_values(expected_arguments, actual_arguments)
    if errors:
        return False, "arg_mismatch", "; ".join(errors[:5])

    return True, None, None


def build_row(
    model: str,
    test_case: dict[str, Any],
    prompt: dict[str, str],
    sample_index: int,
    result: ToolCallResult,
    passed: bool,
    error_type: str | None,
    error: str | None,
    model_prices: dict[str, ModelPricing] | None = None,
) -> dict[str, Any]:
    """Build the compact per-attempt row used for CSV and summary aggregation."""
    usage = result.usage
    expected_call = expected_call_from_test_case(test_case)
    cost_fields = calculate_costs(
        model=model,
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        model_prices=model_prices or {},
    )
    return {
        "model": model,
        "server": test_case["server"],
        "case_id": test_case["id"],
        "prompt_id": prompt["id"],
        "sample_index": sample_index,
        "passed": passed,
        "error_type": error_type or "",
        "error": error or "",
        "expected_tool": expected_call.tool,
        "actual_tool": result.tool_name or "",
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        **cost_fields,
        "latency_ms": result.latency_ms,
    }


def average(values: list[int | None]) -> float | None:
    """Return the rounded average of present integer values."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 3)


def sum_present(values: list[int | float | None]) -> int | float | None:
    """Return the sum of present numeric values, preserving all-missing as None."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    total = sum(present)
    if isinstance(total, float):
        return round(total, 10)
    return total


def summarize(fixture: dict[str, Any], rows: list[dict[str, Any]], num_samples: int) -> list[dict[str, Any]]:
    """Aggregate per-attempt rows into per-model/per-server/per-case summaries."""
    case_prompt_ids = prompt_ids_by_case(fixture)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["model"], row["server"], row["case_id"])
        grouped.setdefault(key, []).append(row)

    summary_rows = []
    for (model, server, case_id), case_rows in sorted(grouped.items()):
        prompt_ids = case_prompt_ids[(server, case_id)]
        passed_count = sum(1 for row in case_rows if row["passed"])
        total_count = len(case_rows)
        pass_rate = round(passed_count / total_count, 3) if total_count else 0
        summary_row: dict[str, Any] = {
            "model": model,
            "server": server,
            "case_id": case_id,
            "num_flavors": len(prompt_ids),
            "num_samples": num_samples,
            "flavor_order": json.dumps(prompt_ids),
            "score_passed": passed_count,
            "score_total": total_count,
            "score_rate": pass_rate,
            "prompts_passed": passed_count,
            "prompts_total": total_count,
            "pass_rate": pass_rate,
            "all_passed": passed_count == total_count,
            "any_passed": passed_count > 0,
        }
        rows_by_prompt: dict[str, list[dict[str, Any]]] = {prompt_id: [] for prompt_id in prompt_ids}
        for row in case_rows:
            rows_by_prompt.setdefault(str(row["prompt_id"]), []).append(row)

        for prompt_id in prompt_ids:
            prompt_rows = rows_by_prompt.get(prompt_id, [])
            prompt_passed = sum(1 for row in prompt_rows if row["passed"])
            prompt_total = len(prompt_rows)
            prompt_rate = round(prompt_passed / prompt_total, 3) if prompt_total else 0
            passed_field, total_field, rate_field = flavor_field_names(prompt_id)
            summary_row[passed_field] = prompt_passed
            summary_row[total_field] = prompt_total or num_samples
            summary_row[rate_field] = prompt_rate
            (
                avg_prompt_tokens_field,
                avg_completion_tokens_field,
                avg_total_tokens_field,
                avg_latency_ms_field,
            ) = flavor_metric_field_names(prompt_id)
            summary_row[avg_prompt_tokens_field] = average([row["prompt_tokens"] for row in prompt_rows])
            summary_row[avg_completion_tokens_field] = average([row["completion_tokens"] for row in prompt_rows])
            summary_row[avg_total_tokens_field] = average([row["total_tokens"] for row in prompt_rows])
            summary_row[avg_latency_ms_field] = average([row["latency_ms"] for row in prompt_rows])

        summary_row["avg_prompt_tokens"] = average([row["prompt_tokens"] for row in case_rows])
        summary_row["avg_completion_tokens"] = average([row["completion_tokens"] for row in case_rows])
        summary_row["avg_total_tokens"] = average([row["total_tokens"] for row in case_rows])
        summary_row["avg_latency_ms"] = average([row["latency_ms"] for row in case_rows])
        summary_row["total_prompt_tokens"] = sum_present([row.get("prompt_tokens") for row in case_rows])
        summary_row["total_completion_tokens"] = sum_present([row.get("completion_tokens") for row in case_rows])
        summary_row["total_tokens"] = sum_present([row.get("total_tokens") for row in case_rows])
        summary_row["input_cost_usd"] = sum_present([row.get("input_cost_usd") for row in case_rows])
        summary_row["output_cost_usd"] = sum_present([row.get("output_cost_usd") for row in case_rows])
        summary_row["total_cost_usd"] = sum_present([row.get("total_cost_usd") for row in case_rows])
        summary_rows.append(summary_row)
    return summary_rows


def total_prompt_count(fixture: dict[str, Any], models: list[str], num_samples: int) -> int:
    """Return the logical number of model prompt attempts in a full run."""
    return len(models) * sum(len(normalize_prompts(test_case)) for test_case in fixture["tests"]) * num_samples


def build_work_items(
    fixture: dict[str, Any],
    models: list[str],
    num_samples: int,
    shard_count: int,
    shard_index: int,
) -> list[EvalWorkItem]:
    """Create deterministic evaluator work items and select this process's shard.

    `ordinal` is assigned before sharding so independently executed shards share
    the same canonical ordering and can later be merged without ambiguity.
    """
    work_items = []
    ordinal = 0
    for model in models:
        for test_case in fixture["tests"]:
            prompts = normalize_prompts(test_case)
            for prompt in prompts:
                for sample_index in range(1, num_samples + 1):
                    if ordinal % shard_count == shard_index:
                        work_items.append(
                            EvalWorkItem(
                                ordinal=ordinal,
                                model=model,
                                test_case=test_case,
                                prompt=prompt,
                                sample_index=sample_index,
                            )
                        )
                    ordinal += 1
    return work_items


def build_detailed_row(
    row: dict[str, Any],
    prompt_text: str,
    expected_call: dict[str, Any],
    result: ToolCallResult,
) -> dict[str, Any]:
    """Extend a compact row with prompt, expected call, and raw model response data."""
    return {
        **row,
        "prompt": prompt_text,
        "expected_call": expected_call,
        "actual_arguments": result.tool_arguments,
        "actual_arguments_raw": result.tool_arguments_raw,
        "assistant_text": result.assistant_text,
        "raw_message": result.raw_message,
        "raw_tool_calls": result.raw_tool_calls,
        "raw_response": result.raw_response,
    }


async def execute_work_item(
    work_item: EvalWorkItem,
    client: AsyncOpenAI,
    connected_servers: dict[str, tuple[ClientSession, list[dict[str, Any]]]],
    system_prompt: str,
    temperature: float | None,
    strict: bool,
    capture_raw_response: bool,
    semaphore: asyncio.Semaphore,
    model_prices: dict[str, ModelPricing],
) -> CompletedWorkItem:
    """Execute and score one evaluator work item."""
    async with semaphore:
        _session, tools = connected_servers[work_item.test_case["server"]]
        result = await get_tool_call(
            client=client,
            model=work_item.model,
            tools=tools,
            prompt=work_item.prompt["text"],
            system_prompt=system_prompt,
            temperature=temperature,
            capture_raw_response=capture_raw_response,
        )

    passed, error_type, error = evaluate_result(work_item.test_case, result, strict)
    row = build_row(
        work_item.model,
        work_item.test_case,
        work_item.prompt,
        work_item.sample_index,
        result,
        passed,
        error_type,
        error,
        model_prices,
    )
    detailed_row = build_detailed_row(row, work_item.prompt["text"], work_item.test_case["expected_call"], result)
    return CompletedWorkItem(
        work_item=work_item,
        row=row,
        detailed_row=detailed_row,
        passed=passed,
        error_type=error_type,
        error=error,
    )


async def execute_work_items(
    work_items: list[EvalWorkItem],
    client: AsyncOpenAI,
    connected_servers: dict[str, tuple[ClientSession, list[dict[str, Any]]]],
    system_prompt: str,
    temperature: float | None,
    strict: bool,
    capture_raw_response: bool,
    quiet: bool,
    total_attempts: int,
    shard_count: int,
    shard_index: int,
    max_concurrency: int,
    csv_writer: csv.DictWriter | None,
    csv_file: Any,
    model_prices: dict[str, ModelPricing],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute work items concurrently while preserving canonical output order."""
    rows: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []
    if not work_items:
        return rows, detailed_rows

    semaphore = asyncio.Semaphore(max_concurrency)
    shard_suffix = progress_shard_suffix(shard_count, shard_index)
    ordered_ordinals = [work_item.ordinal for work_item in work_items]
    buffered: dict[int, CompletedWorkItem] = {}
    next_flush_position = 0
    tasks = []

    for work_item in work_items:
        progress(
            f"[{work_item.ordinal + 1}/{total_attempts}] START "
            f"model={work_item.model} server={work_item.test_case['server']} "
            f"case={work_item.test_case['id']} prompt={work_item.prompt['id']} "
            f"sample={work_item.sample_index}{shard_suffix}",
            quiet,
        )
        tasks.append(
            asyncio.create_task(
                execute_work_item(
                    work_item=work_item,
                    client=client,
                    connected_servers=connected_servers,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    strict=strict,
                    capture_raw_response=capture_raw_response,
                    semaphore=semaphore,
                    model_prices=model_prices,
                )
            )
        )

    for task in asyncio.as_completed(tasks):
        completed = await task
        buffered[completed.work_item.ordinal] = completed
        while next_flush_position < len(ordered_ordinals):
            next_ordinal = ordered_ordinals[next_flush_position]
            buffered_item = buffered.get(next_ordinal)
            if buffered_item is None:
                break

            rows.append(buffered_item.row)
            detailed_rows.append(buffered_item.detailed_row)
            if csv_writer and csv_file:
                write_csv_row(csv_writer, buffered_item.row, ROW_FIELDS)
                csv_file.flush()

            result_label = "PASS" if buffered_item.passed else "FAIL"
            error_detail = (
                f" error_type={buffered_item.error_type} error={buffered_item.error}"
                if buffered_item.error_type
                else ""
            )
            progress(
                f"[{buffered_item.work_item.ordinal + 1}/{total_attempts}] {result_label} "
                f"sample={buffered_item.work_item.sample_index} latency_ms={buffered_item.row['latency_ms']} "
                f"tokens={format_tokens(buffered_item.row)}{error_detail}{shard_suffix}",
                quiet,
            )
            del buffered[next_ordinal]
            next_flush_position += 1

    return rows, detailed_rows


def print_rows(rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> None:
    """Print human-readable result and summary tables to stdout."""
    print("\nResults")
    print("model | server | case | prompt | sample | result | tokens | latency_ms | error")
    print("-" * 112)
    for row in rows:
        result = "PASS" if row["passed"] else "FAIL"
        tokens = row["total_tokens"] if row["total_tokens"] is not None else "n/a"
        print(
            f"{row['model']} | {row['server']} | {row['case_id']} | {row['prompt_id']} | {row['sample_index']} | "
            f"{result} | {tokens} | {row['latency_ms']} | {row['error']}"
        )

    print("\nSummary")
    print("model | server | case | score | pass_rate | avg_tokens | total_cost_usd | avg_latency_ms")
    print("-" * 116)
    for row in summary_rows:
        avg_tokens = row["avg_total_tokens"] if row["avg_total_tokens"] is not None else "n/a"
        total_cost = row["total_cost_usd"] if row.get("total_cost_usd") is not None else "n/a"
        print(
            f"{row['model']} | {row['server']} | {row['case_id']} | "
            f"{row['score_passed']}/{row['score_total']} | {row['pass_rate']} | "
            f"{avg_tokens} | {total_cost} | {row['avg_latency_ms']}"
        )


def format_tokens(row: dict[str, Any]) -> str:
    return str(row["total_tokens"]) if row["total_tokens"] is not None else "n/a"


async def run_evaluator(args: argparse.Namespace) -> int:
    """Run the live evaluator from parsed evaluator arguments."""
    from openai import AsyncOpenAI

    validate_shard_args(args)
    fixture = load_json(args.cases)
    fixture = filter_fixture_prompts(
        fixture,
        include_prompt_ids=getattr(args, "prompt_ids", None),
        include_prompt_styles=getattr(args, "prompt_styles", None),
        exclude_prompt_ids=getattr(args, "exclude_prompt_ids", None),
        exclude_prompt_styles=getattr(args, "exclude_prompt_styles", None),
    )
    config = load_config(args.config)
    model_prices = load_model_prices(args.model_prices)
    system_prompt = args.system_prompt or DEFAULT_SYSTEM_PROMPT
    api_key = args.api_key or get_config_value(config, "api_key") or os.getenv("API_KEY")
    base_url = (
        args.base_url
        or get_config_value(config, "base_url")
        or os.getenv(
            "API_BASE_URL",
            "https://livai-api.llnl.gov/v1",
        )
    )
    if not api_key:
        api_key = "dummy" if base_url.startswith(("http://localhost", "http://127.0.0.1")) else None
    if not api_key:
        raise ValueError("API key is required. Pass --api-key or set API_KEY.")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=args.request_timeout)
    summary_fields = summary_fields_for_fixture(fixture)
    total_prompts = total_prompt_count(fixture, args.models, args.num_samples)
    work_items = build_work_items(fixture, args.models, args.num_samples, args.shard_count, args.shard_index)
    progress(
        f"Evaluating {total_prompts} logical tool-call attempts across {len(args.models)} models, "
        f"{len(fixture['tests'])} test cases, {len(fixture['mcp_servers'])} configured MCP servers, "
        f"and {args.num_samples} sample(s) per prompt flavor.",
        args.quiet,
    )
    if args.shard_count > 1:
        progress(
            f"Executing shard {shard_label(args.shard_count, args.shard_index)} with {len(work_items)} attempt(s) "
            f"and max_concurrency={args.max_concurrency}.",
            args.quiet,
        )
    else:
        progress(f"Executing {len(work_items)} attempt(s) with max_concurrency={args.max_concurrency}.", args.quiet)
    if args.shard_count > 1 and (args.summary_csv or args.summary_json or args.min_pass_rate is not None):
        progress(
            "Note: shard-local summary outputs and --min-pass-rate apply only to this shard's subset of attempts.",
            args.quiet,
        )

    csv_file = None
    csv_writer = None
    if args.results_csv:
        args.results_csv.parent.mkdir(parents=True, exist_ok=True)
        csv_file = args.results_csv.open("w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=ROW_FIELDS)
        csv_writer.writeheader()
        csv_file.flush()

    run_started = time.perf_counter()
    try:
        async with AsyncExitStack() as stack:
            connected_servers = await connect_required_servers(fixture, stack, args.quiet)
            rows, detailed_rows = await execute_work_items(
                work_items=work_items,
                client=client,
                connected_servers=connected_servers,
                system_prompt=system_prompt,
                temperature=args.temperature,
                strict=args.strict,
                capture_raw_response=args.capture_raw_response,
                quiet=args.quiet,
                total_attempts=total_prompts,
                shard_count=args.shard_count,
                shard_index=args.shard_index,
                max_concurrency=args.max_concurrency,
                csv_writer=csv_writer,
                csv_file=csv_file,
                model_prices=model_prices,
            )
    finally:
        if csv_file:
            csv_file.close()

    elapsed_s = round(time.perf_counter() - run_started, 3)
    progress(
        f"Completed {len(work_items)} executed tool-call attempt(s) in {elapsed_s}s.",
        args.quiet,
    )

    summary_rows = summarize(fixture, rows, args.num_samples)
    if not args.no_final_table:
        print_rows(rows, summary_rows)

    if args.results_json:
        write_json(args.results_json, detailed_rows)
    if args.summary_csv:
        write_csv(args.summary_csv, summary_rows, summary_fields)
    if args.summary_json:
        write_json(args.summary_json, summary_rows)

    all_passed = all(row["passed"] for row in rows)
    if args.min_pass_rate is not None:
        all_passed = all(row["pass_rate"] >= args.min_pass_rate for row in summary_rows)
    return 0 if all_passed else 1


from plot_tool_call_eval_results import (  # noqa: E402
    axis_label_with_case_count,
    format_usd,
    has_numeric_value,
    load_rows,
    missing_cost_annotations,
    plot_stacked,
    score_axis_label,
    score_reference_lines,
    sum_numeric_values,
)

from mada_tools.server_management import ServerManager  # noqa: E402

DEFAULT_SCORE_FIELD = "score_passed"
DEFAULT_TOKEN_FIELD = "avg_total_tokens"
DEFAULT_COST_FIELD = "total_cost_usd"


@dataclass(frozen=True)
class ServerManagementSettings:
    """Run-config settings for starting MCP servers around an evaluation."""

    enabled: bool
    config_path: Path | None = None
    randomize_ports: bool = True
    stop_on_exit: bool = True


@dataclass
class ManagedServerRun:
    """State needed to stop managed servers and report effective config paths."""

    manager: ServerManager
    required_servers: list[str]
    cases_path: Path
    servers_config_path: Path
    stop_on_exit: bool


def expand_config_env(value: Any) -> Any:
    """Recursively expand environment placeholders in JSON config values."""
    if isinstance(value, str):
        return expand_env_vars(value, missing="error")
    if isinstance(value, list):
        return [expand_config_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_config_env(item) for key, item in value.items()}
    return value


def load_run_config(path: Path) -> dict[str, Any]:
    """Load a run config and expand environment placeholders recursively."""
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("Run config must be a JSON object")
    return expand_config_env(loaded)


def path_from_config(config_dir: Path, value: Any, field_name: str, required: bool = False) -> Path | None:
    """Resolve a run-config path relative to the run-config directory."""
    if value in (None, ""):
        if required:
            raise ValueError(f"Run config field {field_name!r} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"Run config field {field_name!r} must be a string path")

    path = Path(value)
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def bool_config(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Expected boolean config value, got {type(value).__name__}")


def int_config(value: Any, default: int, parser: Any) -> int:
    if value is None:
        return default
    return parser(str(value))


def float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def min_pass_rate_config(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return parse_min_pass_rate(str(value))


def optional_string(value: Any, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Run config field {field_name!r} must be a string")
    return value


def optional_string_list(value: Any, field_name: str) -> list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return parse_prompt_filter_list(value)
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return value
    raise ValueError(f"Run config field {field_name!r} must be a string or list of strings")


def server_management_settings(
    config: dict[str, Any],
    config_dir: Path,
    cli_args: argparse.Namespace,
) -> ServerManagementSettings:
    """Resolve whether this run should start and stop MCP servers itself."""
    raw = config.get("server_management", {})
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("Run config field 'server_management' must be an object when provided")

    if getattr(cli_args, "no_manage_servers", False):
        return ServerManagementSettings(enabled=False)

    enabled = bool_config(raw.get("enabled"), False)
    if not enabled:
        return ServerManagementSettings(enabled=False)

    config_path = path_from_config(config_dir, raw.get("config"), "server_management.config", required=True)
    assert config_path is not None
    return ServerManagementSettings(
        enabled=True,
        config_path=config_path,
        randomize_ports=bool_config(raw.get("randomize_ports"), True),
        stop_on_exit=bool_config(raw.get("stop_on_exit"), True),
    )


def load_fixture_for_managed_servers(path: Path) -> dict[str, Any]:
    """Load fixture data before managed-server URLs have been injected."""
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("Fixture must be a JSON object")
    tests = loaded.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("Fixture 'tests' must be a non-empty list")

    for index, test_case in enumerate(tests, start=1):
        if not isinstance(test_case, dict):
            raise ValueError(f"Test case #{index} must be an object")
        case_id = test_case.get("id", f"case_{index}")
        server = test_case.get("server")
        if not isinstance(server, str) or not server:
            raise ValueError(f"Test case {case_id} must contain a non-empty server string")
        expected_call_from_test_case(test_case)
        normalize_prompts(test_case)
    return loaded


def required_server_names(fixture: dict[str, Any]) -> list[str]:
    """Return fixture server names in first-use order."""
    names = []
    for test_case in fixture["tests"]:
        server_name = test_case["server"]
        if server_name not in names:
            names.append(server_name)
    return names


def load_server_management_json(path: Path) -> dict[str, Any]:
    """Load and validate a server-management config used for managed runs."""
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError("Server management config must be a JSON object")
    servers = loaded.get("servers")
    if not isinstance(servers, dict) or not servers:
        raise ValueError("Server management config must contain a non-empty 'servers' object")
    return loaded


def randomize_server_ports(
    servers_data: dict[str, Any],
    required_servers: list[str],
    randomize_ports: bool,
) -> dict[str, int]:
    """Assign effective ports for required managed servers.

    Randomizing ports allows concurrent benchmark runs to start their own MCP
    servers without colliding with static development ports.
    """
    servers = servers_data["servers"]
    missing = [name for name in required_servers if name not in servers]
    if missing:
        raise ValueError("Server management config is missing required server(s): " + ", ".join(sorted(missing)))

    port_map = {}
    for name in required_servers:
        server_config = servers[name]
        if not isinstance(server_config, dict):
            raise ValueError(f"Server management config for server {name!r} must be an object")
        if "port" not in server_config:
            raise ValueError(f"Managed MCP server {name!r} must define a port so an evaluator URL can be built")
        if randomize_ports:
            server_config["port"] = random.randint(1024, 65535)
        port_map[name] = int(server_config["port"])
    return port_map


def effective_mcp_fixture(
    fixture: dict[str, Any],
    servers_data: dict[str, Any],
    required_servers: list[str],
    port_map: dict[str, int],
) -> dict[str, Any]:
    """Build the fixture copy used by the evaluator for managed servers."""
    effective = copy.deepcopy(fixture)
    mcp_servers = effective.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}

    for name in required_servers:
        server_config = servers_data["servers"][name]
        host = server_config.get("host", "localhost")
        existing = mcp_servers.get(name, {})
        if not isinstance(existing, dict):
            existing = {}
        mcp_servers[name] = {
            **existing,
            "transport": existing.get("transport", server_config.get("transport", "streamable-http")),
            "url": f"http://{host}:{port_map[name]}/mcp",
        }

    effective["mcp_servers"] = mcp_servers
    return effective


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def start_managed_servers(
    settings: ServerManagementSettings,
    cases_path: Path,
    output_dir: Path,
    quiet: bool,
) -> ManagedServerRun:
    """Write effective server/case configs and start required MCP servers."""
    if not settings.enabled or settings.config_path is None:
        raise ValueError("Server management is not enabled")

    fixture = load_fixture_for_managed_servers(cases_path)
    required_servers = required_server_names(fixture)
    servers_data = load_server_management_json(settings.config_path)
    port_map = randomize_server_ports(servers_data, required_servers, settings.randomize_ports)
    effective_fixture = effective_mcp_fixture(fixture, servers_data, required_servers, port_map)

    output_dir.mkdir(parents=True, exist_ok=True)
    server_config_path = output_dir / f"{settings.config_path.stem}_effective_{uuid.uuid4().hex}.json"
    effective_cases_path = output_dir / f"{cases_path.stem}_effective_{uuid.uuid4().hex}.json"
    write_json_file(server_config_path, servers_data)
    write_json_file(effective_cases_path, effective_fixture)

    manager = ServerManager(state_file=Path.home() / ".mada" / f"server_statuses_{uuid.uuid4().hex}.json")
    progress(
        "Starting managed MCP server(s): " + ", ".join(required_servers),
        quiet,
    )
    manager.start_servers(server_config_path, required_servers)
    return ManagedServerRun(
        manager=manager,
        required_servers=required_servers,
        cases_path=effective_cases_path,
        servers_config_path=server_config_path,
        stop_on_exit=settings.stop_on_exit,
    )


def stop_managed_servers(managed: ManagedServerRun | None, quiet: bool) -> None:
    """Stop managed MCP servers when the run config requests cleanup."""
    if managed is None or not managed.stop_on_exit:
        return
    progress("Stopping managed MCP server(s): " + ", ".join(managed.required_servers), quiet)
    managed.manager.stop_servers()


def level_from_config(config: dict[str, Any], cli_args: argparse.Namespace) -> int:
    """Resolve the maximum model-list level from CLI or run config."""
    cli_level = getattr(cli_args, "level", None)
    if cli_level is not None:
        return cli_level
    try:
        return parse_model_level(str(config.get("level", 0)), "Run config field 'level'")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def models_from_config(
    config: dict[str, Any],
    config_dir: Path,
    models_file_override: Path | None,
    models_override: list[str] | None = None,
    level: int = 0,
) -> list[str]:
    """Resolve the model list from CLI overrides, run config, or model files."""
    if models_override is not None:
        if not models_override:
            raise ValueError("--models must include at least one model")
        return models_override

    if models_file_override is not None:
        return load_models_file(models_file_override, level)

    if "models" in config:
        models = config["models"]
        if not isinstance(models, list) or not all(isinstance(model, str) and model for model in models):
            raise ValueError("Run config field 'models' must be a non-empty list of model strings")
        if not models:
            raise ValueError("Run config field 'models' must not be empty")
        return models

    models_file = path_from_config(config_dir, config.get("models_file"), "models_file", required=True)
    assert models_file is not None
    return load_models_file(models_file, level)


def output_path(output_dir: Path, prefix: str, suffix: str, enabled: bool) -> Path | None:
    """Return a prefixed output path only when that artifact is enabled."""
    if not enabled:
        return None
    return output_dir / f"{prefix}_{suffix}"


def report_output_path(config: dict[str, Any], output_dir: Path) -> Path | None:
    """Resolve the optional Markdown report output path for a run."""
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")
    if not bool_config(output_config.get("report"), True):
        return None

    configured_path = output_config.get("report_path")
    if configured_path not in (None, ""):
        if not isinstance(configured_path, str):
            raise ValueError("Run config field 'output.report_path' must be a string path")
        path = Path(configured_path)
        return path if path.is_absolute() else output_dir / path

    prefix = str(output_config.get("prefix") or "tool_call")
    return output_dir / f"{prefix}_report.md"


def build_output_dir(config: dict[str, Any], config_dir: Path, output_dir_override: Path | None) -> Path:
    """Resolve and optionally timestamp the run output directory."""
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")

    base_dir = output_dir_override or path_from_config(
        config_dir, output_config.get("directory", "results"), "output.directory"
    )
    assert base_dir is not None

    timestamped = bool_config(output_config.get("timestamped"), True)
    run_name = str(config.get("name") or "tool_call_eval")
    if timestamped:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return base_dir / f"{run_name}_{timestamp}"
    return base_dir


def build_eval_args(
    config: dict[str, Any],
    config_dir: Path,
    cli_args: argparse.Namespace,
    output_dir: Path,
    models: list[str],
) -> argparse.Namespace:
    """Translate the high-level run config into evaluator arguments."""
    eval_config = config.get("eval", {})
    output_config = config.get("output", {})
    model_api_config = config.get("model_api", {})
    if not isinstance(eval_config, dict):
        raise ValueError("Run config field 'eval' must be an object when provided")
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")
    if not isinstance(model_api_config, dict):
        raise ValueError("Run config field 'model_api' must be an object when provided")

    prefix = str(output_config.get("prefix") or "tool_call")
    cases = path_from_config(config_dir, config.get("cases"), "cases", required=True)
    api_config = path_from_config(config_dir, model_api_config.get("config"), "model_api.config")
    model_prices = path_from_config(
        config_dir,
        config.get("model_prices", str(DEFAULT_MODEL_PRICES_PATH)),
        "model_prices",
    )

    return argparse.Namespace(
        cases=cases,
        config=api_config,
        models=models,
        base_url=optional_string(model_api_config.get("base_url"), "model_api.base_url"),
        api_key=optional_string(model_api_config.get("api_key"), "model_api.api_key"),
        system_prompt=optional_string(config.get("system_prompt"), "system_prompt") or DEFAULT_SYSTEM_PROMPT,
        temperature=float_or_none(eval_config.get("temperature")),
        request_timeout=float(eval_config.get("request_timeout", 120.0)),
        max_concurrency=cli_args.max_concurrency
        if cli_args.max_concurrency is not None
        else int_config(eval_config.get("max_concurrency"), 1, parse_max_concurrency),
        num_samples=cli_args.num_samples
        if cli_args.num_samples is not None
        else int_config(eval_config.get("num_samples"), 1, parse_num_samples),
        shard_count=cli_args.shard_count
        if cli_args.shard_count is not None
        else int_config(eval_config.get("shard_count"), 1, parse_shard_count),
        shard_index=cli_args.shard_index
        if cli_args.shard_index is not None
        else int_config(eval_config.get("shard_index"), 0, parse_shard_index),
        strict=bool_config(eval_config.get("strict"), False),
        min_pass_rate=cli_args.min_pass_rate
        if cli_args.min_pass_rate is not None
        else min_pass_rate_config(eval_config.get("min_pass_rate")),
        prompt_ids=cli_args.prompt_ids or optional_string_list(eval_config.get("prompt_ids"), "eval.prompt_ids"),
        prompt_styles=cli_args.prompt_styles
        or optional_string_list(eval_config.get("prompt_styles"), "eval.prompt_styles"),
        exclude_prompt_ids=cli_args.exclude_prompt_ids
        or optional_string_list(eval_config.get("exclude_prompt_ids"), "eval.exclude_prompt_ids"),
        exclude_prompt_styles=cli_args.exclude_prompt_styles
        or optional_string_list(eval_config.get("exclude_prompt_styles"), "eval.exclude_prompt_styles"),
        results_csv=output_path(output_dir, prefix, "rows.csv", bool_config(output_config.get("results_csv"), True)),
        results_json=output_path(output_dir, prefix, "rows.json", bool_config(output_config.get("results_json"), True)),
        summary_csv=output_path(output_dir, prefix, "summary.csv", bool_config(output_config.get("summary_csv"), True)),
        summary_json=output_path(
            output_dir, prefix, "summary.json", bool_config(output_config.get("summary_json"), True)
        ),
        model_prices=model_prices,
        quiet=cli_args.quiet or bool_config(output_config.get("quiet"), False),
        no_final_table=bool_config(output_config.get("no_final_table"), False),
        capture_raw_response=bool_config(output_config.get("capture_raw_response"), False),
    )


def plots_enabled(config: dict[str, Any], cli_args: argparse.Namespace) -> bool:
    """Return whether run-level plot generation should occur."""
    if cli_args.no_plots:
        return False
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")
    return bool_config(output_config.get("plots"), True)


def write_run_report(**kwargs):
    """Import lazily and write a Markdown benchmark run report."""
    from gen_benchmark_report import write_run_report as _write_run_report

    return _write_run_report(**kwargs)


def generate_plots(
    config: dict[str, Any],
    output_dir: Path,
    summary_csv: Path,
    quiet: bool,
    min_pass_rate: float | None = None,
) -> list[Path]:
    """Generate score, token, and optional cost plots for a completed run."""
    output_config = config.get("output", {})
    if not isinstance(output_config, dict):
        raise ValueError("Run config field 'output' must be an object when provided")

    prefix = str(output_config.get("prefix") or "tool_call")
    score_field = str(output_config.get("score_field") or DEFAULT_SCORE_FIELD)
    token_field = str(output_config.get("token_field") or DEFAULT_TOKEN_FIELD)
    cost_field = str(output_config.get("cost_field") or DEFAULT_COST_FIELD)
    group_prompt_styles = not bool_config(output_config.get("plot_prompt_details"), False)
    score_output = output_dir / f"{prefix}_score.png"
    tokens_output = output_dir / f"{prefix}_tokens.png"
    cost_output = output_dir / f"{prefix}_cost.png"

    rows = load_rows(summary_csv)
    score_value_format = "{:.2f}" if score_field.endswith("_rate") or score_field == "pass_rate" else "{:.0f}"
    score_xlabel = (
        "Stacked score rate across test cases"
        if score_field.endswith("_rate") or score_field == "pass_rate"
        else "Stacked total score across test cases"
    )

    plot_stacked(
        rows=rows,
        value_field=score_field,
        output_path=score_output,
        title="MCP Tool-Call Evaluation Score By Model",
        xlabel=score_axis_label(rows, score_field, score_xlabel),
        value_format=score_value_format,
        legend_title="Test case (mean block score)",
        draw_flavor_boundaries=True,
        show_flavor_order_box=True,
        group_prompt_styles=group_prompt_styles,
        reference_lines=score_reference_lines(rows, score_field, min_pass_rate),
    )
    plot_stacked(
        rows=rows,
        value_field=token_field,
        output_path=tokens_output,
        title="MCP Tool-Call Evaluation Token Use By Model",
        xlabel=axis_label_with_case_count(rows, "Stacked average total tokens across test cases"),
        value_format="{:.0f}",
        legend_title="Test case (mean block value)",
        draw_flavor_boundaries=True,
        show_flavor_order_box=True,
        group_prompt_styles=group_prompt_styles,
    )
    wrote_cost_plot = False
    if has_numeric_value(rows, cost_field):
        total_cost = sum_numeric_values(rows, cost_field)
        plot_stacked(
            rows=rows,
            value_field=cost_field,
            output_path=cost_output,
            title=f"MCP Tool-Call Evaluation Cost By Model (Total: {format_usd(total_cost)})",
            xlabel=axis_label_with_case_count(rows, "Stacked actual cost across test cases (USD)"),
            value_format="{:.6f}",
            legend_title="Test case",
            show_legend_values=False,
            row_annotations=missing_cost_annotations(rows, cost_field),
        )
        wrote_cost_plot = True

    if not quiet:
        print(f"Wrote {score_output}")
        print(f"Wrote {tokens_output}")
        if wrote_cost_plot:
            print(f"Wrote {cost_output}")
        else:
            print(f"Skipping cost plot because {cost_field!r} has no numeric values.")
    plot_paths = [score_output, tokens_output]
    if wrote_cost_plot:
        plot_paths.append(cost_output)
    return plot_paths


def parse_args() -> argparse.Namespace:
    """Parse the run-config CLI for benchmark evaluation."""
    parser = argparse.ArgumentParser(description="Run MCP tool-call evaluation from a JSON run config.")
    parser.add_argument("--run-config", required=True, type=Path, help="JSON run configuration")
    parser.add_argument("--models", nargs="+", help="Explicit model names to evaluate")
    parser.add_argument("--models-file", type=Path, help="Override run config model file")
    parser.add_argument("--level", type=parse_level, help="Override maximum model level from a level-aware models file")
    parser.add_argument("--num-samples", "-n", type=parse_num_samples, help="Override number of samples")
    parser.add_argument("--max-concurrency", "-c", type=parse_max_concurrency, help="Override max concurrency")
    parser.add_argument("--shard-count", type=parse_shard_count, help="Override shard count")
    parser.add_argument("--shard-index", type=parse_shard_index, help="Override shard index")
    parser.add_argument("--min-pass-rate", type=parse_min_pass_rate, help="Override eval.min_pass_rate")
    parser.add_argument(
        "--prompt-ids",
        type=parse_prompt_filter_list,
        help="Comma-separated exact prompt IDs to include",
    )
    parser.add_argument(
        "--prompt-styles",
        type=parse_prompt_filter_list,
        help="Comma-separated root prompt styles to include",
    )
    parser.add_argument(
        "--exclude-prompt-ids",
        type=parse_prompt_filter_list,
        help="Comma-separated exact prompt IDs to exclude",
    )
    parser.add_argument(
        "--exclude-prompt-styles",
        type=parse_prompt_filter_list,
        help="Comma-separated root prompt styles to exclude",
    )
    parser.add_argument("--output-dir", type=Path, help="Override base output directory")
    parser.add_argument("--no-plots", action="store_true", help="Disable plot generation")
    parser.add_argument("--no-manage-servers", action="store_true", help="Do not start servers from run config")
    parser.add_argument("--quiet", action="store_true", help="Suppress live progress output")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    """Run the configured benchmark, including optional servers, plots, and report."""
    config_path = args.run_config.resolve()
    config = load_run_config(config_path)
    config_dir = config_path.parent

    models_file_override = args.models_file.resolve() if args.models_file is not None else None
    output_dir_override = args.output_dir.resolve() if args.output_dir is not None else None
    level = level_from_config(config, args)
    models = models_from_config(config, config_dir, models_file_override, args.models, level)
    output_dir = build_output_dir(config, config_dir, output_dir_override)
    eval_args = build_eval_args(config, config_dir, args, output_dir, models)
    server_settings = server_management_settings(config, config_dir, args)

    managed_servers = None
    try:
        if server_settings.enabled:
            managed_servers = start_managed_servers(
                server_settings,
                eval_args.cases,
                output_dir,
                eval_args.quiet,
            )
            eval_args.cases = managed_servers.cases_path

        eval_status = await run_evaluator(eval_args)
    finally:
        stop_managed_servers(managed_servers, eval_args.quiet)

    plot_paths = []
    if plots_enabled(config, args):
        if eval_args.summary_csv is not None and eval_args.summary_csv.exists():
            plot_paths = generate_plots(
                config,
                output_dir,
                eval_args.summary_csv,
                eval_args.quiet,
                min_pass_rate=eval_args.min_pass_rate,
            )
        elif not eval_args.quiet:
            print(f"Skipping plot generation because {eval_args.summary_csv} was not created.", file=sys.stderr)

    report_path = report_output_path(config, output_dir)
    if report_path is not None:
        write_run_report(
            cases_path=eval_args.cases,
            run_config_path=config_path,
            run_config=config,
            eval_args=eval_args,
            output_dir=output_dir,
            report_path=report_path,
            eval_status=eval_status,
            plot_paths=plot_paths,
            detailed_rows_path=eval_args.results_json,
        )
        if not eval_args.quiet:
            print(f"Wrote benchmark run report to {report_path}")

    if not eval_args.quiet:
        print(f"Wrote eval results to {output_dir}")
    return eval_status


def main() -> int:
    """CLI entrypoint for the benchmark runner."""
    try:
        return asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print("Error:", file=sys.stderr)
        for message in exception_messages(exc):
            for line in str(message).splitlines():
                print(f"  - {line}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
