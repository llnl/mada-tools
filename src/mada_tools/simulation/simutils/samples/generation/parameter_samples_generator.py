"""
Shared parameter sample generation utilities for simulation servers.
"""

import itertools
import json
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast

import numpy as np

from mada_tools.simulation.simutils.samples.generation.lhs_sample_generator import LHSampleGenerator


@dataclass(frozen=True)
class ParameterSpec:
    """
    Validated parameter generation specification.

    `parameter_type` is server-defined, while `selection` is one of the shared
    sampling modes handled by ParameterSampleGenerator. These fields correspond
    to the prompt-facing `param_type` and `param_selection` tuple positions.
    `num_selections` stores the prompt-facing `param_num_selections` value for
    discrete_random parameters, and `zip_group` stores `param_zip_group_id` for
    zip parameters.
    """

    name: str
    parameter_type: str
    selection: str
    values: List[Any]
    num_selections: Optional[int] = None
    zip_group: Optional[int | str] = None


@dataclass(frozen=True)
class ParameterSampleResult:
    """
    Generated parameter samples and reproducibility metadata.

    `parameter_names` defines the column order for `samples`. `row_values`
    contains the same data as one dictionary per generated run and is usually
    the easiest representation for server helpers to translate into command
    lines, deck edits, input files, or run manifests. `specs` contains the
    validated parameter schema used to generate the rows.
    """

    parameter_names: List[str]
    samples: List[List[Any]]
    row_values: List[Dict[str, Any]]
    specs: List[ParameterSpec]
    sampling_metadata: Dict[str, Any]


def create_sampling_rngs(
    seed: Optional[int] = None,
    rng_bit_generator: Optional[str] = "MT19937",
) -> tuple[Dict[str, np.random.Generator], Dict[str, Any]]:
    """
    Create independent RNG streams and metadata for parameter sampling.

    The returned streams are keyed by sampling mode: `lhs`, `discrete_lhs`, and
    `discrete_random`. They are derived from jumped versions of one root bit
    generator so each mode is reproducible without sharing mutable RNG state.

    `seed` must be None or a non-negative integer. When `seed` is None, NumPy
    initializes from system entropy and the effective entropy value is recorded
    in the metadata. `rng_bit_generator` may be MT19937, PCG64, PCG64DXSM, or
    PHILOX. If omitted, MT19937 is used.
    """
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
        raise ValueError("seed must be a non-negative integer or null")

    normalized_bit_generator = str(rng_bit_generator or "MT19937").upper()

    bit_generator_classes = {
        "MT19937": np.random.MT19937,
        "PCG64": np.random.PCG64,
        "PCG64DXSM": np.random.PCG64DXSM,
        "PHILOX": np.random.Philox,
    }
    bit_generator_class = bit_generator_classes.get(normalized_bit_generator)
    if bit_generator_class is None:
        raise ValueError("rng_bit_generator must be one of: MT19937, PCG64, PCG64DXSM, PHILOX")

    seed_sequence = np.random.SeedSequence(seed)
    effective_seed = int(cast(int, seed_sequence.entropy))
    root_bit_generator = bit_generator_class(seed_sequence)
    rng_streams = {
        "lhs": np.random.Generator(root_bit_generator.jumped(1)),
        "discrete_lhs": np.random.Generator(root_bit_generator.jumped(2)),
        "discrete_random": np.random.Generator(root_bit_generator.jumped(3)),
    }
    return rng_streams, {
        "seed": effective_seed,
        "requested_seed": seed,
        "seed_source": "user" if seed is not None else "system_entropy",
        "rng_bit_generator": normalized_bit_generator,
    }


class ParameterSampleGenerator:
    """
    Build concrete parameter rows from mixed parameter specifications.

    The generator is intentionally simulation-agnostic. It validates the shared
    sampling schema and returns row dictionaries; server helpers remain
    responsible for translating row values into command-line arguments, deck
    edits, input files, environment variables, or run metadata.

    `allowed_types` restricts server-specific parameter types. For example, a
    deck-based server might allow `def`, `cli`, and `exe`, while another server
    might allow `input`, `flag`, and `executable`.

    `continuous_allowed_types` restricts which parameter types may use
    continuous sampling. This is useful when only numeric simulation variables,
    and not executable or CLI selectors, should accept numeric bounds.

    `max_exe_parameters` limits parameters of type exactly `exe`.
    `validate_cli_values` validates values for parameters of type exactly `cli`
    with normalize_cli_value during schema parsing.
    """

    def __init__(
        self,
        allowed_types: Optional[set[str]] = None,
        continuous_allowed_types: Optional[set[str]] = None,
        max_exe_parameters: Optional[int] = None,
        validate_cli_values: bool = False,
    ):
        self.allowed_types = allowed_types
        self.continuous_allowed_types = continuous_allowed_types
        self.max_exe_parameters = max_exe_parameters
        self.validate_cli_values = validate_cli_values

    def generate(
        self,
        parameters: Dict[str, List[Any]],
        num_samples: Optional[int] = None,
        seed: Optional[int] = None,
        rng_bit_generator: Optional[str] = None,
    ) -> ParameterSampleResult:
        """
        Validate parameter specifications and generate all run rows.

        Continuous and discrete_lhs parameters produce `num_samples` LHS rows.
        Discrete and discrete_random parameters produce Cartesian grid rows. Zip
        parameters pair values by index within each zip group, and independent
        zip groups are combined as separate dimensions.

        The final run matrix is:

            grid rows * zip rows * LHS rows

        The returned ParameterSampleResult contains ordered sample rows,
        per-run dictionaries, validated specs, and reproducibility metadata.
        """
        rng_streams, sampling_metadata = create_sampling_rngs(seed, rng_bit_generator)
        parameter_specs = self.parse_parameter_specs(parameters)

        lhs_rows = self._generate_lhs_rows(parameter_specs, num_samples, rng_streams)
        grid_rows = self._generate_grid_rows(parameter_specs, rng_streams)
        zip_rows = self._generate_zip_rows(parameter_specs)

        parameter_names = [spec.name for spec in parameter_specs]
        samples = []
        row_values = []
        for grid_row in grid_rows:
            for zip_row in zip_rows:
                for lhs_row in lhs_rows:
                    run_values = {}
                    run_values.update(grid_row)
                    run_values.update(zip_row)
                    run_values.update(lhs_row)
                    row_values.append(run_values)
                    samples.append([run_values.get(name) for name in parameter_names])

        return ParameterSampleResult(
            parameter_names=parameter_names,
            samples=samples,
            row_values=row_values,
            specs=parameter_specs,
            sampling_metadata=sampling_metadata,
        )

    def parse_parameter_specs(self, parameters: Dict[str, List[Any]]) -> List[ParameterSpec]:
        """
        Validate and normalize structured parameter specifications.

        Each non-random, non-zip entry in `parameters` must use this list form:

            [param_type, param_selection, param_values]

        `discrete_random` and `zip` entries require a fourth value:

            [param_type, "discrete_random", param_values, param_num_selections]
            [param_type, "zip", param_values, param_zip_group_id]

        Parameter names must be non-empty strings. Parameter type and selection
        names are normalized to lowercase. `param_values` must normalize to a
        non-empty list. JSON-encoded list strings are accepted as a compatibility
        fallback, but callers should prefer passing native lists.

        Supported selections are `continuous`, `discrete`, `discrete_lhs`,
        `discrete_random`, and `zip`. Unsupported selections, invalid bounds,
        invalid random counts, unsupported parameter types, and mismatched zip
        groups raise built-in Python exceptions.
        """
        if not parameters:
            raise ValueError("parameters must contain at least one parameter")

        allowed_selections = {"continuous", "discrete", "discrete_lhs", "discrete_random", "zip"}
        unsupported_modes = {"discrete_random_zip"}
        specs = []
        exe_parameter_names = []

        for name, parameter_spec in parameters.items():
            if not isinstance(name, str) or not name:
                raise ValueError("parameter names must be non-empty strings")
            if not isinstance(parameter_spec, list) or len(parameter_spec) not in {3, 4}:
                raise ValueError(
                    f"parameters['{name}'] must be [param_type, param_selection, param_values],"
                    "[param_type, 'discrete_random', param_values, param_num_selections],"
                    "or [param_type, 'zip', param_values, param_zip_group_id]"
                )

            parameter_type = str(parameter_spec[0]).lower()
            selection = str(parameter_spec[1]).lower()
            values = normalize_values_list(name, parameter_spec[2])
            fourth_value = parameter_spec[3] if len(parameter_spec) == 4 else None
            num_selections = None
            zip_group = None

            if self.allowed_types is not None and parameter_type not in self.allowed_types:
                raise ValueError(f"parameters['{name}'] has unsupported parameter type: {parameter_spec[0]}")
            if selection in unsupported_modes or selection not in allowed_selections:
                raise ValueError(f"parameters['{name}'] has unsupported parameter selection: {parameter_spec[1]}")
            if (
                self.continuous_allowed_types is not None
                and selection == "continuous"
                and parameter_type not in self.continuous_allowed_types
            ):
                raise ValueError(f"parameters['{name}'] type '{parameter_type}' does not support continuous selection")
            if parameter_type == "exe" and self.max_exe_parameters is not None:
                exe_parameter_names.append(name)
                if not all(isinstance(value, str) and value for value in values):
                    raise ValueError(f"parameters['{name}'] exe values must be non-empty strings")
            if parameter_type == "cli" and self.validate_cli_values:
                for value in values:
                    normalize_cli_value(name, value)

            if selection == "continuous":
                if len(values) != 2 or not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool) for value in values
                ):
                    raise ValueError(f"parameters['{name}'] continuous values must be exactly two numeric bounds")
            if selection == "discrete_random":
                num_selections = fourth_value
                if not isinstance(num_selections, int) or isinstance(num_selections, bool):
                    raise TypeError(f"parameters['{name}'] discrete_random requires an integer param_num_selections")
                if num_selections <= 0:
                    raise ValueError(f"parameters['{name}'] discrete_random param_num_selections must be positive")
                if num_selections > len(values):
                    raise ValueError(
                        f"parameters['{name}'] discrete_random param_num_selections cannot exceed param_values count"
                    )
            if selection == "zip":
                if len(parameter_spec) != 4:
                    raise ValueError(f"parameters['{name}'] zip requires a fourth param_zip_group_id")
                zip_group = fourth_value
                valid_int_group = isinstance(zip_group, int) and not isinstance(zip_group, bool) and zip_group >= 0
                valid_string_group = isinstance(zip_group, str) and zip_group != ""
                if not valid_int_group and not valid_string_group:
                    raise ValueError(
                        f"parameters['{name}'] param_zip_group_id must be a non-negative integer or non-empty string"
                    )

            specs.append(
                ParameterSpec(
                    name=name,
                    parameter_type=parameter_type,
                    selection=selection,
                    values=values,
                    num_selections=num_selections,
                    zip_group=zip_group,
                )
            )

        if self.max_exe_parameters is not None and len(exe_parameter_names) > self.max_exe_parameters:
            raise ValueError(
                f"At most {self.max_exe_parameters} exe parameter(s) are supported. "
                f"Found {len(exe_parameter_names)}: {exe_parameter_names}"
            )

        return specs

    def _generate_lhs_rows(
        self,
        parameter_specs: List[ParameterSpec],
        num_samples: int,
        rng_streams: Dict[str, np.random.Generator],
    ) -> List[Dict[str, Any]]:
        continuous_specs = [spec for spec in parameter_specs if spec.selection == "continuous"]
        discrete_lhs_specs = [spec for spec in parameter_specs if spec.selection == "discrete_lhs"]

        if not continuous_specs and not discrete_lhs_specs:
            return [{}]
        if num_samples is None:
            raise ValueError("num_samples must be provided when using continuous or discrete_lhs parameters")
        if not isinstance(num_samples, int) or isinstance(num_samples, bool) or num_samples <= 0:
            raise ValueError("num_samples must be a positive integer")

        lhs_rows: List[Dict[str, Any]] = [{} for _ in range(num_samples)]
        if continuous_specs:
            sample_settings: Dict[str, Any] = {
                "dims": len(continuous_specs),
                "n_samples": num_samples,
                "lower_bounds": [float(spec.values[0]) for spec in continuous_specs],
                "upper_bounds": [float(spec.values[1]) for spec in continuous_specs],
                "rng": rng_streams["lhs"],
            }

            sample_generator = LHSampleGenerator()
            continuous_samples = sample_generator.generate(**sample_settings).tolist()
            for row, continuous_sample in zip(lhs_rows, continuous_samples):
                for spec, value in zip(continuous_specs, continuous_sample):
                    row[spec.name] = value

        for spec in discrete_lhs_specs:
            for row in lhs_rows:
                value_index = int(rng_streams["discrete_lhs"].integers(len(spec.values)))
                row[spec.name] = spec.values[value_index]

        return lhs_rows

    def _generate_grid_rows(
        self,
        parameter_specs: List[ParameterSpec],
        rng_streams: Dict[str, np.random.Generator],
    ) -> List[Dict[str, Any]]:
        grid_specs = [spec for spec in parameter_specs if spec.selection in {"discrete", "discrete_random"}]
        if not grid_specs:
            return [{}]

        value_lists = []
        for spec in grid_specs:
            if spec.selection == "discrete_random":
                if spec.num_selections is None:
                    raise RuntimeError(f"parameters['{spec.name}'] discrete_random requires param_num_selections")
                value_indices = rng_streams["discrete_random"].choice(
                    len(spec.values),
                    size=spec.num_selections,
                    replace=False,
                )
                values = [spec.values[int(index)] for index in value_indices]
            else:
                values = spec.values
            value_lists.append([(spec.name, value) for value in values])

        return [dict(values) for values in itertools.product(*value_lists)]

    def _generate_zip_rows(self, parameter_specs: List[ParameterSpec]) -> List[Dict[str, Any]]:
        zip_specs = [spec for spec in parameter_specs if spec.selection == "zip"]
        if not zip_specs:
            return [{}]

        grouped_specs: Dict[int | str, List[ParameterSpec]] = {}
        for spec in zip_specs:
            if spec.zip_group is None:
                raise RuntimeError(f"parameters['{spec.name}'] zip requires a zip group")
            grouped_specs.setdefault(spec.zip_group, []).append(spec)

        grouped_rows = []
        for zip_group, group_specs in grouped_specs.items():
            value_counts = {len(spec.values) for spec in group_specs}
            if len(value_counts) != 1:
                raise ValueError(f"All zip parameter value lists in group {zip_group} must have the same length")

            grouped_rows.append(
                [{spec.name: spec.values[index] for spec in group_specs} for index in range(next(iter(value_counts)))]
            )

        rows = []
        for row_parts in itertools.product(*grouped_rows):
            row = {}
            for row_part in row_parts:
                row.update(row_part)
            rows.append(row)
        return rows


def normalize_values_list(parameter_name: str, values: Any) -> List[Any]:
    """
    Normalize a parameter `values` field to a non-empty list.

    Most callers should pass native JSON/Python lists. JSON-encoded list strings
    are accepted as a compatibility fallback for LLM-generated tool calls that
    double-encode the list value, such as "[1, 2, 3]". Non-list strings and
    empty lists are rejected.
    """
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            pass

    if not isinstance(values, list) or not values:
        raise ValueError(f"parameters['{parameter_name}'] param_values must be a non-empty list")
    return values


def normalize_cli_value(parameter_name: str, value: Any) -> List[str]:
    """
    Normalize a CLI parameter value into argv tokens.

    A non-empty string is split with shlex.split so quoted groups are preserved.
    A non-empty list of non-empty strings is treated as an explicit argv token
    list. Shell expansion is not performed; variables, globs, redirects, pipes,
    and command substitutions remain ordinary argv text after splitting.
    """
    if isinstance(value, str):
        if not value:
            raise ValueError(f"parameters['{parameter_name}'] cli values must be non-empty strings or lists of strings")
        try:
            cli_args = shlex.split(value)
        except ValueError as exc:
            raise ValueError(f"parameters['{parameter_name}'] cli value could not be parsed: {exc}") from exc
        if not cli_args:
            raise ValueError(f"parameters['{parameter_name}'] cli values must produce at least one argv token")
        return cli_args

    if isinstance(value, list):
        if not value or not all(isinstance(arg, str) and arg for arg in value):
            raise ValueError(f"parameters['{parameter_name}'] cli argv lists must contain non-empty strings")
        return value

    raise TypeError(f"parameters['{parameter_name}'] cli values must be non-empty strings or lists of strings")
