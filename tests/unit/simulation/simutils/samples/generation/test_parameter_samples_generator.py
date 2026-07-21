"""
Unit tests for shared structured parameter sample generation.
"""

import pytest

from mada_tools.simulation.simutils.samples.generation.parameter_samples_generator import (
    ParameterSampleGenerator,
    create_sampling_rngs,
    normalize_cli_value,
)


def collect_values(result, parameter_name: str) -> list:
    return [row[parameter_name] for row in result.row_values]


def create_def_exe_cli_generator() -> ParameterSampleGenerator:
    return ParameterSampleGenerator(
        allowed_types={"def", "exe", "cli"},
        continuous_allowed_types={"def"},
        max_exe_parameters=1,
        validate_cli_values=True,
    )


def test_continuous_lhs_generates_requested_sample_count():
    result = ParameterSampleGenerator().generate(
        parameters={"emult": ["def", "continuous", [0.75, 1.5]]},
        num_samples=3,
        seed=12345,
    )

    assert result.parameter_names == ["emult"]
    assert len(result.samples) == 3
    assert len(result.row_values) == 3
    assert all(0.75 <= row["emult"] <= 1.5 for row in result.row_values)
    assert result.sampling_metadata["rng_bit_generator"] == "MT19937"


def test_discrete_parameters_generate_cartesian_product():
    result = ParameterSampleGenerator().generate(
        parameters={
            "material": ["def", "discrete", ["Aluminum", "Steel"]],
            "plate_loc": ["def", "discrete", [5.0, 10.0]],
        },
        seed=12345,
    )

    assert result.parameter_names == ["material", "plate_loc"]
    assert result.row_values == [
        {"material": "Aluminum", "plate_loc": 5.0},
        {"material": "Aluminum", "plate_loc": 10.0},
        {"material": "Steel", "plate_loc": 5.0},
        {"material": "Steel", "plate_loc": 10.0},
    ]
    assert result.samples == [["Aluminum", 5.0], ["Aluminum", 10.0], ["Steel", 5.0], ["Steel", 10.0]]


def test_json_string_list_values_are_accepted():
    result = ParameterSampleGenerator().generate(
        parameters={
            "material": ["def", "discrete", '["Aluminum", "Steel"]'],
            "plate_loc": ["def", "discrete", "[5.0, 10.0]"],
        },
        seed=12345,
    )

    assert result.row_values == [
        {"material": "Aluminum", "plate_loc": 5.0},
        {"material": "Aluminum", "plate_loc": 10.0},
        {"material": "Steel", "plate_loc": 5.0},
        {"material": "Steel", "plate_loc": 10.0},
    ]


def test_json_string_non_list_values_are_rejected():
    with pytest.raises(ValueError, match="values must be a non-empty list"):
        ParameterSampleGenerator().generate(
            parameters={"material": ["def", "discrete", '"Aluminum"']},
            seed=12345,
        )


def test_generic_generator_allows_custom_parameter_types():
    result = ParameterSampleGenerator().generate(
        parameters={"mach": ["solver_input", "continuous", [1.0, 2.0]]},
        num_samples=2,
        seed=12345,
    )

    assert result.parameter_names == ["mach"]
    assert all(1.0 <= row["mach"] <= 2.0 for row in result.row_values)


def test_discrete_lhs_selects_values_reproducibly():
    parameters = {"plate_loc": ["def", "discrete_lhs", [5.0, 7.5, 10.0, 15.0]]}

    first = ParameterSampleGenerator().generate(parameters=parameters, num_samples=4, seed=12345)
    second = ParameterSampleGenerator().generate(parameters=parameters, num_samples=4, seed=12345)

    assert collect_values(first, "plate_loc") == collect_values(second, "plate_loc")
    assert len(first.row_values) == 4


def test_discrete_random_selects_subset_reproducibly():
    parameters = {"plate_thick": ["def", "discrete_random", [1.0, 1.5, 2.0, 3.0], 2]}

    first = ParameterSampleGenerator().generate(parameters=parameters, seed=12345)
    second = ParameterSampleGenerator().generate(parameters=parameters, seed=12345)

    assert collect_values(first, "plate_thick") == collect_values(second, "plate_thick")
    assert len(first.row_values) == 2


def test_zip_pairs_values_by_group_identifier():
    result = ParameterSampleGenerator().generate(
        parameters={
            "material": ["def", "zip", ["Aluminum", "Steel"], "material_group"],
            "plate_loc": ["def", "zip", [5.0, 10.0], "material_group"],
            "source": ["def", "zip", ["src1", "src2"], 0],
        },
        seed=12345,
    )

    assert result.row_values == [
        {"material": "Aluminum", "plate_loc": 5.0, "source": "src1"},
        {"material": "Aluminum", "plate_loc": 5.0, "source": "src2"},
        {"material": "Steel", "plate_loc": 10.0, "source": "src1"},
        {"material": "Steel", "plate_loc": 10.0, "source": "src2"},
    ]


def test_mixed_zip_group_identifiers_use_first_seen_group_order():
    result = ParameterSampleGenerator().generate(
        parameters={
            "right": ["def", "zip", ["r1", "r2"], "right_group"],
            "left": ["def", "zip", ["l1", "l2"], 0],
        },
        seed=12345,
    )

    assert result.row_values == [
        {"right": "r1", "left": "l1"},
        {"right": "r1", "left": "l2"},
        {"right": "r2", "left": "l1"},
        {"right": "r2", "left": "l2"},
    ]


def test_rejects_omitted_zip_group():
    with pytest.raises(ValueError, match="zip requires a fourth param_zip_group_id"):
        ParameterSampleGenerator().generate(
            parameters={
                "material": ["def", "zip", ["Aluminum", "Steel"]],
                "plate_loc": ["def", "zip", [5.0, 10.0], 1],
            },
            seed=12345,
        )


def test_rejects_mismatched_zip_lengths_within_group():
    with pytest.raises(ValueError, match="group 1"):
        ParameterSampleGenerator().generate(
            parameters={
                "material": ["def", "zip", ["Aluminum", "Steel"], 1],
                "plate_loc": ["def", "zip", [5.0], 1],
            },
            seed=12345,
        )


@pytest.mark.parametrize("zip_group", [-1, True, "", 1.5, None, [], {}])
def test_rejects_invalid_zip_group(zip_group):
    with pytest.raises(ValueError, match="param_zip_group_id"):
        ParameterSampleGenerator().generate(
            parameters={"material": ["def", "zip", ["Aluminum"], zip_group]},
            seed=12345,
        )


def test_cli_values_are_normalized():
    assert normalize_cli_value("cli_args", "-dm last -v") == ["-dm", "last", "-v"]
    assert normalize_cli_value("cli_args", ["-dm", "last"]) == ["-dm", "last"]


def test_rejects_invalid_cli_values():
    with pytest.raises(ValueError, match="cli argv lists"):
        normalize_cli_value("cli_args", ["-dm", 1])

    with pytest.raises(TypeError, match="cli values"):
        normalize_cli_value("cli_args", 1)


def test_rejects_continuous_cli_and_exe_parameters():
    with pytest.raises(ValueError, match="does not support continuous"):
        create_def_exe_cli_generator().generate(
            parameters={"cli_args": ["cli", "continuous", [1.0, 2.0]]},
            num_samples=2,
            seed=12345,
        )

    with pytest.raises(ValueError, match="does not support continuous"):
        create_def_exe_cli_generator().generate(
            parameters={"executable": ["exe", "continuous", [1.0, 2.0]]},
            num_samples=2,
            seed=12345,
        )


def test_rejects_multiple_executable_parameters():
    with pytest.raises(ValueError, match="At most 1 exe parameter"):
        create_def_exe_cli_generator().generate(
            parameters={
                "executable_a": ["exe", "discrete", ["a"]],
                "executable_b": ["exe", "discrete", ["b"]],
            },
            seed=12345,
        )


def test_rejects_executable_parameters_above_configured_maximum():
    generator = ParameterSampleGenerator(
        allowed_types={"def", "exe", "cli"},
        max_exe_parameters=2,
    )

    with pytest.raises(ValueError, match="At most 2 exe parameter"):
        generator.generate(
            parameters={
                "executable_a": ["exe", "discrete", ["a"]],
                "executable_b": ["exe", "discrete", ["b"]],
                "executable_c": ["exe", "discrete", ["c"]],
            },
            seed=12345,
        )


@pytest.mark.parametrize("seed", [-1, True])
def test_create_sampling_rngs_rejects_invalid_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        create_sampling_rngs(seed=seed, rng_bit_generator=None)


def test_create_sampling_rngs_rejects_invalid_bit_generator():
    with pytest.raises(ValueError, match="rng_bit_generator"):
        create_sampling_rngs(seed=12345, rng_bit_generator="Threefry")


def test_create_sampling_rngs_normalizes_supported_bit_generator():
    _, metadata = create_sampling_rngs(seed=12345, rng_bit_generator="philox")

    assert metadata == {
        "seed": 12345,
        "requested_seed": 12345,
        "seed_source": "user",
        "rng_bit_generator": "PHILOX",
    }
