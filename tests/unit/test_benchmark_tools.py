import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "benchmark"

if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))


def load_benchmark_module(module_name: str, filename: str):
    script_path = BENCHMARK_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


eval_io = load_benchmark_module("eval_io", "eval_io.py")
populate_eval_models = load_benchmark_module("populate_eval_models", "populate_eval_models.py")
mcp_tool_call_eval = load_benchmark_module("mcp_tool_call_eval", "mcp_tool_call_eval.py")
plot_tool_call_eval_results = load_benchmark_module("plot_tool_call_eval_results", "plot_tool_call_eval_results.py")
run_tool_call_eval = load_benchmark_module("run_tool_call_eval", "run_tool_call_eval.py")
merge_tool_call_eval_results = load_benchmark_module("merge_tool_call_eval_results", "merge_tool_call_eval_results.py")
gen_benchmark_fixture = load_benchmark_module("gen_benchmark_fixture", "gen_benchmark_fixture.py")
gen_benchmark_report = load_benchmark_module(
    "gen_benchmark_report",
    "gen_benchmark_report.py",
)


# eval_io


class TestEvalIo:
    def test_load_models_file_filters_tsv_by_inclusive_level(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text(
            "# Level Model\n2 model-two\n0 model-zero\n1 model-one\n",
            encoding="utf-8",
        )

        assert eval_io.load_models_file(models_file, level=1) == ["model-zero", "model-one"]

    def test_load_models_file_defaults_tsv_to_level_zero(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("1 model-one\n0 model-zero\n", encoding="utf-8")

        assert eval_io.load_models_file(models_file) == ["model-zero"]

    def test_load_models_file_preserves_plain_text_behavior(self, tmp_path: Path):
        models_file = tmp_path / "models.txt"
        models_file.write_text("# comment\nmodel-a\n\nmodel-b\n", encoding="utf-8")

        assert eval_io.load_models_file(models_file, level=0) == ["model-a", "model-b"]

    def test_load_models_file_rejects_malformed_tsv_rows(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-a extra\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected '<level> <model>'"):
            eval_io.load_models_file(models_file)

    def test_load_models_file_rejects_negative_level(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("-1 model-a\n", encoding="utf-8")

        with pytest.raises(ValueError, match="must be at least 0"):
            eval_io.load_models_file(models_file)

    def test_write_model_level_file_uses_level_aware_tsv_header(self, tmp_path: Path):
        output = tmp_path / "models.tsv"

        eval_io.write_model_level_file(output, ["model-a", "model-b"], {"model-b": 2})

        assert output.read_text(encoding="utf-8") == (
            "# Shared eval model list that may be used in LLM testing.\n"
            "# One model per line with corresponding run level.\n"
            "# Set appropriate levels.\n"
            "# Comment out any model you may want to omit entirely from eval runs.\n"
            "# Level\tModel\n"
            "0\tmodel-a\n"
            "2\tmodel-b\n"
        )

    def test_load_model_levels_rejects_malformed_rows(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("1 model-a extra\n", encoding="utf-8")

        with pytest.raises(ValueError, match="expected '<level> <model>'"):
            eval_io.load_model_levels(models_file)


# populate_eval_models


class TestPopulateEvalModels:
    def test_extract_model_ids_dedupes_and_sorts(self):
        payload = {
            "data": [
                {"id": "model-b"},
                {"id": "model-a"},
                {"id": "model-b"},
                {"id": ""},
                {"name": "missing-id"},
            ]
        }

        assert populate_eval_models.extract_model_ids(payload) == ["model-a", "model-b"]

    def test_refresh_model_files_initializes_missing_curated_file(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"

        initialized = populate_eval_models.refresh_model_files(["model-a"], all_output, enabled_output)

        assert initialized is True
        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")
        assert enabled_output.read_text(encoding="utf-8") == all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_does_not_overwrite_existing_curated_file(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        curated_content = "# custom curated header\n1\tmodel-b\n"
        enabled_output.write_text(curated_content, encoding="utf-8")

        initialized = populate_eval_models.refresh_model_files(["model-a"], all_output, enabled_output)

        assert initialized is False
        assert enabled_output.read_text(encoding="utf-8") == curated_content
        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_preserves_known_curated_levels(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        enabled_output.write_text(
            "# Level Model\n2 model-b\n1 model-c\n",
            encoding="utf-8",
        )

        populate_eval_models.refresh_model_files(["model-a", "model-b"], all_output, enabled_output)

        assert "0\tmodel-a\n" in all_output.read_text(encoding="utf-8")
        assert "2\tmodel-b\n" in all_output.read_text(encoding="utf-8")

    def test_refresh_model_files_falls_back_to_existing_discovery_levels(self, tmp_path: Path):
        all_output = tmp_path / "eval_models_all.tsv"
        enabled_output = tmp_path / "eval_models.tsv"
        all_output.write_text(
            "# Level Model\n3 model-a\n",
            encoding="utf-8",
        )

        populate_eval_models.refresh_model_files(["model-a", "model-b"], all_output, enabled_output)

        contents = enabled_output.read_text(encoding="utf-8")
        assert "3\tmodel-a\n" in contents
        assert "0\tmodel-b\n" in contents


# mcp_tool_call_eval


def tool_result(arguments: dict[str, Any], tool_name: str = "generate_parameter_runs"):
    return mcp_tool_call_eval.ToolCallResult(
        tool_name=tool_name,
        tool_arguments=arguments,
        tool_arguments_raw=None,
        assistant_text=None,
        raw_message=None,
        raw_tool_calls=[],
        raw_response=None,
        usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        latency_ms=1,
    )


def make_test_case(
    arguments: dict[str, Any],
    tool: str = "generate_parameter_runs",
    mode: str = "subset",
    profile: str | None = "parameter_runs",
) -> dict[str, Any]:
    match: dict[str, Any] = {"mode": mode}
    if profile is not None:
        match["profile"] = profile
    return {
        "id": "case",
        "server": "server",
        "expected_call": {
            "tool": tool,
            "arguments": arguments,
            "match": match,
        },
        "prompts": [{"id": "direct", "text": "test"}],
    }


def fixture_with(test: dict[str, Any]) -> dict[str, Any]:
    return {"mcp_servers": {"server": {"url": "http://localhost:8000/mcp"}}, "tests": [test]}


class TestMcpToolCallEval:
    @pytest.mark.parametrize(
        ("parser", "value", "expected"),
        [
            (mcp_tool_call_eval.parse_num_samples, "1", 1),
            (mcp_tool_call_eval.parse_max_concurrency, "2", 2),
            (mcp_tool_call_eval.parse_shard_count, "3", 3),
            (mcp_tool_call_eval.parse_shard_index, "0", 0),
        ],
    )
    def test_integer_argument_validators_accept_valid_values(self, parser, value, expected):
        assert parser(value) == expected

    @pytest.mark.parametrize(
        ("parser", "value", "message"),
        [
            (mcp_tool_call_eval.parse_num_samples, "0", "--num-samples must be at least 1"),
            (mcp_tool_call_eval.parse_max_concurrency, "0", "--max-concurrency must be at least 1"),
            (mcp_tool_call_eval.parse_shard_count, "0", "--shard-count must be at least 1"),
            (mcp_tool_call_eval.parse_shard_index, "-1", "--shard-index must be at least 0"),
        ],
    )
    def test_integer_argument_validators_reject_values_below_minimum(self, parser, value, message):
        with pytest.raises(argparse.ArgumentTypeError, match=message):
            parser(value)

    def test_integer_argument_validator_rejects_non_integer_values(self):
        with pytest.raises(argparse.ArgumentTypeError, match="--num-samples must be an integer"):
            mcp_tool_call_eval.parse_num_samples("not-an-int")

    def test_parse_args_loads_default_models_from_level_file(self, tmp_path: Path, monkeypatch):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n1 model-one\n", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mcp_tool_call_eval.py",
                "--cases",
                "cases.json",
                "--models-file",
                str(models_file),
                "--level",
                "1",
            ],
        )

        args = mcp_tool_call_eval.parse_args()

        assert args.models == ["model-zero", "model-one"]

    def test_parse_args_explicit_models_bypass_level_file(self, tmp_path: Path, monkeypatch):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "mcp_tool_call_eval.py",
                "--cases",
                "cases.json",
                "--models",
                "model-explicit",
                "--models-file",
                str(models_file),
                "--level",
                "0",
            ],
        )

        args = mcp_tool_call_eval.parse_args()

        assert args.models == ["model-explicit"]

    @pytest.mark.parametrize(
        ("mutator", "message"),
        [
            (lambda case: case.pop("expected_call"), "expected_call object"),
            (lambda case: case["expected_call"].pop("tool"), "expected_call.tool"),
            (lambda case: case["expected_call"].pop("arguments"), "expected_call.arguments"),
            (lambda case: case["expected_call"]["match"].update({"mode": "loose"}), "match.mode"),
            (lambda case: case["expected_call"]["match"].update({"profile": "unknown"}), "match.profile"),
        ],
    )
    def test_validate_fixture_rejects_invalid_expected_call(self, mutator, message):
        case = make_test_case({})
        mutator(case)

        with pytest.raises(ValueError, match=message):
            mcp_tool_call_eval.validate_fixture(fixture_with(case))

    def test_load_json_rejects_legacy_expected_tool_schema(self, tmp_path: Path):
        path = tmp_path / "legacy.json"
        path.write_text(
            json.dumps(
                {
                    "mcp_servers": {"server": {"url": "http://localhost:8000/mcp"}},
                    "tests": [
                        {
                            "id": "legacy",
                            "server": "server",
                            "expected_tool": "generate_parameter_runs",
                            "expected_arguments": {},
                            "prompts": ["prompt"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="expected_call object"):
            mcp_tool_call_eval.load_json(path)

    def test_filter_fixture_prompts_includes_root_styles(self):
        case = make_test_case({})
        case["prompts"] = [
            {"id": "direct", "text": "direct"},
            {"id": "direct_2", "text": "direct two"},
            {"id": "natural", "text": "natural"},
            {"id": "lazy", "text": "lazy"},
        ]
        fixture = fixture_with(case)

        filtered = mcp_tool_call_eval.filter_fixture_prompts(fixture, include_prompt_styles=["direct", "natural"])

        assert [prompt["id"] for prompt in filtered["tests"][0]["prompts"]] == ["direct", "direct_2", "natural"]
        assert [prompt["id"] for prompt in fixture["tests"][0]["prompts"]] == [
            "direct",
            "direct_2",
            "natural",
            "lazy",
        ]

    def test_filter_fixture_prompts_includes_exact_ids_then_excludes_styles(self):
        case = make_test_case({})
        case["prompts"] = [
            {"id": "direct", "text": "direct"},
            {"id": "direct_2", "text": "direct two"},
            {"id": "natural", "text": "natural"},
        ]
        fixture = fixture_with(case)

        filtered = mcp_tool_call_eval.filter_fixture_prompts(
            fixture,
            include_prompt_ids=["direct", "direct_2", "natural"],
            exclude_prompt_styles=["direct"],
        )

        assert [prompt["id"] for prompt in filtered["tests"][0]["prompts"]] == ["natural"]

    def test_filter_fixture_prompts_rejects_empty_case_selection(self):
        case = make_test_case({})
        case["prompts"] = [{"id": "direct", "text": "direct"}]

        with pytest.raises(ValueError, match="removed all prompts"):
            mcp_tool_call_eval.filter_fixture_prompts(fixture_with(case), include_prompt_styles=["natural"])

    def test_exception_messages_formats_plain_exception(self):
        assert mcp_tool_call_eval.exception_messages(ValueError("bad value")) == ["ValueError: bad value"]

    def test_exception_messages_flattens_exception_group_shape(self):
        class FakeExceptionGroup(Exception):
            def __init__(self, exceptions: tuple[BaseException, ...]):
                super().__init__("group")
                self.exceptions = exceptions

        error = FakeExceptionGroup(
            (
                ValueError("bad value"),
                FakeExceptionGroup((RuntimeError("runtime failed"),)),
            )
        )

        assert mcp_tool_call_eval.exception_messages(error) == [
            "ValueError: bad value",
            "RuntimeError: runtime failed",
        ]

    def test_load_model_prices_extracts_token_prices(self, tmp_path: Path):
        prices_path = tmp_path / "prices.json"
        prices_path.write_text(
            json.dumps(
                {
                    "sample_spec": {"input_cost_per_token": 0},
                    "gpt-test": {
                        "input_cost_per_token": 0.001,
                        "output_cost_per_token": 0.002,
                        "mode": "chat",
                    },
                    "image-test": {"output_cost_per_image": 0.01},
                }
            ),
            encoding="utf-8",
        )

        prices = mcp_tool_call_eval.load_model_prices(prices_path)

        assert set(prices) == {"gpt-test"}
        assert prices["gpt-test"].input_cost_per_token == 0.001
        assert prices["gpt-test"].output_cost_per_token == 0.002

    def test_build_row_adds_actual_cost_fields(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        prompt = {"id": "direct", "text": "test"}
        result = mcp_tool_call_eval.ToolCallResult(
            tool_name="submit_job",
            tool_arguments={"command": "hostname"},
            tool_arguments_raw=None,
            assistant_text=None,
            raw_message=None,
            raw_tool_calls=[],
            raw_response=None,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            latency_ms=15,
        )
        prices = {"gpt-test": mcp_tool_call_eval.ModelPricing(0.001, 0.002)}

        row = mcp_tool_call_eval.build_row("gpt-test", case, prompt, 1, result, True, None, None, prices)

        assert row["input_token_price_usd"] == 0.001
        assert row["output_token_price_usd"] == 0.002
        assert row["input_cost_usd"] == 0.1
        assert row["output_cost_usd"] == 0.04
        assert row["total_cost_usd"] == 0.14

    def test_build_row_leaves_costs_empty_without_tokens_or_price(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        prompt = {"id": "direct", "text": "test"}
        result = mcp_tool_call_eval.ToolCallResult(
            tool_name="submit_job",
            tool_arguments={"command": "hostname"},
            tool_arguments_raw=None,
            assistant_text=None,
            raw_message=None,
            raw_tool_calls=[],
            raw_response=None,
            usage={"prompt_tokens": None, "completion_tokens": 20, "total_tokens": None},
            latency_ms=15,
        )

        row = mcp_tool_call_eval.build_row("unknown", case, prompt, 1, result, True, None, None, {})

        assert row["input_token_price_usd"] is None
        assert row["output_token_price_usd"] is None
        assert row["input_cost_usd"] is None
        assert row["output_cost_usd"] is None
        assert row["total_cost_usd"] is None

    def test_summarize_adds_total_tokens_and_costs(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        fixture = fixture_with(case)
        rows = [
            {
                "model": "gpt-test",
                "server": "server",
                "case_id": "case",
                "prompt_id": "direct",
                "sample_index": 1,
                "passed": True,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "input_cost_usd": 0.1,
                "output_cost_usd": 0.04,
                "total_cost_usd": 0.14,
                "latency_ms": 10,
            },
            {
                "model": "gpt-test",
                "server": "server",
                "case_id": "case",
                "prompt_id": "direct",
                "sample_index": 2,
                "passed": False,
                "prompt_tokens": 110,
                "completion_tokens": 25,
                "total_tokens": 135,
                "input_cost_usd": 0.11,
                "output_cost_usd": 0.05,
                "total_cost_usd": 0.16,
                "latency_ms": 20,
            },
        ]

        summary = mcp_tool_call_eval.summarize(fixture, rows, num_samples=2)[0]

        assert summary["total_prompt_tokens"] == 210
        assert summary["total_completion_tokens"] == 45
        assert summary["total_tokens"] == 255
        assert summary["input_cost_usd"] == 0.21
        assert summary["output_cost_usd"] == 0.09
        assert summary["total_cost_usd"] == 0.3

    def test_evaluate_result_accepts_generic_subset_extra_arguments(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_generic_exact_extra_arguments(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", mode="exact", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_strict_overrides_subset_mode(self):
        case = make_test_case({"command": "hostname"}, tool="submit_job", mode="subset", profile=None)
        result = tool_result({"command": "hostname", "nodes": 1}, tool_name="submit_job")

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=True)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_no_argument_tool(self):
        case = make_test_case({}, tool="clear_model", profile=None)
        result = tool_result({}, tool_name="clear_model")

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_wrong_tool(self):
        case = make_test_case({}, tool="clear_model", profile=None)
        result = tool_result({}, tool_name="start_cubit")

        passed, error_type, error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "wrong_tool"
        assert "clear_model" in error

    def test_evaluate_result_accepts_executable_parameter_alias_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "executable": ["exe", "discrete", ["skeleton_cpu"]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "skeleton_executable": ["exe", "discrete", ["skeleton_cpu"]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_zip_group_identifier_aliases_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], 1],
                    "source_scale": ["def", "zip", [1.0, 0.8], 1],
                    "right_source": ["def", "zip", ["right_a", "right_b"], 2],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], "source_group"],
                    "source_scale": ["def", "zip", [1.0, 0.8], "source_group"],
                    "right_source": ["def", "zip", ["right_a", "right_b"], "right_group"],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_collapsed_zip_groups_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "left_source": ["def", "zip", ["left_a", "left_b"], 1],
                    "right_source": ["def", "zip", ["right_a", "right_b"], 2],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "left_source": ["def", "zip", ["left_a", "left_b"], "same_group"],
                    "right_source": ["def", "zip", ["right_a", "right_b"], "same_group"],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_executable_zip_alias_with_group_identifier_alias(self):
        case = make_test_case(
            {
                "parameters": {
                    "right_source": ["def", "zip", ["right_a", "right_b"], 2],
                    "solver": ["exe", "zip", ["skeleton_cpu", "skeleton_gpu"], 2],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "right_source": ["def", "zip", ["right_a", "right_b"], "right_group"],
                    "executable": ["exe", "zip", ["skeleton_cpu", "skeleton_gpu"], "right_group"],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_executable_alias_without_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "executable": ["exe", "discrete", ["skeleton_cpu"]],
                },
            },
            profile=None,
        )
        result = tool_result(
            {
                "parameters": {
                    "skeleton_executable": ["exe", "discrete", ["skeleton_cpu"]],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_deck_file_path_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/grid_problem",
                "input_deck_entrypoint": "input.deck",
            }
        )
        result = tool_result(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/grid_problem/input.deck",
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_deck_file_path_with_null_entrypoint_with_profile(self):
        case = make_test_case(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/blast",
                "input_deck_entrypoint": "main.deck",
            }
        )
        result = tool_result(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/blast/main.deck",
                "input_deck_entrypoint": None,
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_deck_file_path_with_matching_entrypoint_with_profile(self):
        case = make_test_case(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip",
                "input_deck_entrypoint": "multi.deck",
            }
        )
        result = tool_result(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip/multi.deck",
                "input_deck_entrypoint": "multi.deck",
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_deck_file_path_with_conflicting_entrypoint_with_profile(self):
        case = make_test_case(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip",
                "input_deck_entrypoint": "multi.deck",
            }
        )
        result = tool_result(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/multi_zip/multi.deck",
                "input_deck_entrypoint": "other.deck",
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_absolute_dependency_paths_under_deck_path_with_profile(self):
        case = make_test_case(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/source_case",
                "dependency_paths": ["Materials", "Tables/table_a.dat"],
            }
        )
        result = tool_result(
            {
                "input_deck_path": "/tmp/mada_skeleton_eval/decks/source_case",
                "dependency_paths": [
                    "/tmp/mada_skeleton_eval/decks/source_case/Materials",
                    "/tmp/mada_skeleton_eval/decks/source_case/Tables/table_a.dat",
                ],
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_same_key_cli_expected_string_actual_tokens_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "restart_args": ["cli", "discrete", ["-restart old.chk"]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "restart_args": ["cli", "discrete", [["-restart", "old.chk"]]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_same_key_cli_expected_tokens_actual_string_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "log_args": ["cli", "discrete", [["--log", "debug"]]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "log_args": ["cli", "discrete", ["--log debug"]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_combined_cli_parameter_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "restart_flag": ["cli", "discrete", ["-r"]],
                    "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "cli_args": ["cli", "discrete", [["-r", "-dm", "last", "-v", "-visit"]]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_combined_cli_string_parameter_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "restart_flag": ["cli", "discrete", ["-r"]],
                    "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "cli_args": ["cli", "discrete", ["-r -dm last -v -visit"]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_missing_cli_tokens_with_parameter_runs_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "cli_args": ["cli", "discrete", [["-dm", "last"]]],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_rejects_scalar_non_cli_parameter_values_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], "source_group"],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "source_file": ["def", "zip", "src/a.deck", "source_group"],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_strict_mode_rejects_parameter_runs_normalization(self):
        case = make_test_case(
            {
                "parameters": {
                    "restart_flag": ["cli", "discrete", ["-r"]],
                    "dump_options": ["cli", "discrete", [["-dm", "last", "-v", "-visit"]]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "cli_args": ["cli", "discrete", [["-r", "-dm", "last", "-v", "-visit"]]],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=True)

        assert not passed
        assert error_type == "arg_mismatch"

    def test_evaluate_result_accepts_discrete_def_numeric_string_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "INCLUDE_EXTRA": ["def", "discrete", [1]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "INCLUDE_EXTRA": ["def", "discrete", ["1"]],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_accepts_json_string_values_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "material": ["def", "discrete", ["Aluminum", "Steel"]],
                    "plate_loc": ["def", "discrete", [5.0, 10.0]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "material": ["def", "discrete", '["Aluminum", "Steel"]'],
                    "plate_loc": ["def", "discrete", "[5.0, 10.0]"],
                },
            }
        )

        assert mcp_tool_call_eval.evaluate_result(case, result, strict=False) == (True, None, None)

    def test_evaluate_result_rejects_json_string_non_list_values_with_profile(self):
        case = make_test_case(
            {
                "parameters": {
                    "material": ["def", "discrete", ["Aluminum", "Steel"]],
                },
            }
        )
        result = tool_result(
            {
                "parameters": {
                    "material": ["def", "discrete", '"Aluminum"'],
                },
            }
        )

        passed, error_type, _error = mcp_tool_call_eval.evaluate_result(case, result, strict=False)

        assert not passed
        assert error_type == "arg_mismatch"


# run_tool_call_eval


def cli_overrides(**overrides):
    defaults = {
        "models_file": None,
        "level": None,
        "num_samples": None,
        "max_concurrency": None,
        "shard_count": None,
        "shard_index": None,
        "prompt_ids": None,
        "prompt_styles": None,
        "exclude_prompt_ids": None,
        "exclude_prompt_styles": None,
        "output_dir": None,
        "no_plots": False,
        "quiet": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestRunToolCallEval:
    def test_load_run_config_expands_env_vars(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("MODEL_ID", "gpt-test")
        config_path = tmp_path / "run.json"
        config_path.write_text(json.dumps({"models": ["${MODEL_ID}"]}), encoding="utf-8")

        assert run_tool_call_eval.load_run_config(config_path) == {"models": ["gpt-test"]}

    def test_build_eval_args_resolves_paths_and_outputs(self, tmp_path: Path):
        models_file = tmp_path / "models.txt"
        models_file.write_text("# comment\nmodel-a\n\nmodel-b\n", encoding="utf-8")
        cases = tmp_path / "cases.json"
        cases.write_text("{}", encoding="utf-8")
        config = {
            "name": "flux",
            "cases": "cases.json",
            "models_file": "models.txt",
            "output": {
                "directory": "results",
                "prefix": "flux_tool_call",
                "timestamped": False,
                "capture_raw_response": True,
            },
            "eval": {
                "num_samples": 2,
                "max_concurrency": 3,
                "shard_count": 4,
                "shard_index": 1,
                "prompt_styles": ["direct", "natural"],
                "exclude_prompt_ids": "direct_5",
            },
        }

        args = cli_overrides()
        models = run_tool_call_eval.models_from_config(config, tmp_path, None)
        output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, None)
        eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, args, output_dir, models)

        assert models == ["model-a", "model-b"]
        assert output_dir == tmp_path / "results"
        assert eval_args.cases == cases.resolve()
        assert eval_args.results_csv == tmp_path / "results" / "flux_tool_call_rows.csv"
        assert eval_args.results_json == tmp_path / "results" / "flux_tool_call_rows.json"
        assert eval_args.summary_csv == tmp_path / "results" / "flux_tool_call_summary.csv"
        assert eval_args.summary_json == tmp_path / "results" / "flux_tool_call_summary.json"
        assert eval_args.model_prices == run_tool_call_eval.DEFAULT_MODEL_PRICES_PATH
        assert eval_args.num_samples == 2
        assert eval_args.max_concurrency == 3
        assert eval_args.shard_count == 4
        assert eval_args.shard_index == 1
        assert eval_args.prompt_styles == ["direct", "natural"]
        assert eval_args.exclude_prompt_ids == ["direct_5"]
        assert eval_args.capture_raw_response is True

    def test_cli_overrides_replace_config_values(self, tmp_path: Path):
        config_models_file = tmp_path / "models.txt"
        config_models_file.write_text("model-a\n", encoding="utf-8")
        override_models_file = tmp_path / "small.txt"
        override_models_file.write_text("model-small\n", encoding="utf-8")
        config = {
            "cases": "cases.json",
            "models_file": "models.txt",
            "output": {"directory": "results", "timestamped": False},
            "eval": {"num_samples": 1, "max_concurrency": 1, "shard_count": 1, "shard_index": 0},
        }

        args = cli_overrides(
            models_file=override_models_file,
            num_samples=5,
            max_concurrency=6,
            shard_count=7,
            shard_index=2,
            prompt_styles=["terse"],
            exclude_prompt_styles=["lazy"],
            output_dir=tmp_path / "override-results",
        )
        models = run_tool_call_eval.models_from_config(config, tmp_path, args.models_file)
        output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, args.output_dir)
        eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, args, output_dir, models)

        assert models == ["model-small"]
        assert output_dir == tmp_path / "override-results"
        assert eval_args.num_samples == 5
        assert eval_args.max_concurrency == 6
        assert eval_args.shard_count == 7
        assert eval_args.shard_index == 2
        assert eval_args.prompt_styles == ["terse"]
        assert eval_args.exclude_prompt_styles == ["lazy"]

    def test_build_eval_args_allows_model_prices_override(self, tmp_path: Path):
        prices = tmp_path / "prices.json"
        prices.write_text("{}", encoding="utf-8")
        config = {
            "cases": "cases.json",
            "models": ["gpt-test"],
            "model_prices": "prices.json",
            "output": {"directory": "results", "timestamped": False},
        }

        output_dir = run_tool_call_eval.build_output_dir(config, tmp_path, None)
        eval_args = run_tool_call_eval.build_eval_args(config, tmp_path, cli_overrides(), output_dir, ["gpt-test"])

        assert eval_args.model_prices == prices.resolve()

    def test_report_output_path_defaults_to_prefix_report(self, tmp_path: Path):
        output_dir = tmp_path / "results"

        assert run_tool_call_eval.report_output_path({"output": {"prefix": "flux_tool_call"}}, output_dir) == (
            output_dir / "flux_tool_call_report.md"
        )

    def test_report_output_path_can_be_disabled_or_overridden(self, tmp_path: Path):
        output_dir = tmp_path / "results"

        assert run_tool_call_eval.report_output_path({"output": {"report": False}}, output_dir) is None
        assert run_tool_call_eval.report_output_path({"output": {"report_path": "custom.md"}}, output_dir) == (
            output_dir / "custom.md"
        )

    def test_models_from_config_filters_level_aware_file(self, tmp_path: Path):
        models_file = tmp_path / "models.tsv"
        models_file.write_text("0 model-zero\n1 model-one\n2 model-two\n", encoding="utf-8")
        config = {"models_file": "models.tsv"}

        assert run_tool_call_eval.models_from_config(config, tmp_path, None, level=1) == ["model-zero", "model-one"]

    def test_models_from_config_explicit_models_bypass_level_filtering(self, tmp_path: Path):
        config = {"models": ["model-two"]}

        assert run_tool_call_eval.models_from_config(config, tmp_path, None, level=0) == ["model-two"]

    def test_models_from_config_override_file_uses_level_filtering(self, tmp_path: Path):
        override_models_file = tmp_path / "override.tsv"
        override_models_file.write_text("0 model-zero\n1 model-one\n", encoding="utf-8")
        config = {"models": ["model-explicit"]}

        assert run_tool_call_eval.models_from_config(config, tmp_path, override_models_file, level=0) == ["model-zero"]

    def test_level_from_config_defaults_to_zero(self):
        assert run_tool_call_eval.level_from_config({}, cli_overrides()) == 0

    def test_level_from_config_cli_overrides_config(self):
        assert run_tool_call_eval.level_from_config({"level": 1}, cli_overrides(level=2)) == 2

    def test_missing_cost_annotations_marks_models_with_no_cost_data(self):
        rows = [
            {"model": "gpt-test", "case_id": "case-a", "total_cost_usd": ""},
            {"model": "gpt-test", "case_id": "case-b", "total_cost_usd": "n/a"},
            {"model": "gpt-test-2", "case_id": "case-a", "total_cost_usd": ""},
            {"model": "gpt-test-2", "case_id": "case-b", "total_cost_usd": 0.2},
        ]

        assert run_tool_call_eval.missing_cost_annotations(rows, "total_cost_usd") == {
            "gpt-test": "Missing Pricing",
        }

    def test_flavor_boundary_values_groups_numeric_prompt_suffixes_by_default(self):
        row = {
            "flavor_order": json.dumps(["direct", "direct_2", "natural"]),
            "direct_passed": 1,
            "direct_2_passed": 0,
            "natural_passed": 1,
        }

        assert plot_tool_call_eval_results.flavor_boundary_values(row, "score_passed", 2) == [
            ("direct", 1.0),
            ("natural", 1.0),
        ]

    def test_flavor_boundary_values_can_show_prompt_details(self):
        row = {
            "flavor_order": json.dumps(["direct", "direct_2", "natural"]),
            "direct_passed": 1,
            "direct_2_passed": 0,
            "natural_passed": 1,
        }

        assert plot_tool_call_eval_results.flavor_boundary_values(
            row,
            "score_passed",
            2,
            group_prompt_styles=False,
        ) == [
            ("direct", 1.0),
            ("direct_2", 0.0),
            ("natural", 1.0),
        ]

    def test_generate_plots_writes_cost_plot_when_cost_values_exist(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [
            {
                "model": "gpt-test",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.1,
            },
            {
                "model": "gpt-test-2",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.2,
            },
        ]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        plot_paths = run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert plot_paths == [
            tmp_path / "flux_tool_call_score.png",
            tmp_path / "flux_tool_call_tokens.png",
            tmp_path / "flux_tool_call_cost.png",
        ]
        assert [call["value_field"] for call in calls] == ["score_passed", "avg_total_tokens", "total_cost_usd"]
        assert calls[-1]["output_path"] == tmp_path / "flux_tool_call_cost.png"
        assert calls[-1]["title"] == "MCP Tool-Call Evaluation Cost By Model (Total: $0.300000)"
        assert calls[-1]["legend_title"] == "Test case"
        assert calls[-1]["show_legend_values"] is False
        assert calls[-1]["row_annotations"] == {}
        assert calls[0]["group_prompt_styles"] is True
        assert calls[1]["group_prompt_styles"] is True

    def test_generate_plots_can_request_prompt_details(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [{"model": "gpt-test", "case_id": "case-a", "score_passed": 1, "avg_total_tokens": 10}]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call", "plot_prompt_details": True}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert calls[0]["group_prompt_styles"] is False
        assert calls[1]["group_prompt_styles"] is False

    def test_generate_plots_marks_models_with_missing_pricing(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [
            {"model": "gpt-test", "case_id": "case-a", "score_passed": 1, "avg_total_tokens": 10, "total_cost_usd": ""},
            {"model": "gpt-test", "case_id": "case-b", "score_passed": 1, "avg_total_tokens": 10, "total_cost_usd": ""},
            {
                "model": "gpt-test-2",
                "case_id": "case-a",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": 0.2,
            },
            {
                "model": "gpt-test-2",
                "case_id": "case-b",
                "score_passed": 1,
                "avg_total_tokens": 10,
                "total_cost_usd": "n/a",
            },
        ]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert calls[-1]["value_field"] == "total_cost_usd"
        assert calls[-1]["row_annotations"] == {
            "gpt-test": "Missing Pricing",
        }

    def test_generate_plots_skips_cost_plot_without_cost_values(self, tmp_path: Path, monkeypatch):
        summary_csv = tmp_path / "summary.csv"
        summary_csv.write_text("not used", encoding="utf-8")
        rows = [{"model": "gpt-test", "case_id": "case-a", "score_passed": 1, "avg_total_tokens": 10}]
        calls = []

        monkeypatch.setattr(run_tool_call_eval, "load_rows", lambda _path: rows)
        monkeypatch.setattr(
            run_tool_call_eval,
            "plot_stacked",
            lambda **kwargs: calls.append(kwargs),
        )

        plot_paths = run_tool_call_eval.generate_plots(
            {"output": {"prefix": "flux_tool_call"}},
            tmp_path,
            summary_csv,
            quiet=True,
        )

        assert plot_paths == [tmp_path / "flux_tool_call_score.png", tmp_path / "flux_tool_call_tokens.png"]
        assert [call["value_field"] for call in calls] == ["score_passed", "avg_total_tokens"]

    @pytest.mark.asyncio
    async def test_run_writes_report_after_eval_and_plots(self, tmp_path: Path, monkeypatch):
        config_path = tmp_path / "run.json"
        cases_path = tmp_path / "cases.json"
        models_file = tmp_path / "models.txt"
        cases_path.write_text("{}", encoding="utf-8")
        models_file.write_text("model-a\n", encoding="utf-8")
        config_path.write_text(
            json.dumps(
                {
                    "name": "flux",
                    "cases": "cases.json",
                    "models_file": "models.txt",
                    "output": {"directory": "results", "prefix": "flux_tool_call", "timestamped": False},
                }
            ),
            encoding="utf-8",
        )
        calls = []

        async def fake_run_evaluator(eval_args):
            eval_args.summary_csv.parent.mkdir(parents=True, exist_ok=True)
            eval_args.summary_csv.write_text("summary", encoding="utf-8")
            eval_args.results_json.write_text("[]", encoding="utf-8")
            return 1

        def fake_generate_plots(_config, output_dir, _summary_csv, _quiet):
            return [output_dir / "flux_tool_call_score.png", output_dir / "flux_tool_call_tokens.png"]

        def fake_write_run_report(**kwargs):
            calls.append(kwargs)
            kwargs["report_path"].write_text("# report\n", encoding="utf-8")

        monkeypatch.setattr(run_tool_call_eval, "run_evaluator", fake_run_evaluator)
        monkeypatch.setattr(run_tool_call_eval, "generate_plots", fake_generate_plots)
        monkeypatch.setattr(run_tool_call_eval, "write_run_report", fake_write_run_report)

        status = await run_tool_call_eval.run(cli_overrides(run_config=config_path))

        assert status == 1
        assert len(calls) == 1
        call = calls[0]
        assert call["cases_path"] == cases_path.resolve()
        assert call["run_config_path"] == config_path.resolve()
        assert call["report_path"] == tmp_path / "results" / "flux_tool_call_report.md"
        assert call["eval_status"] == 1
        assert call["plot_paths"] == [
            tmp_path / "results" / "flux_tool_call_score.png",
            tmp_path / "results" / "flux_tool_call_tokens.png",
        ]
        assert call["detailed_rows_path"] == tmp_path / "results" / "flux_tool_call_rows.json"


# merge_tool_call_eval_results


class TestMergeToolCallEvalResults:
    def test_normalize_base_row_accepts_legacy_rows_without_cost_fields(self, tmp_path: Path):
        row = {
            "model": "gpt-test",
            "server": "server",
            "case_id": "case",
            "prompt_id": "direct",
            "sample_index": "1",
            "passed": "true",
            "error_type": "",
            "error": "",
            "expected_tool": "submit_job",
            "actual_tool": "submit_job",
            "prompt_tokens": "100",
            "completion_tokens": "20",
            "total_tokens": "120",
            "latency_ms": "10",
        }

        normalized = merge_tool_call_eval_results.normalize_base_row(row, tmp_path / "rows.csv")

        assert normalized["sample_index"] == 1
        assert normalized["passed"] is True
        assert normalized["input_cost_usd"] is None
        assert normalized["output_cost_usd"] is None
        assert normalized["total_cost_usd"] is None

    def test_normalize_base_row_parses_cost_fields(self, tmp_path: Path):
        row = {
            "model": "gpt-test",
            "server": "server",
            "case_id": "case",
            "prompt_id": "direct",
            "sample_index": "1",
            "passed": "true",
            "error_type": "",
            "error": "",
            "expected_tool": "submit_job",
            "actual_tool": "submit_job",
            "prompt_tokens": "100",
            "completion_tokens": "20",
            "total_tokens": "120",
            "input_token_price_usd": "0.001",
            "output_token_price_usd": "0.002",
            "input_cost_usd": "0.1",
            "output_cost_usd": "0.04",
            "total_cost_usd": "0.14",
            "latency_ms": "10",
        }

        normalized = merge_tool_call_eval_results.normalize_base_row(row, tmp_path / "rows.csv")

        assert normalized["input_token_price_usd"] == 0.001
        assert normalized["output_token_price_usd"] == 0.002
        assert normalized["input_cost_usd"] == 0.1
        assert normalized["output_cost_usd"] == 0.04
        assert normalized["total_cost_usd"] == 0.14


# gen_benchmark_fixture


class TestGenBenchmarkFixture:
    def test_build_generation_settings_prefers_cli_over_fixture_config(self):
        fixture = {
            "prompt_generation": {
                "model": "fixture-model",
                "num_prompts": 2,
                "styles": [
                    {"id": "natural", "description": "Natural request"},
                    {"id": "terse", "description": "Terse request"},
                ],
                "prompt_source": "existing",
                "augment_prompts": True,
                "augment_source": "existing",
            }
        }
        args = argparse.Namespace(
            model="cli-model",
            num_prompts=4,
            styles=["terse"],
            prompt_source="generated",
            augment_prompts=False,
            augment_source="generated",
            temperature=0.2,
            request_timeout=30.0,
        )

        settings = gen_benchmark_fixture.build_generation_settings(fixture, {}, args)

        assert settings.model == "cli-model"
        assert settings.num_prompts == 4
        assert [style.id for style in settings.styles] == ["terse"]
        assert settings.temperature == 0.2
        assert settings.request_timeout == 30.0
        assert settings.prompt_source == "generated"
        assert settings.augment_prompts is False
        assert settings.augment_source == "generated"

    def test_prompt_slots_generates_requested_count_per_style(self):
        styles = [
            gen_benchmark_fixture.GenerationStyle("natural", "Natural request"),
            gen_benchmark_fixture.GenerationStyle("terse", "Terse request"),
        ]

        slots = gen_benchmark_fixture.prompt_slots(styles, 3)

        assert [(slot.id, slot.style.id) for slot in slots] == [
            ("natural", "natural"),
            ("terse", "terse"),
            ("natural_2", "natural"),
            ("terse_2", "terse"),
            ("natural_3", "natural"),
            ("terse_3", "terse"),
        ]

    def test_parse_server_py_tools_extracts_docstrings_signatures_and_defaults(self, tmp_path: Path):
        server_py = tmp_path / "server.py"
        server_py.write_text(
            '''
class ExampleServer:
    def _register_tools(self):
        @self.mcp.tool()
        def submit_command(command: str, nodes: int = 1, exclusive: bool = False) -> str:
            """
            Submit one ad hoc command.

            Args:
                command: Command to run.
                nodes: Number of nodes to request.
                exclusive: Whether to request exclusive nodes.

            Returns:
                Result JSON.
            """
            return "{}"
''',
            encoding="utf-8",
        )

        tools = gen_benchmark_fixture.parse_server_py_tools(server_py, "example")

        assert len(tools) == 1
        function = tools[0]["function"]
        assert function["name"] == "submit_command"
        assert "[example] Submit one ad hoc command." in function["description"]
        parameters = function["parameters"]
        assert parameters["required"] == ["command"]
        assert parameters["properties"]["command"]["type"] == "string"
        assert parameters["properties"]["command"]["description"] == "Command to run."
        assert parameters["properties"]["nodes"]["type"] == "integer"
        assert parameters["properties"]["nodes"]["default"] == 1
        assert parameters["properties"]["exclusive"]["type"] == "boolean"
        assert parameters["properties"]["exclusive"]["default"] is False

    def test_build_generation_settings_parses_argument_policies(self):
        fixture = {
            "prompt_generation": {
                "model": "fixture-model",
                "argument_policies": [
                    {
                        "server": "flux",
                        "tool": "submit_command",
                        "arguments": {
                            "command": {
                                "mode": "verbatim",
                                "guidance": "Keep command exact.",
                            },
                            "nodes": {
                                "mode": "semantic",
                                "guidance": "Describe the node count clearly.",
                            },
                        },
                        "guidance": ["Keep command exact."],
                    }
                ],
            }
        }
        args = argparse.Namespace(
            model=None,
            num_prompts=None,
            styles=None,
            prompt_source=None,
            augment_prompts=None,
            augment_source=None,
            temperature=None,
            request_timeout=None,
        )

        settings = gen_benchmark_fixture.build_generation_settings(fixture, {}, args)

        assert settings.argument_policies == [
            gen_benchmark_fixture.PromptArgumentPolicy(
                server="flux",
                tool="submit_command",
                test_id=None,
                arguments={
                    "command": gen_benchmark_fixture.PromptArgumentRule(
                        mode="verbatim",
                        guidance=("Keep command exact.",),
                    ),
                    "nodes": gen_benchmark_fixture.PromptArgumentRule(
                        mode="semantic",
                        guidance=("Describe the node count clearly.",),
                    ),
                },
                guidance=("Keep command exact.",),
            )
        ]

    def test_build_generation_settings_requires_policy_server_and_tool(self):
        args = argparse.Namespace(
            model=None,
            num_prompts=None,
            styles=None,
            prompt_source=None,
            augment_prompts=None,
            augment_source=None,
            temperature=None,
            request_timeout=None,
        )

        with pytest.raises(ValueError, match=r"argument_policies\[1\]\.server"):
            gen_benchmark_fixture.build_generation_settings(
                {"prompt_generation": {"model": "model", "argument_policies": [{"tool": "submit_command"}]}},
                {},
                args,
            )

        with pytest.raises(ValueError, match=r"argument_policies\[1\]\.tool"):
            gen_benchmark_fixture.build_generation_settings(
                {"prompt_generation": {"model": "model", "argument_policies": [{"server": "flux"}]}},
                {},
                args,
            )

    def test_prompt_argument_policy_for_case_merges_matching_policies(self):
        test_case = {
            "id": "submit_command_full_options",
            "server": "flux",
            "expected_call": {
                "tool": "submit_command",
                "arguments": {
                    "command": "python simulate.py --case fluid_test --steps 10",
                    "nodes": 2,
                    "tasks": 8,
                    "time_limit": "30m",
                    "job_name": "fluid_test_eval",
                    "working_directory": "/tmp/mada_flux_eval/fluid_test_job",
                },
                "match": {"mode": "subset"},
            },
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model="model",
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="generated",
            augment_prompts=False,
            augment_source="both",
            argument_policies=[
                gen_benchmark_fixture.PromptArgumentPolicy(
                    server="flux",
                    tool="submit_command",
                    test_id=None,
                    arguments={
                        "working_directory": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Keep paths exact.",),
                        ),
                        "nodes": gen_benchmark_fixture.PromptArgumentRule(
                            mode="semantic",
                            guidance=("Describe node count clearly.",),
                        ),
                    },
                    guidance=("Flux guidance.",),
                ),
                gen_benchmark_fixture.PromptArgumentPolicy(
                    server="flux",
                    tool="submit_command",
                    test_id=None,
                    arguments={
                        "command": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Keep command exact.",),
                        ),
                        "working_directory": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Keep paths exact.",),
                        ),
                    },
                    guidance=("Command guidance.",),
                ),
                gen_benchmark_fixture.PromptArgumentPolicy(
                    server="slurm",
                    tool="submit_command",
                    test_id=None,
                    arguments={
                        "job_name": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Slurm guidance.",),
                        )
                    },
                    guidance=("Slurm guidance.",),
                ),
            ],
        )

        policy = gen_benchmark_fixture.prompt_argument_policy_for_case(settings, test_case)

        assert policy.verbatim_arguments == ("working_directory", "command")
        assert policy.argument_guidance == {
            "working_directory": ("Keep paths exact.",),
            "nodes": ("Describe node count clearly.",),
            "command": ("Keep command exact.",),
        }
        assert policy.guidance == ("Flux guidance.", "Command guidance.")

    def test_prompt_argument_policy_for_case_skips_absent_argument_guidance(self):
        test_case = {
            "id": "submit_jobs_generated_runs_default_sbatch",
            "server": "slurm",
            "expected_call": {
                "tool": "submit_jobs",
                "arguments": {
                    "run_info_json": "{\"runs\":[]}",
                },
                "match": {"mode": "subset"},
            },
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model="model",
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="generated",
            augment_prompts=False,
            augment_source="both",
            argument_policies=[
                gen_benchmark_fixture.PromptArgumentPolicy(
                    server="slurm",
                    tool="submit_jobs",
                    test_id=None,
                    arguments={
                        "run_info_json": gen_benchmark_fixture.PromptArgumentRule(
                            mode="semantic",
                            guidance=("Describe run_info_json manifest fields clearly.",),
                        ),
                        "account": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Keep account exact.",),
                        ),
                        "partition": gen_benchmark_fixture.PromptArgumentRule(
                            mode="verbatim",
                            guidance=("Keep partition exact.",),
                        ),
                    },
                    guidance=(),
                )
            ],
        )

        policy = gen_benchmark_fixture.prompt_argument_policy_for_case(settings, test_case)

        assert policy.verbatim_arguments == ()
        assert policy.argument_guidance == {
            "run_info_json": ("Describe run_info_json manifest fields clearly.",)
        }

    def test_generation_user_prompt_uses_configured_argument_policy(self):
        test_case = {
            "id": "submit_command_full_options",
            "server": "flux",
            "expected_call": {
                "tool": "submit_command",
                "arguments": {
                    "command": "python simulate.py --case fluid_test --steps 10",
                    "nodes": 2,
                    "tasks": 8,
                    "time_limit": "30m",
                    "job_name": "fluid_test_eval",
                    "working_directory": "/tmp/mada_flux_eval/fluid_test_job",
                },
                "match": {"mode": "subset"},
            },
        }
        slots = [
            gen_benchmark_fixture.PromptSlot(
                id="natural",
                style=gen_benchmark_fixture.GenerationStyle("natural", "Natural request"),
            )
        ]
        argument_policy = gen_benchmark_fixture.MatchedPromptArgumentPolicy(
            verbatim_arguments=("command", "working_directory"),
            argument_guidance={
                "command": ("Keep the command exact.",),
                "nodes": ("Describe node count clearly.",),
            },
            guidance=("Keep Flux command values exact.",),
        )

        prompt = gen_benchmark_fixture.generation_user_prompt(test_case, [], slots, argument_policy)

        assert "verbatim_string_arguments" in prompt
        assert "argument_guidance" in prompt
        assert "generation_guidance" in prompt
        assert "python simulate.py --case fluid_test --steps 10" in prompt
        assert "/tmp/mada_flux_eval/fluid_test_job" in prompt
        assert "Keep Flux command values exact." in prompt
        assert "Describe node count clearly." in prompt
        assert "naturally imply the expected MCP server, tool, and arguments" in prompt
        assert "Every prompt must preserve the exact value" in prompt

    def test_generation_user_prompt_without_policy_has_no_flux_specific_guidance(self):
        test_case = {
            "id": "semantic_string_case",
            "server": "example",
            "expected_call": {
                "tool": "search",
                "arguments": {"query": "fluid simulation"},
                "match": {"mode": "subset"},
            },
        }
        slots = [
            gen_benchmark_fixture.PromptSlot(
                id="natural",
                style=gen_benchmark_fixture.GenerationStyle("natural", "Natural request"),
            )
        ]

        prompt = gen_benchmark_fixture.generation_user_prompt(test_case, [], slots)

        assert '"verbatim_string_arguments": []' in prompt
        assert '"argument_guidance": {}' in prompt
        assert '"generation_guidance": []' in prompt
        assert "Every prompt must preserve the exact value" not in prompt
        assert "Scheduler/resource arguments" not in prompt
        assert "Do not substitute a program name" not in prompt
        assert "naturally imply the expected MCP server, tool, and arguments" in prompt

    def test_validate_generated_prompt_argument_coverage_ignores_unconfigured_string_arguments(self):
        prompts = [
            {
                "id": "natural",
                "text": (
                    "Can you run the fluid_test simulation for 10 steps with the usual eval setup? "
                    "Use the job name fluid_test_eval and the working directory under "
                    "/tmp/mada_flux_eval/fluid_test_job."
                ),
            }
        ]
        expected_call = {
            "tool": "submit_command",
            "arguments": {
                "command": "python simulate.py --case fluid_test --steps 10",
                "job_name": "fluid_test_eval",
                "working_directory": "/tmp/mada_flux_eval/fluid_test_job",
            },
        }

        gen_benchmark_fixture.validate_generated_prompt_argument_coverage(prompts, expected_call)

    def test_validate_generated_prompt_argument_coverage_rejects_configured_missing_exact_command(self):
        prompts = [
            {
                "id": "natural",
                "text": (
                    "Can you run the fluid_test simulation for 10 steps with the usual eval setup? "
                    "Use the job name fluid_test_eval and the working directory under "
                    "/tmp/mada_flux_eval/fluid_test_job."
                ),
            }
        ]
        expected_call = {
            "tool": "submit_command",
            "arguments": {
                "command": "python simulate.py --case fluid_test --steps 10",
                "job_name": "fluid_test_eval",
                "working_directory": "/tmp/mada_flux_eval/fluid_test_job",
            },
        }

        with pytest.raises(ValueError, match="natural missing exact string argument\\(s\\): command"):
            gen_benchmark_fixture.validate_generated_prompt_argument_coverage(prompts, expected_call, ("command",))

    def test_validate_generated_prompt_argument_coverage_accepts_configured_exact_string_arguments(self):
        prompts = [
            {
                "id": "natural",
                "text": (
                    "Use Flux submit_command to run `python simulate.py --case fluid_test --steps 10` "
                    "from /tmp/mada_flux_eval/fluid_test_job as job fluid_test_eval."
                ),
            }
        ]
        expected_call = {
            "tool": "submit_command",
            "arguments": {
                "command": "python simulate.py --case fluid_test --steps 10",
                "job_name": "fluid_test_eval",
                "working_directory": "/tmp/mada_flux_eval/fluid_test_job",
            },
        }

        gen_benchmark_fixture.validate_generated_prompt_argument_coverage(
            prompts,
            expected_call,
            ("command", "job_name", "working_directory"),
        )

    def test_verbatim_string_arguments_star_selects_all_string_arguments(self):
        expected_call = {
            "tool": "submit_command",
            "arguments": {
                "command": "python -V",
                "nodes": 1,
                "job_name": "python_version",
                "working_directory": "/tmp/mada_flux_eval/single_command",
            },
        }

        arguments = gen_benchmark_fixture.verbatim_string_arguments(expected_call, ("*",))

        assert arguments == [
            {"name": "command", "value": "python -V"},
            {"name": "job_name", "value": "python_version"},
            {"name": "working_directory", "value": "/tmp/mada_flux_eval/single_command"},
        ]

    def test_validate_generated_prompts_rejects_unexpected_ids(self):
        payload = {"prompts": [{"id": "natural", "text": "Run python -V."}]}

        with pytest.raises(ValueError, match="do not match expected ids"):
            gen_benchmark_fixture.validate_generated_prompts(payload, ["natural", "terse"])

    def test_validate_generated_prompts_orders_by_expected_ids(self):
        payload = {
            "prompts": [
                {"id": "terse", "text": "Flux submit status."},
                {"id": "natural", "text": "Please check the Flux job status."},
            ]
        }

        prompts = gen_benchmark_fixture.validate_generated_prompts(payload, ["natural", "terse"])

        assert prompts == [
            {"id": "natural", "text": "Please check the Flux job status."},
            {"id": "terse", "text": "Flux submit status."},
        ]

    def test_validate_generated_prompts_normalizes_prompt_text(self):
        payload = {
            "prompts": [
                {"id": "natural", "text": "Don\u2019t use smart quotes."},
                {"id": "terse", "text": "Don\\u2019t use smart quotes."},
            ]
        }

        prompts = gen_benchmark_fixture.validate_generated_prompts(payload, ["natural", "terse"])

        assert prompts == [
            {"id": "natural", "text": "Don't use smart quotes."},
            {"id": "terse", "text": "Don't use smart quotes."},
        ]

    def test_normalize_existing_prompts_normalizes_objects_and_strings(self):
        test_case = {
            "id": "case",
            "prompts": [
                {"id": "natural", "text": "Don\u2019t use an em dash\u2014here."},
                "Use\\u00a0plain\\u2019text.",
            ],
        }

        prompts = gen_benchmark_fixture.normalize_existing_prompts(test_case)

        assert prompts == [
            {"id": "natural", "text": "Don't use an em dash-here."},
            {"id": "prompt_2", "text": "Use plain'text."},
        ]

    @pytest.mark.asyncio
    async def test_generate_slot_prompts_retries_duplicate_prompt_ids(self):
        class Message:
            def __init__(self, content: str):
                self.content = content

        class Choice:
            def __init__(self, content: str):
                self.message = Message(content)

        class Response:
            def __init__(self, content: str):
                self.choices = [Choice(content)]

        class Completions:
            def __init__(self):
                self.calls = 0

            async def create(self, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return Response(
                        json.dumps(
                            {
                                "prompts": [
                                    {"id": "direct_2", "text": "Duplicate A"},
                                    {"id": "direct_2", "text": "Duplicate B"},
                                ]
                            }
                        )
                    )
                return Response(
                    json.dumps(
                        {
                            "prompts": [
                                {"id": "direct", "text": "Use Flux to check all jobs."},
                                {"id": "direct_2", "text": "Call Flux check_job_status for all tracked jobs."},
                            ]
                        }
                    )
                )

        class Chat:
            def __init__(self):
                self.completions = Completions()

        class Client:
            def __init__(self):
                self.chat = Chat()

        client = Client()
        settings = gen_benchmark_fixture.GenerationSettings(
            model="model",
            num_prompts=2,
            styles=[gen_benchmark_fixture.GenerationStyle("direct", "Direct request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="generated",
            augment_prompts=False,
            augment_source="both",
        )
        slots = gen_benchmark_fixture.prompt_slots_for_style(settings.styles[0], settings.num_prompts)
        test_case = {
            "id": "case",
            "server": "flux",
            "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
        }

        prompts = await gen_benchmark_fixture.generate_slot_prompts(client, settings, test_case, [], slots)

        assert client.chat.completions.calls == 2
        assert prompts == [
            {"id": "direct", "text": "Use Flux to check all jobs."},
            {"id": "direct_2", "text": "Call Flux check_job_status for all tracked jobs."},
        ]

    @pytest.mark.asyncio
    async def test_generate_fixture_sets_prompts_without_mutating_input(self, monkeypatch):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model="model",
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="generated",
            augment_prompts=False,
            augment_source="both",
        )

        async def fake_generate_case_prompts(_client, _settings, _test_case, _tools):
            return [{"id": "natural", "text": "Show all Flux jobs."}]

        monkeypatch.setattr(gen_benchmark_fixture, "generate_case_prompts", fake_generate_case_prompts)

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            {"flux": [{"type": "function", "function": {"name": "check_job_status"}}]},
            client=object(),
            settings=settings,
            quiet=True,
        )

        assert "prompts" not in fixture["tests"][0]
        assert output["tests"][0]["prompts"] == [{"id": "natural", "text": "Show all Flux jobs."}]

    @pytest.mark.asyncio
    async def test_generate_fixture_existing_source_preserves_existing_prompts_without_client(self):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Show all Flux jobs."}],
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model=None,
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="existing",
            augment_prompts=False,
            augment_source="both",
        )

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            tools_by_server=None,
            client=None,
            settings=settings,
            quiet=True,
        )

        assert output["tests"][0]["prompts"] == [{"id": "direct", "text": "Show all Flux jobs."}]

    @pytest.mark.asyncio
    async def test_generate_fixture_both_sources_prefixes_conflicting_generated_ids(self, monkeypatch):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "prompts": [{"id": "natural", "text": "Existing prompt."}],
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model="model",
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="both",
            augment_prompts=False,
            augment_source="both",
        )

        async def fake_generate_case_prompts(_client, _settings, _test_case, _tools):
            return [{"id": "natural", "text": "Generated prompt."}]

        monkeypatch.setattr(gen_benchmark_fixture, "generate_case_prompts", fake_generate_case_prompts)

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            {"flux": [{"type": "function", "function": {"name": "check_job_status"}}]},
            client=object(),
            settings=settings,
            quiet=True,
        )

        assert output["tests"][0]["prompts"] == [
            {"id": "natural", "text": "Existing prompt."},
            {"id": "generated_natural", "text": "Generated prompt."},
        ]

    @pytest.mark.asyncio
    async def test_generate_fixture_augment_prompts_calls_noop_hook(self, monkeypatch):
        calls = []
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Show all Flux jobs."}],
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model=None,
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="existing",
            augment_prompts=True,
            augment_source="existing",
        )

        def fake_augment_prompt_text(prompt_text, *, prompt_id, test_case, source, settings):
            calls.append((prompt_text, prompt_id, test_case["id"], source, settings.prompt_source))
            return prompt_text

        monkeypatch.setattr(gen_benchmark_fixture, "augment_prompt_text", fake_augment_prompt_text)

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            tools_by_server=None,
            client=None,
            settings=settings,
            quiet=True,
        )

        assert output["tests"][0]["prompts"] == [{"id": "direct", "text": "Show all Flux jobs."}]
        assert calls == [("Show all Flux jobs.", "direct", "case", "existing", "existing")]

    @pytest.mark.asyncio
    async def test_generate_fixture_normalizes_augmented_prompt_output(self, monkeypatch):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Show all Flux jobs."}],
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model=None,
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="existing",
            augment_prompts=True,
            augment_source="existing",
        )

        def fake_augment_prompt_text(prompt_text, *, prompt_id, test_case, source, settings):
            return f"{prompt_text} Don\u2019t use smart punctuation."

        monkeypatch.setattr(gen_benchmark_fixture, "augment_prompt_text", fake_augment_prompt_text)

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            tools_by_server=None,
            client=None,
            settings=settings,
            quiet=True,
        )

        assert output["tests"][0]["prompts"] == [
            {"id": "direct", "text": "Show all Flux jobs. Don't use smart punctuation."}
        ]

    @pytest.mark.asyncio
    async def test_generate_fixture_does_not_normalize_expected_call_arguments(self):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Don\u2019t touch expected_call."}],
                    "expected_call": {
                        "tool": "check_job_status",
                        "arguments": {"command": "Don\u2019t normalize this."},
                        "match": {"mode": "subset"},
                    },
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model=None,
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="existing",
            augment_prompts=False,
            augment_source="both",
        )

        output = await gen_benchmark_fixture.generate_fixture(
            fixture,
            tools_by_server=None,
            client=None,
            settings=settings,
            quiet=True,
        )

        assert output["tests"][0]["prompts"] == [{"id": "direct", "text": "Don't touch expected_call."}]
        assert output["tests"][0]["expected_call"]["arguments"] == {"command": "Don\u2019t normalize this."}

    @pytest.mark.asyncio
    async def test_generate_fixture_existing_source_requires_existing_prompts(self):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case",
                    "server": "flux",
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }
        settings = gen_benchmark_fixture.GenerationSettings(
            model=None,
            num_prompts=1,
            styles=[gen_benchmark_fixture.GenerationStyle("natural", "Natural request")],
            temperature=None,
            request_timeout=120.0,
            prompt_source="existing",
            augment_prompts=False,
            augment_source="both",
        )

        with pytest.raises(ValueError, match="must contain prompts"):
            await gen_benchmark_fixture.generate_fixture(
                fixture,
                tools_by_server=None,
                client=None,
                settings=settings,
                quiet=True,
            )


# gen_benchmark_report


class TestGenBenchmarkReport:
    def test_default_output_path_uses_markdown_suffix(self):
        assert gen_benchmark_report.default_output_path(Path("benchmark/cases.json")) == Path(
            "benchmark/cases.md"
        )

    def test_render_report_groups_single_server_prompts_by_flavor(self):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case_one",
                    "server": "flux",
                    "prompts": [
                        {"id": "direct", "text": "Call the tool directly."},
                        {"id": "direct_2", "text": "Call it another direct way."},
                        {"id": "natural", "text": "Please call the tool."},
                    ],
                    "expected_call": {
                        "tool": "check_job_status",
                        "arguments": {"job_id": "job_000123"},
                        "match": {"mode": "subset"},
                    },
                }
            ],
        }

        report = gen_benchmark_report.render_report(fixture, Path("flux_tool_call_eval_cases.json"))

        assert report.startswith("# flux_tool_call_eval_cases\n")
        assert "## MCP Server: flux" in report
        assert "### Test: case_one" in report
        assert "- Expected tool: `check_job_status`" in report
        assert '"job_id": "job_000123"' in report
        assert report.count("##### Prompt Flavor: direct") == 1
        assert "- **direct**: Call the tool directly." in report
        assert "- **direct\\_2**: Call it another direct way." in report
        assert "##### Prompt Flavor: natural" in report

    def test_render_report_splits_multiple_servers_into_chapters(self):
        fixture = {
            "mcp_servers": {
                "flux": {"url": "http://localhost:8101/mcp"},
                "slurm": {"url": "http://localhost:8102/mcp"},
            },
            "tests": [
                {
                    "id": "flux_case",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Flux prompt."}],
                    "expected_call": {"tool": "flux_tool", "arguments": {}, "match": {"mode": "subset"}},
                },
                {
                    "id": "slurm_case",
                    "server": "slurm",
                    "prompts": [{"id": "direct", "text": "Slurm prompt."}],
                    "expected_call": {"tool": "slurm_tool", "arguments": {}, "match": {"mode": "subset"}},
                },
            ],
        }

        report = gen_benchmark_report.render_report(fixture, Path("mixed_cases.json"))

        flux_chapter = report.index("## MCP Server: flux")
        slurm_chapter = report.index("## MCP Server: slurm")
        assert flux_chapter < slurm_chapter
        assert "### Test: flux_case" in report[flux_chapter:slurm_chapter]
        assert "### Test: slurm_case" not in report[flux_chapter:slurm_chapter]
        assert "### Test: slurm_case" in report[slurm_chapter:]

    def test_render_report_accepts_plain_string_prompts(self):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case_one",
                    "server": "flux",
                    "prompts": ["Plain prompt."],
                    "expected_call": {"tool": "check_job_status", "arguments": {}, "match": {"mode": "subset"}},
                }
            ],
        }

        report = gen_benchmark_report.render_report(fixture, Path("string_prompt_cases.json"))

        assert "##### Prompt Flavor: prompt" in report
        assert "- **prompt\\_1**: Plain prompt." in report

    def test_run_writes_markdown_report(self, tmp_path: Path):
        cases_path = tmp_path / "small_cases.json"
        output_path = tmp_path / "small_report.md"
        cases_path.write_text(
            json.dumps(
                {
                    "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
                    "tests": [
                        {
                            "id": "case_one",
                            "server": "flux",
                            "prompts": [{"id": "direct", "text": "Prompt."}],
                            "expected_call": {
                                "tool": "check_job_status",
                                "arguments": {},
                                "match": {"mode": "subset"},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        args = argparse.Namespace(cases=cases_path, output=output_path)

        assert gen_benchmark_report.run(args) == 0

        assert output_path.read_text(encoding="utf-8").startswith("# small_cases\n")

    def test_run_can_generate_benchmark_run_report_from_output_dir(self, tmp_path: Path):
        cases_path = tmp_path / "small_cases.json"
        output_dir = tmp_path / "results"
        output_dir.mkdir()
        cases_path.write_text(
            json.dumps(
                {
                    "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
                    "tests": [
                        {
                            "id": "case_one",
                            "server": "flux",
                            "prompts": [
                                {"id": "direct", "text": "Prompt."},
                                {"id": "natural", "text": "Unused prompt."},
                            ],
                            "expected_call": {
                                "tool": "check_job_status",
                                "arguments": {"job_id": "job_000123"},
                                "match": {"mode": "subset"},
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "flux_tool_call_score.png").write_bytes(b"png")
        (output_dir / "flux_tool_call_rows.json").write_text(
            json.dumps(
                [
                    {
                        "model": "gpt-test",
                        "server": "flux",
                        "case_id": "case_one",
                        "prompt_id": "direct",
                        "sample_index": 1,
                        "passed": False,
                        "error_type": "wrong_tool",
                        "error": "Expected tool check_job_status, got submit_command",
                        "expected_tool": "check_job_status",
                        "actual_tool": "submit_command",
                        "expected_call": {
                            "tool": "check_job_status",
                            "arguments": {"job_id": "job_000123"},
                            "match": {"mode": "subset"},
                        },
                        "actual_arguments": {"command": "status"},
                        "prompt": "Prompt.",
                    }
                ]
            ),
            encoding="utf-8",
        )
        args = argparse.Namespace(
            cases=cases_path,
            output=None,
            run_output=output_dir,
            rows_json=None,
            plots=None,
            run_config=None,
            eval_status=None,
        )

        assert gen_benchmark_report.run(args) == 0

        report = (output_dir / "flux_tool_call_report.md").read_text(encoding="utf-8")
        assert report.startswith("# Benchmark Run Report: results\n")
        assert "![Flux Tool Call Score](flux_tool_call_score.png)" in report
        assert "- Models: gpt-test" in report
        assert "- Prompt:" in report
        assert "Prompt." in report
        assert "##### Prompt Flavor: direct" in report
        assert "Unused prompt." not in report

    def test_render_run_report_includes_plots_and_common_failures(self, tmp_path: Path):
        fixture = {
            "mcp_servers": {"flux": {"url": "http://localhost:8101/mcp"}},
            "tests": [
                {
                    "id": "case_one",
                    "server": "flux",
                    "prompts": [{"id": "direct", "text": "Prompt."}],
                    "expected_call": {
                        "tool": "check_job_status",
                        "arguments": {"job_id": "job_000123"},
                        "match": {"mode": "subset"},
                    },
                }
            ],
        }
        eval_args = argparse.Namespace(
            models=["gpt-test"],
            cases=tmp_path / "cases.json",
            num_samples=2,
            max_concurrency=1,
            shard_index=0,
            shard_count=1,
            strict=False,
            prompt_ids=None,
            prompt_styles=None,
            exclude_prompt_ids=None,
            exclude_prompt_styles=None,
        )
        detailed_rows = [
            {
                "model": "gpt-test",
                "server": "flux",
                "case_id": "case_one",
                "prompt_id": "direct",
                "sample_index": 1,
                "passed": False,
                "error_type": "wrong_tool",
                "error": "Expected tool check_job_status, got submit_command",
                "expected_tool": "check_job_status",
                "actual_tool": "submit_command",
                "expected_call": fixture["tests"][0]["expected_call"],
                "actual_arguments": {"command": "status"},
            },
            {
                "model": "gpt-test",
                "server": "flux",
                "case_id": "case_one",
                "prompt_id": "direct",
                "sample_index": 2,
                "passed": False,
                "error_type": "wrong_tool",
                "error": "Expected tool check_job_status, got submit_command",
                "expected_tool": "check_job_status",
                "actual_tool": "submit_command",
                "expected_call": fixture["tests"][0]["expected_call"],
                "actual_arguments": {"command": "status"},
            },
        ]

        report = gen_benchmark_report.render_run_report(
            fixture=fixture,
            cases_path=tmp_path / "cases.json",
            run_config_path=tmp_path / "run.json",
            run_config={"name": "flux"},
            eval_args=eval_args,
            output_dir=tmp_path / "results",
            report_path=tmp_path / "results" / "flux_tool_call_report.md",
            eval_status=1,
            plot_paths=[tmp_path / "results" / "flux_tool_call_score.png"],
            detailed_rows=detailed_rows,
        )

        assert "# Benchmark Run Report: results" in report
        assert "![Flux Tool Call Score](flux_tool_call_score.png)" in report
        assert "### gpt-test / flux / case_one / direct" in report
        assert "- Passed: 0/2" in report
        assert "- Prompt:" in report
        assert "Prompt." in report
        assert "2x `wrong_tool`: got `submit_command`" in report
        assert "Expected tool check_job_status, got submit_command" in report
        assert "Returned arguments:" in report
        assert '{"command": "status"}' in report
        assert "## Benchmark Fixture: cases" in report


# tool_call_eval_fixtures


class TestToolCallEvalFixtures:
    @pytest.mark.parametrize(
        "fixture_name",
        [
            "flux_tool_call_eval_cases.json",
            "slurm_tool_call_eval_cases.json",
        ],
    )
    def test_tool_call_eval_fixture_schema(self, fixture_name: str):
        fixture = mcp_tool_call_eval.load_json(BENCHMARK_DIR / fixture_name)

        assert fixture["mcp_servers"]
        assert fixture["tests"]
