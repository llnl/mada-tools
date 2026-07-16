#!/usr/bin/env python3
"""Evaluate LLM MCP tool-call selection and arguments from JSON fixtures."""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import os
import shlex
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
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
    input_cost_per_token: float
    output_cost_per_token: float


@dataclass
class ToolCallResult:
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
    tool: str
    arguments: dict[str, Any]
    match_mode: str = "subset"
    match_profile: str | None = None


@dataclass(frozen=True)
class EvalWorkItem:
    ordinal: int
    model: str
    test_case: dict[str, Any]
    prompt: dict[str, str]
    sample_index: int


@dataclass
class CompletedWorkItem:
    work_item: EvalWorkItem
    row: dict[str, Any]
    detailed_row: dict[str, Any]
    passed: bool
    error_type: str | None
    error: str | None


@dataclass(frozen=True)
class IntegerArgumentValidator:
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


parse_num_samples = IntegerArgumentValidator("--num-samples", 1)
parse_max_concurrency = IntegerArgumentValidator("--max-concurrency", 1)
parse_shard_count = IntegerArgumentValidator("--shard-count", 1)
parse_shard_index = IntegerArgumentValidator("--shard-index", 0)


def parse_level(value: str) -> int:
    try:
        return parse_model_level(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


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
    if args.shard_index >= args.shard_count:
        raise ValueError("--shard-index must be less than --shard-count")


def expected_call_from_test_case(test_case: dict[str, Any]) -> ExpectedCall:
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
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": f"[{server_name}] {tool.description or ''}",
            "parameters": tool.inputSchema,
        },
    }


def progress(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, flush=True)


def model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def exception_messages(exc: BaseException) -> list[str]:
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
    if not isinstance(value, list) or len(value) < 3 or not isinstance(value[0], str):
        return False
    if parameter_type is not None:
        return value[0] == parameter_type
    return value[0] in {"def", "exe", "cli"}


def is_zip_parameter_spec(value: Any, parameter_type: str | None = None) -> bool:
    return is_parameter_spec(value, parameter_type) and len(value) >= 3 and value[1] == "zip"


def zip_group_id(spec: list[Any]) -> Any:
    return spec[3] if len(spec) >= 4 else 1


def set_zip_group_id(spec: list[Any], group_id: Any) -> None:
    if len(spec) >= 4:
        spec[3] = group_id
    else:
        spec.append(group_id)


def parameter_specs_match_ignoring_zip_group(expected: Any, actual: Any) -> bool:
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
    if not expected or len(expected) > len(tokens):
        return False
    return any(tokens[index : index + len(expected)] == expected for index in range(len(tokens) - len(expected) + 1))


def normalize_cli_parameter_values(expected_arguments: dict[str, Any], actual_arguments: dict[str, Any]) -> None:
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
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 3)


def sum_present(values: list[int | float | None]) -> int | float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    total = sum(present)
    if isinstance(total, float):
        return round(total, 10)
    return total


def summarize(fixture: dict[str, Any], rows: list[dict[str, Any]], num_samples: int) -> list[dict[str, Any]]:
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
    return len(models) * sum(len(normalize_prompts(test_case)) for test_case in fixture["tests"]) * num_samples


def build_work_items(
    fixture: dict[str, Any],
    models: list[str],
    num_samples: int,
    shard_count: int,
    shard_index: int,
) -> list[EvalWorkItem]:
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


async def run(args: argparse.Namespace) -> int:
    from openai import AsyncOpenAI

    validate_shard_args(args)
    fixture = load_json(args.cases)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate LLM MCP tool-call behavior from JSON fixtures.")
    parser.add_argument("--cases", required=True, type=Path, help="JSON fixture with mcp_servers and tests")
    parser.add_argument("--config", type=Path, help="Optional JSON config with model.api_key and model.base_url")
    parser.add_argument("--models", nargs="+", help="Explicit model names to evaluate")
    parser.add_argument(
        "--models-file",
        type=Path,
        default=DEFAULT_MODELS_PATH,
        help=f"Model list file to use when --models is omitted (default: {DEFAULT_MODELS_PATH})",
    )
    parser.add_argument(
        "--level",
        type=parse_level,
        default=0,
        help="Maximum model level to include from a level-aware models file (default: 0)",
    )
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument("--system-prompt", help="Override the default system prompt")
    parser.add_argument("--temperature", type=float, help="Optional temperature to pass to the model")
    parser.add_argument("--request-timeout", type=float, default=120.0, help="LLM request timeout in seconds")
    parser.add_argument(
        "--max-concurrency",
        type=parse_max_concurrency,
        default=1,
        help="Maximum number of concurrent tool-call attempts per process (default: 1)",
    )
    parser.add_argument(
        "--num-samples",
        "-n",
        type=parse_num_samples,
        default=1,
        help="Number of tool-call samples to collect per prompt flavor (default: 1)",
    )
    parser.add_argument(
        "--shard-count",
        type=parse_shard_count,
        default=1,
        help="Total number of shards to split the eval matrix across (default: 1)",
    )
    parser.add_argument(
        "--shard-index",
        type=parse_shard_index,
        default=0,
        help="0-based shard index to execute from the sharded eval matrix (default: 0)",
    )
    parser.add_argument("--strict", action="store_true", help="Require exact argument equality")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        help="Minimum per-case prompt pass rate required for success, e.g. 1.0 or 0.8",
    )
    parser.add_argument("--results-csv", type=Path, help="Write per-prompt CSV results")
    parser.add_argument("--results-json", type=Path, help="Write detailed per-prompt JSON results")
    parser.add_argument("--summary-csv", type=Path, help="Write per-case summary CSV results")
    parser.add_argument("--summary-json", type=Path, help="Write per-case summary JSON results")
    parser.add_argument(
        "--model-prices",
        type=Path,
        default=DEFAULT_MODEL_PRICES_PATH if DEFAULT_MODEL_PRICES_PATH.exists() else None,
        help="JSON model pricing file used to compute token costs",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress live progress output")
    parser.add_argument("--no-final-table", action="store_true", help="Skip final console result tables")
    parser.add_argument(
        "--capture-raw-response",
        action="store_true",
        help="Include full raw OpenAI-compatible response objects in --results-json",
    )
    parsed = parser.parse_args()
    if parsed.models is None:
        try:
            parsed.models = load_models_file(parsed.models_file, parsed.level)
        except ValueError as exc:
            parser.error(str(exc))
    return parsed


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print("Error:", file=sys.stderr)
        for message in exception_messages(e):
            print(f"  - {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
