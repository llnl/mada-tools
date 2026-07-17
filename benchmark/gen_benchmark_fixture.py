#!/usr/bin/env python3
"""Generate prompt variants for MCP tool-call benchmark fixtures."""

from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import json
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_SRC = REPO_ROOT / "src"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_SRC) not in sys.path:
    sys.path.insert(0, str(REPO_SRC))

from mcp_tool_call_eval import connect_server, exception_messages, expected_call_from_test_case  # noqa: E402

from mada_tools.shared.config import get_config_value, load_json_object_config  # noqa: E402

DEFAULT_BASE_URL = "https://livai-api.llnl.gov/v1"
DEFAULT_GENERATION_ATTEMPTS = 3
DEFAULT_STYLES = [
    {
        "id": "natural",
        "description": "Plain conversational request from a capable user.",
    },
    {
        "id": "terse",
        "description": "Short command-like request with minimal extra words.",
    },
    {
        "id": "direct",
        "description": "Explicit instruction that names the intended server, tool, and important arguments.",
    },
]
KNOWN_SERVER_PATHS = {
    "flux": REPO_SRC / "mada_tools" / "scheduler" / "flux" / "server.py",
    "slurm": REPO_SRC / "mada_tools" / "scheduler" / "slurm" / "server.py",
    "vertex_cfd": REPO_SRC / "mada_tools" / "simulation" / "vertex_cfd" / "server.py",
    "professor": REPO_SRC / "mada_tools" / "surrogate" / "professor" / "server.py",
    "job_monitor": REPO_SRC / "mada_tools" / "monitor" / "job_monitor" / "server.py",
    "maestro_command_executor": REPO_SRC / "mada_tools" / "workflow" / "weave" / "maestro" / "server.py",
}


@dataclass(frozen=True)
class GenerationStyle:
    id: str
    description: str


@dataclass(frozen=True)
class PromptSlot:
    id: str
    style: GenerationStyle


@dataclass(frozen=True)
class GenerationSettings:
    model: str
    num_prompts: int
    styles: list[GenerationStyle]
    temperature: float | None
    request_timeout: float


def positive_int(option_name: str):
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{option_name} must be an integer") from exc
        if parsed < 1:
            raise argparse.ArgumentTypeError(f"{option_name} must be at least 1")
        return parsed

    return parse


parse_num_prompts = positive_int("--num-prompts")


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return loaded


def validate_input_fixture(fixture: dict[str, Any]) -> None:
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


def load_input_fixture(path: Path) -> dict[str, Any]:
    fixture = load_json_object(path)
    validate_input_fixture(fixture)
    return fixture


def parse_styles(raw_styles: Any) -> list[GenerationStyle]:
    if raw_styles is None:
        raw_styles = DEFAULT_STYLES
    if not isinstance(raw_styles, list) or not raw_styles:
        raise ValueError("prompt_generation.styles must be a non-empty list")

    styles: list[GenerationStyle] = []
    seen_ids: set[str] = set()
    for index, style in enumerate(raw_styles, start=1):
        if not isinstance(style, dict):
            raise ValueError(f"prompt_generation.styles[{index}] must be an object")
        style_id = style.get("id")
        description = style.get("description")
        if not isinstance(style_id, str) or not style_id:
            raise ValueError(f"prompt_generation.styles[{index}].id must be a non-empty string")
        if style_id in seen_ids:
            raise ValueError(f"Duplicate prompt style id: {style_id}")
        if not isinstance(description, str) or not description:
            raise ValueError(f"prompt_generation.styles[{index}].description must be a non-empty string")
        seen_ids.add(style_id)
        styles.append(GenerationStyle(id=style_id, description=description))
    return styles


def select_styles(styles: list[GenerationStyle], style_ids: list[str] | None) -> list[GenerationStyle]:
    if not style_ids:
        return styles
    by_id = {style.id: style for style in styles}
    selected = []
    for style_id in style_ids:
        if style_id not in by_id:
            raise ValueError(f"Unknown prompt style id: {style_id}")
        selected.append(by_id[style_id])
    return selected


def build_generation_settings(
    fixture: dict[str, Any],
    api_config: dict[str, Any],
    args: argparse.Namespace,
) -> GenerationSettings:
    prompt_generation = fixture.get("prompt_generation", {})
    if prompt_generation is None:
        prompt_generation = {}
    if not isinstance(prompt_generation, dict):
        raise ValueError("Fixture prompt_generation must be an object when provided")

    styles = select_styles(parse_styles(prompt_generation.get("styles")), args.styles)
    model = args.model or prompt_generation.get("model") or get_config_value(api_config, "model", expand_env=False)
    if not isinstance(model, str) or not model:
        raise ValueError("Generation model is required. Provide --model or prompt_generation.model.")

    num_prompts = args.num_prompts or prompt_generation.get("num_prompts") or 1
    if not isinstance(num_prompts, int) or num_prompts < 1:
        raise ValueError("num_prompts must be an integer greater than or equal to 1")

    temperature = args.temperature
    if temperature is None and "temperature" in prompt_generation:
        temperature = float(prompt_generation["temperature"])

    request_timeout = args.request_timeout
    if request_timeout is None:
        request_timeout = float(prompt_generation.get("request_timeout", 120.0))

    return GenerationSettings(
        model=model,
        num_prompts=num_prompts,
        styles=styles,
        temperature=temperature,
        request_timeout=request_timeout,
    )


def prompt_slots(styles: list[GenerationStyle], num_prompts_per_style: int) -> list[PromptSlot]:
    slots = []
    for prompt_index in range(1, num_prompts_per_style + 1):
        for style in styles:
            prompt_id = style.id if prompt_index == 1 else f"{style.id}_{prompt_index}"
            slots.append(PromptSlot(id=prompt_id, style=style))
    return slots


def prompt_slots_for_style(style: GenerationStyle, num_prompts: int) -> list[PromptSlot]:
    return [
        PromptSlot(id=style.id if prompt_index == 1 else f"{style.id}_{prompt_index}", style=style)
        for prompt_index in range(1, num_prompts + 1)
    ]


def resolve_api_settings(args: argparse.Namespace) -> tuple[str, str, dict[str, Any]]:
    api_config = load_json_object_config(args.config)
    base_url = args.base_url or get_config_value(api_config, "base_url") or os.getenv("API_BASE_URL", DEFAULT_BASE_URL)
    api_key = args.api_key or get_config_value(api_config, "api_key") or os.getenv("API_KEY")
    if not api_key:
        api_key = "dummy" if base_url.startswith(("http://localhost", "http://127.0.0.1")) else None
    if not api_key:
        raise ValueError("API key is required. Provide --api-key, --config, or set API_KEY.")
    return api_key, base_url, api_config


def annotation_to_schema_type(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "string"
    text = ast.unparse(annotation)
    if text in {"str", "Optional[str]", "typing.Optional[str]"} or text.endswith(" | None"):
        if text.startswith("str") or "str" in text:
            return "string"
    if "int" in text:
        return "integer"
    if "float" in text:
        return "number"
    if "bool" in text:
        return "boolean"
    if "dict" in text or "Dict" in text:
        return "object"
    if "list" in text or "List" in text:
        return "array"
    return "string"


def literal_default(node: ast.expr | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except Exception:
        return ast.unparse(node)


def parse_arg_descriptions(docstring: str) -> dict[str, str]:
    lines = docstring.splitlines()
    in_args = False
    descriptions: dict[str, str] = {}
    current_name: str | None = None
    for raw_line in lines:
        line = raw_line.strip()
        if line == "Args:":
            in_args = True
            current_name = None
            continue
        if in_args and line in {"Returns:", "Raises:", "Examples:"}:
            break
        if not in_args or not line:
            continue
        if ":" in line and not line.startswith(("`", "-")):
            name, description = line.split(":", 1)
            name = name.strip()
            if name:
                descriptions[name] = description.strip()
                current_name = name
                continue
        if current_name:
            descriptions[current_name] = f"{descriptions[current_name]} {line}".strip()
    return descriptions


def function_to_openai_tool(function: ast.FunctionDef, server_name: str) -> dict[str, Any]:
    docstring = ast.get_docstring(function) or ""
    arg_descriptions = parse_arg_descriptions(docstring)
    args = function.args.args
    defaults = [None] * (len(args) - len(function.args.defaults)) + list(function.args.defaults)

    properties: dict[str, Any] = {}
    required = []
    for arg, default_node in zip(args, defaults):
        if arg.arg == "self":
            continue
        schema: dict[str, Any] = {"type": annotation_to_schema_type(arg.annotation)}
        if arg.arg in arg_descriptions:
            schema["description"] = arg_descriptions[arg.arg]
        if default_node is None:
            required.append(arg.arg)
        else:
            schema["default"] = literal_default(default_node)
        properties[arg.arg] = schema

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required

    return {
        "type": "function",
        "function": {
            "name": function.name,
            "description": f"[{server_name}] {docstring}",
            "parameters": parameters,
        },
    }


def is_mcp_tool_decorator(decorator: ast.expr) -> bool:
    target = decorator
    if isinstance(target, ast.Call):
        target = target.func
    return isinstance(target, ast.Attribute) and target.attr == "tool"


def parse_server_py_tools(path: Path, server_name: str) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_register_tools":
            continue
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and any(is_mcp_tool_decorator(d) for d in child.decorator_list):
                tools.append(function_to_openai_tool(child, server_name))
    if not tools:
        raise ValueError(f"No @self.mcp.tool functions found in {path}")
    return tools


def module_to_server_path(module_name: str) -> Path:
    return REPO_SRC / Path(*module_name.split(".")).with_suffix(".py")


def resolve_server_path(server_name: str, server_config: dict[str, Any]) -> Path:
    raw_path = server_config.get("server_py")
    if isinstance(raw_path, str) and raw_path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    module_name = server_config.get("module")
    if isinstance(module_name, str) and module_name:
        return module_to_server_path(module_name)

    if server_name in KNOWN_SERVER_PATHS:
        return KNOWN_SERVER_PATHS[server_name]
    raise ValueError(
        f"No static server.py fallback known for MCP server '{server_name}'. "
        "Add mcp_servers.<server>.server_py or mcp_servers.<server>.module."
    )


async def live_tools_for_server(server_name: str, server_config: dict[str, Any], quiet: bool) -> list[dict[str, Any]]:
    async with AsyncExitStack() as stack:
        _session, tools = await connect_server(server_name, server_config, stack, quiet)
        return tools


async def tools_for_server(
    server_name: str,
    server_config: dict[str, Any],
    source: str,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    if source in {"auto", "live"}:
        try:
            return await live_tools_for_server(server_name, server_config, quiet)
        except Exception as exc:
            if source == "live":
                raise
            if not quiet:
                print(
                    f"Warning: live MCP discovery failed for '{server_name}'; using static server.py fallback.",
                    file=sys.stderr,
                )
                for message in exception_messages(exc):
                    print(f"  - {message}", file=sys.stderr)

    server_path = resolve_server_path(server_name, server_config)
    return parse_server_py_tools(server_path, server_name)


async def discover_tools(
    fixture: dict[str, Any],
    source: str,
    quiet: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    required_servers = sorted({test_case["server"] for test_case in fixture["tests"]})
    server_configs = fixture["mcp_servers"]
    discovered = {}
    for server_name in required_servers:
        discovered[server_name] = await tools_for_server(server_name, server_configs[server_name], source, quiet)
    return discovered


def generation_system_prompt() -> str:
    return (
        "You generate realistic user prompts for MCP tool-call benchmark fixtures. "
        "Each prompt should be something a user could say that should lead an LLM to call the expected tool with "
        "the expected structured arguments. Return only JSON."
    )


def generation_user_prompt(
    test_case: dict[str, Any],
    tools: list[dict[str, Any]],
    slots: list[PromptSlot],
) -> str:
    expected_call = test_case["expected_call"]
    style_specs = [{"id": slot.id, "style": slot.style.id, "description": slot.style.description} for slot in slots]
    payload = {
        "case_id": test_case["id"],
        "server": test_case["server"],
        "available_tools": tools,
        "expected_call": expected_call,
        "requested_prompts": style_specs,
        "output_schema": {
            "prompts": [
                {
                    "id": "must exactly match a requested prompt id",
                    "text": "the user prompt text only",
                }
            ]
        },
    }
    return (
        "Generate benchmark prompt variants for this MCP tool-call case.\n"
        "Rules:\n"
        "- Produce exactly one prompt for each requested prompt id.\n"
        "- The prompt must not mention that it is a benchmark or fixture.\n"
        "- The prompt should naturally imply the expected tool and arguments.\n"
        "- Do not include tool-call JSON as the user's prompt unless the expected argument itself is a "
        "literal JSON string.\n"
        "- Return a JSON object with only a 'prompts' list.\n\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )


def parse_model_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Generation model did not return valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Generation model JSON response must be an object")
    return parsed


def validate_generated_prompts(payload: dict[str, Any], expected_ids: list[str]) -> list[dict[str, str]]:
    prompts = payload.get("prompts")
    if not isinstance(prompts, list):
        raise ValueError("Generation response must contain a 'prompts' list")

    normalized: list[dict[str, str]] = []
    seen_ids = set()
    for index, prompt in enumerate(prompts, start=1):
        if not isinstance(prompt, dict):
            raise ValueError(f"Generated prompt #{index} must be an object")
        prompt_id = prompt.get("id")
        text = prompt.get("text")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError(f"Generated prompt #{index}.id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Generated prompt {prompt_id}.text must be a non-empty string")
        if prompt_id in seen_ids:
            raise ValueError(f"Duplicate generated prompt id: {prompt_id}")
        seen_ids.add(prompt_id)
        normalized.append({"id": prompt_id, "text": text.strip()})

    if set(seen_ids) != set(expected_ids):
        raise ValueError(f"Generated prompt ids {sorted(seen_ids)} do not match expected ids {sorted(expected_ids)}")
    return sorted(normalized, key=lambda prompt: expected_ids.index(prompt["id"]))


async def generate_case_prompts(
    client: Any,
    settings: GenerationSettings,
    test_case: dict[str, Any],
    tools: list[dict[str, Any]],
) -> list[dict[str, str]]:
    expected_slots = prompt_slots(settings.styles, settings.num_prompts)
    prompts = []
    for style in settings.styles:
        prompts.extend(
            await generate_slot_prompts(
                client,
                settings,
                test_case,
                tools,
                prompt_slots_for_style(style, settings.num_prompts),
            )
        )
    expected_ids = [slot.id for slot in expected_slots]
    return sorted(prompts, key=lambda prompt: expected_ids.index(prompt["id"]))


async def generate_slot_prompts(
    client: Any,
    settings: GenerationSettings,
    test_case: dict[str, Any],
    tools: list[dict[str, Any]],
    slots: list[PromptSlot],
) -> list[dict[str, str]]:
    expected_ids = [slot.id for slot in slots]
    messages = [
        {"role": "system", "content": generation_system_prompt()},
        {"role": "user", "content": generation_user_prompt(test_case, tools, slots)},
    ]
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
    }
    if settings.temperature is not None:
        kwargs["temperature"] = settings.temperature

    last_error: ValueError | None = None
    for attempt in range(1, DEFAULT_GENERATION_ATTEMPTS + 1):
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        if not isinstance(content, str):
            last_error = ValueError("Generation model returned an empty response")
        else:
            try:
                return validate_generated_prompts(parse_model_json(content), expected_ids)
            except ValueError as exc:
                last_error = exc

        if attempt < DEFAULT_GENERATION_ATTEMPTS:
            kwargs["messages"] = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        f"Your previous response was invalid: {last_error}. "
                        f"Return exactly these prompt ids and no others: {', '.join(expected_ids)}."
                    ),
                },
            ]

    assert last_error is not None
    raise last_error


async def generate_fixture(
    fixture: dict[str, Any],
    tools_by_server: dict[str, list[dict[str, Any]]],
    client: Any,
    settings: GenerationSettings,
    quiet: bool = False,
) -> dict[str, Any]:
    output = copy.deepcopy(fixture)
    for index, test_case in enumerate(output["tests"], start=1):
        if not quiet:
            print(f"Generating prompts for {test_case['server']}/{test_case['id']} ({index}/{len(output['tests'])})")
        test_case["prompts"] = await generate_case_prompts(
            client,
            settings,
            test_case,
            tools_by_server[test_case["server"]],
        )
    return output


def parse_style_ids(value: str) -> list[str]:
    style_ids = [item.strip() for item in value.split(",") if item.strip()]
    if not style_ids:
        raise argparse.ArgumentTypeError("--styles must include at least one style id")
    return style_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate prompt variants for MCP tool-call benchmark fixtures.")
    parser.add_argument("--cases", required=True, type=Path, help="Input fixture with mcp_servers and tests")
    parser.add_argument("--output", required=True, type=Path, help="Write generated fixture JSON here")
    parser.add_argument("--config", type=Path, help="Optional JSON config with model.api_key and model.base_url")
    parser.add_argument("--model", help="Generation model name")
    parser.add_argument("--base-url", help="OpenAI-compatible API base URL")
    parser.add_argument("--api-key", help="OpenAI-compatible API key")
    parser.add_argument(
        "--num-prompts",
        "-n",
        type=parse_num_prompts,
        help="Generated prompts per selected style for each test case",
    )
    parser.add_argument(
        "--styles",
        type=parse_style_ids,
        help="Comma-separated style ids from prompt_generation.styles",
    )
    parser.add_argument("--temperature", type=float, help="Optional generation temperature")
    parser.add_argument("--request-timeout", type=float, help="LLM request timeout in seconds")
    parser.add_argument(
        "--server-source",
        choices=["auto", "live", "static"],
        default="auto",
        help="Where to get MCP tool schemas from (default: auto)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    from openai import AsyncOpenAI

    fixture = load_input_fixture(args.cases)
    api_key, base_url, api_config = resolve_api_settings(args)
    settings = build_generation_settings(fixture, api_config, args)
    tools_by_server = await discover_tools(fixture, args.server_source, args.quiet)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=settings.request_timeout)
    output = await generate_fixture(fixture, tools_by_server, client, settings, args.quiet)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    if not args.quiet:
        print(f"Wrote generated fixture to {args.output}")
    return 0


def main() -> int:
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
