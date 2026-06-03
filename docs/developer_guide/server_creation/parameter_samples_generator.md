# Using the Parameter Samples Generator

`ParameterSampleGenerator` provides shared parameter sampling for simulation MCP
servers. It handles parameter validation, sample generation, reproducible
random number generator metadata, and common selection modes. Each server
remains responsible for translating generated parameter rows into the
command-line arguments, input files, deck edits, or run metadata required by its
simulation code.

Use this utility when a simulation server needs to create multiple run
directories from sampled or enumerated parameter values.

## Import the Generator

```python
from mada_tools.simulation.simutils.samples.generation import (
    ParameterSampleGenerator,
    ParameterSampleResult,
    normalize_cli_value,
)
```

## Parameter Schema

Each entry in `parameters` uses one of these forms:

```python
"name": [parameter_type, selection, values]
"name": [parameter_type, selection, values, num_selections_or_zip_group]
```

The `parameter_type` is defined by the server. For example, one server might
use `input`, `flag`, and `executable`, while another might use `def`, `cli`,
and `exe`.

Parameter names must be non-empty strings. Each parameter specification must be
a list with three or four entries, and `values` must be a non-empty list.
Parameter types and selection names are normalized to lowercase before
validation.

Supported selections:

| Selection | Values | Behavior |
| --- | --- | --- |
| `continuous` | `[min, max]` | Latin Hypercube samples in the numeric range. Requires `num_samples`. |
| `discrete` | `[value, ...]` | Uses every listed value in a Cartesian product. |
| `discrete_lhs` | `[value, ...]` | Selects one listed value per LHS row. Requires `num_samples`. |
| `discrete_random` | `[value, ...]` plus `num_selections` | Selects a random subset without replacement. |
| `zip` | `[value, ...]` plus optional `zip_group` | Pairs values by index inside a zip group. |

Validation rules:

- `continuous` values must be exactly two numeric bounds.
- `continuous` and `discrete_lhs` require `num_samples` to be a positive
  integer.
- `discrete_random` requires a fourth value, `num_selections`, which must be a
  positive integer and must not exceed the number of listed values.
- `zip` can use a fourth value for the zip group. If omitted, the group
  defaults to `1`. Zip groups must be positive integers.
- All `zip` parameters in the same group must have value lists of the same
  length.
- `discrete_random_zip` is explicitly unsupported.

## Selection Semantics and Run Counts

The generator builds run rows from three independent parts:

- LHS rows from `continuous` and `discrete_lhs` parameters.
- Grid rows from `discrete` and `discrete_random` parameters.
- Zip rows from `zip` parameters.

For mixed studies, each grid row is combined with each zip row and each LHS row.
The effective run count is:

```text
grid combinations * zip combinations * lhs rows
```

For example, a study with `num_samples=3`, one `discrete` parameter with two
values, one `discrete_random` parameter selecting two values, and two zip
groups with lengths three and two produces:

```text
2 * 2 * (3 * 2) * 3 = 72 runs
```

`discrete_random` first chooses `num_selections` values without replacement from
the listed values. The selected values then become grid dimensions for the run
matrix. `zip` parameters in the same group are paired by index. Different zip
groups are combined as independent dimensions.

The generated row order is grid rows first, then zip rows, then LHS rows. Use
`sample_result.parameter_names` and `sample_result.samples` when writing
ordered tables, and use `sample_result.row_values` when translating each run
into server-specific runtime inputs.

## Configure the Generator

Configure the base generator for the parameter types your server accepts. This
example supports simulation input parameters, raw CLI flags, and one executable
selector:

```python
def _create_parameter_sample_generator(self) -> ParameterSampleGenerator:
    return ParameterSampleGenerator(
        allowed_types={"input", "flag", "executable"},
        continuous_allowed_types={"input"},
        max_exe_parameters=1,
        validate_cli_values=True,
    )
```

Constructor options:

| Option | Behavior |
| --- | --- |
| `allowed_types` | Optional set of accepted parameter types. If set, any other type is rejected. |
| `continuous_allowed_types` | Optional set of parameter types allowed to use `continuous` selection. |
| `max_exe_parameters` | Optional maximum count for parameters whose type is exactly `exe`. |
| `validate_cli_values` | If `True`, validate values for parameters whose type is exactly `cli`. |

Use `ParameterSampleGenerator()` without arguments when the server has no
special parameter type restrictions.

`max_exe_parameters` only applies to parameter type `exe`. When enabled, each
`exe` value must be a non-empty string, and the total number of `exe`
parameters must not exceed the configured maximum.

`validate_cli_values=True` only validates parameter type `cli` during parsing.
Servers using other CLI-like types, such as `gen_cli` or `run_cli`, should call
`normalize_cli_value` while translating rows into command arguments.

## Generate Samples

```python
sample_result = self._create_parameter_sample_generator().generate(
    parameters=parameters,
    num_samples=num_samples,
    seed=seed,
    rng_bit_generator=rng_bit_generator,
)
```

`sample_result` is a `ParameterSampleResult` with:

| Field | Meaning |
| --- | --- |
| `parameter_names` | Ordered parameter names for writing sample tables. |
| `samples` | Sample table rows matching `parameter_names`. |
| `row_values` | One dictionary per generated run, keyed by parameter name. |
| `specs` | Validated parameter specifications. |
| `sampling_metadata` | Effective seed, requested seed, seed source, and NumPy bit generator. |

Store `sampling_metadata` in each run manifest when reproducibility matters:

```python
run_data["sampling"] = sample_result.sampling_metadata
```

## Reproducible Sampling and RNGs

`seed` may be `None` or a non-negative integer. Boolean values are rejected even
though `bool` is an `int` subclass in Python.

The generator creates a NumPy `SeedSequence(seed)` and records
`SeedSequence.entropy` as the effective seed in `sampling_metadata["seed"]`.
When `seed` is provided, `seed_source` is `"user"` and `requested_seed` is the
provided value. When `seed` is omitted, NumPy initializes the seed sequence from
system entropy, `seed_source` is `"system_entropy"`, and `requested_seed` is
`None`.

Supported `rng_bit_generator` values are:

- `MT19937`
- `PCG64`
- `PCG64DXSM`
- `PHILOX`

If `rng_bit_generator` is omitted or `None`, the generator uses `MT19937`.
Provided bit generator names are normalized to uppercase. Invalid names raise
`ValueError`.

The generator creates independent NumPy `Generator` streams for:

- `lhs`: continuous Latin Hypercube sampling.
- `discrete_lhs`: random value selection for `discrete_lhs`.
- `discrete_random`: random subset selection for `discrete_random`.

Those streams are created from jumped versions of the same root bit generator,
so each sampling mode is reproducible without sharing one mutable RNG stream
across all random operations.

Server-specific environment fallbacks are not part of `ParameterSampleGenerator`.
If a server wants an environment variable such as `DECKSIM_BITGENERATOR` to set
the default bit generator, the server helper should read that variable and pass
the resulting value as `rng_bit_generator`.

Example reproducible call:

```python
sample_result = generator.generate(
    parameters={
        "scale": ["def", "continuous", [0.75, 1.5]],
        "location": ["def", "discrete_lhs", [5.0, 7.5, 10.0, 15.0]],
        "thickness": ["def", "discrete_random", [1.0, 1.5, 2.0, 3.0], 2],
    },
    num_samples=3,
    seed=12345,
    rng_bit_generator="PCG64DXSM",
)
```

Representative metadata for a seeded run:

```json
{
  "seed": 12345,
  "requested_seed": 12345,
  "seed_source": "user",
  "rng_bit_generator": "PCG64DXSM"
}
```

Representative metadata for an unseeded run:

```json
{
  "seed": 228051777428008974360608241931799117282,
  "requested_seed": null,
  "seed_source": "system_entropy",
  "rng_bit_generator": "MT19937"
}
```

To reproduce an unseeded study, rerun with the recorded `sampling.seed` and the
same `rng_bit_generator`.

## CLI Value Normalization

Use `normalize_cli_value(parameter_name, value)` when a parameter value should
be converted into argv tokens.

Accepted values:

- A non-empty string, split with `shlex.split`.
- A non-empty list of non-empty strings, used as explicit argv tokens.

String values use shell-like quote handling:

```python
normalize_cli_value("cli_args", '-name "case one" -flag')
# ["-name", "case one", "-flag"]
```

Shell expansion is not performed. Variables, globs, pipes, redirects, and
command substitutions are treated as argv text after splitting.

```python
normalize_cli_value("cli_args", "$RUN_DIR/*.dat | tee out.txt")
# ["$RUN_DIR/*.dat", "|", "tee", "out.txt"]
```

Invalid CLI values raise built-in Python exceptions:

- `ValueError` for empty strings, parse errors, empty lists, or lists containing
  empty or non-string entries.
- `TypeError` for values that are neither strings nor lists.

## Translate Samples to Simulation Syntax

Keep simulation-specific syntax in the server helper. The shared generator tells
you which values belong in each run; your server decides how those values become
argv tokens, deck edits, input files, or environment variables.

For an argv-style code that expects:

- executable chosen by `parameter_type == "executable"`
- input parameters as `--set name=value`
- raw flags or options from `parameter_type == "flag"`

the helper could implement:

```python
def _build_run_configurations(
    self,
    sample_result: ParameterSampleResult,
) -> list[dict[str, object]]:
    run_configurations = []

    for row_values in sample_result.row_values:
        executable = None
        args: list[str] = []

        for spec in sample_result.specs:
            value = row_values[spec.name]

            if spec.parameter_type == "input":
                args.extend(["--set", f"{spec.name}={value}"])
            elif spec.parameter_type == "flag":
                args.extend(normalize_cli_value(spec.name, value))
            elif spec.parameter_type == "executable":
                executable = value

        run_configurations.append(
            {
                "executable": executable,
                "args": args,
            }
        )

    return run_configurations
```

The server can then attach those configurations to run instances:

```python
for run_instance, run_configuration in zip(output_result.run_instances, run_configurations):
    run_instance.command = self._resolve_executable(run_configuration["executable"])
    run_instance.args = [
        "--input",
        self._stage_input_file(run_instance.run_location),
        *run_configuration["args"],
    ]

    run_data = run_instance.to_dict()
    run_data["sampling"] = sample_result.sampling_metadata
```

## Deck-Based Server Skeleton

This skeleton shows how to use the generator in a deck-based simulation server.
It uses generic `def`, `exe`, and `cli` parameter types:

- `def`: simulation variable passed as `-def name=value`.
- `exe`: optional executable selector.
- `cli`: additional argv tokens.

Deck staging and dependency copying are represented as placeholder helper
methods because they depend on the target simulation code's file layout.

```python
import json
import os
from typing import Any

import numpy as np

from mada_tools.simulation.simutils.samples.generation import (
    ParameterSampleGenerator,
    ParameterSampleResult,
    normalize_cli_value,
)
from mada_tools.simulation.simutils.samples.output.folder_output_handler import (
    FolderOutputHandler,
)


class DeckSimHelper:
    def generate_parameter_runs(
        self,
        parameters: dict[str, list[Any]],
        output_dir: str,
        num_samples: int | None = None,
        kernel_name: str = "decksim",
        input_deck_path: str | None = None,
        input_deck_entrypoint: str | None = None,
        dependency_paths: list[str] | None = None,
        seed: int | None = None,
        rng_bit_generator: str | None = None,
    ) -> tuple[bool, str]:
        configured_bit_generator = rng_bit_generator
        if configured_bit_generator is None:
            configured_bit_generator = os.environ.get("DECKSIM_BITGENERATOR")

        sample_result = self._create_parameter_sample_generator().generate(
            parameters=parameters,
            num_samples=num_samples,
            seed=seed,
            rng_bit_generator=configured_bit_generator,
        )
        run_configurations = self._build_run_configurations(sample_result)

        output_handler = FolderOutputHandler()
        samples_array = np.array(sample_result.samples, dtype=object)
        output_result = output_handler.write(
            samples_array,
            sample_result.parameter_names,
            output_dir=os.path.abspath(output_dir),
            param_file="parameter_samples.txt",
        )

        run_info = []
        for run_instance, run_configuration in zip(output_result.run_instances, run_configurations):
            staged_deck = self._stage_input_deck(
                input_deck_path=input_deck_path,
                input_deck_entrypoint=input_deck_entrypoint,
                dependency_paths=dependency_paths,
                run_location=run_instance.run_location,
            )

            run_instance.command = self._resolve_executable(run_configuration["executable"])
            run_instance.args = [
                "-i",
                staged_deck,
                "-k",
                kernel_name,
                *run_configuration["def_args"],
                *run_configuration["cli_args"],
            ]

            run_data = run_instance.to_dict()
            run_data["kernel_name"] = kernel_name
            run_data["staged_deck"] = staged_deck
            run_data["sampling"] = sample_result.sampling_metadata
            run_info.append(run_data)

        run_instances_json_path = os.path.join(output_dir, "run_instances.json")
        with open(run_instances_json_path, "w", encoding="utf-8") as json_file:
            json.dump(run_info, json_file, indent=2)

        return True, json.dumps(run_info, indent=2)

    def _create_parameter_sample_generator(self) -> ParameterSampleGenerator:
        return ParameterSampleGenerator(
            allowed_types={"def", "exe", "cli"},
            continuous_allowed_types={"def"},
            max_exe_parameters=1,
            validate_cli_values=True,
        )

    def _build_run_configurations(
        self,
        sample_result: ParameterSampleResult,
    ) -> list[dict[str, Any]]:
        run_configurations = []

        for row_values in sample_result.row_values:
            executable = None
            def_args: list[str] = []
            cli_args: list[str] = []

            for spec in sample_result.specs:
                value = row_values[spec.name]

                if spec.parameter_type == "def":
                    def_args.extend(["-def", f"{spec.name}={value}"])
                elif spec.parameter_type == "cli":
                    cli_args.extend(normalize_cli_value(spec.name, value))
                elif spec.parameter_type == "exe":
                    executable = value

            run_configurations.append(
                {
                    "executable": executable,
                    "def_args": def_args,
                    "cli_args": cli_args,
                }
            )

        return run_configurations

    def _resolve_executable(self, executable: str | None) -> str:
        default_executable = os.environ.get("DECKSIM_EXE_PATH")
        if executable is None:
            if default_executable is None:
                raise RuntimeError("DECKSIM_EXE_PATH must be set")
            return default_executable

        if os.path.basename(executable) == executable:
            if default_executable is None:
                raise RuntimeError("DECKSIM_EXE_PATH must be set for bare executable names")
            return os.path.join(os.path.dirname(default_executable), executable)

        return os.path.expanduser(executable)

    def _stage_input_deck(
        self,
        input_deck_path: str | None,
        input_deck_entrypoint: str | None,
        dependency_paths: list[str] | None,
        run_location: str,
    ) -> str:
        """Copy the deck entrypoint and dependencies into run_location."""
        raise NotImplementedError("Implement deck staging for this simulation code")
```

## File or Deck Based Codes

Some simulation codes do not pass sampled parameters as command-line arguments.
For example, a server may need to edit XML, write a Lua deck, copy dependency
files, or update a generated input file.

Use `sample_result.row_values` directly for those cases:

```python
for run_instance, row_values in zip(output_result.run_instances, sample_result.row_values):
    input_path = self._copy_template_input(run_instance.run_location)
    self._replace_parameters_in_file(input_path, row_values)

    run_instance.command = self._resolve_executable(None)
    run_instance.args = ["--input", input_path]
```

Do not put file mutation or deck staging behavior in `ParameterSampleGenerator`.
That logic belongs in the simulation server because it depends on the target
code's file format and runtime conventions.

## Recommended Tests

For each server using `ParameterSampleGenerator`, add tests for:

- generated run count for continuous, discrete, and zip inputs
- reproducibility with a fixed `seed`
- server-specific argv or file/deck translation
- invalid parameter schemas and unsupported parameter types
- invalid `seed` and `rng_bit_generator` values
- run metadata containing `sampling_metadata`
