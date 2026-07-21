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
from mada_tools.simulation.simutils import (
    ParameterSampleGenerator,
    ParameterSampleResult,
    normalize_cli_value,
)
```

## Parameter Schema

Each non-random, non-zip entry in `parameters` uses this form:

```python
"name": [param_type, param_selection, param_values]
"name": [param_type, "discrete_random", param_values, param_num_selections]
"name": [param_type, "zip", param_values, param_zip_group_id]
```

The `param_type` position is defined by the server. For example, one server might
use `input`, `flag`, and `executable`, while another might use `def`, `cli`,
and `exe`.

For MCP tool docstrings, be explicit that `param_type` is not a data type.
LLMs often invent labels such as `categorical`, `string`, `float`, `file`,
`fixed`, or `continuous` for this position unless the tool description says not
to. A deck-style server should usually say:

```text
The first item is the server parameter type, not a data type. Use "def" for
simulation variables, including numeric values, strings, file names, labels,
and case ids. Use "exe" only for executable selection and "cli" only for raw
command-line argv tokens.
```

Likewise, be explicit that `param_selection` is a fixed vocabulary. Do not
encourage or accept invented selection names such as `lhs`, `grid`, `range`,
`constant`, `continuous_lhs`, `values`, or `set` in documentation examples. Use
the exact selection strings listed below.

Parameter names must be non-empty strings. Each parameter specification must be
a list with three or four entries, and `param_values` must always be a JSON
list, even when there is one value.
Parameter types and selection names are normalized to lowercase before
validation.

Supported selections:

| Selection | Values | Behavior |
| --- | --- | --- |
| `continuous` | `[min, max]` | Latin Hypercube samples in the numeric range. Requires `num_samples`. |
| `discrete` | `[value, ...]` | Uses every listed value in a Cartesian product. |
| `discrete_lhs` | `[value, ...]` | Selects one listed value per LHS row. Requires `num_samples`. |
| `discrete_random` | `param_values` plus `param_num_selections` | Selects a random subset without replacement. |
| `zip` | `param_values` plus `param_zip_group_id` | Pairs values by index inside a zip group. |

Validation rules:

- `continuous` param_values must be exactly two numeric bounds.
- `continuous` and `discrete_lhs` require `num_samples` to be a positive
  integer.
- `discrete_random` requires a fourth value, `param_num_selections`, which must
  be a positive integer and must not exceed the number of listed param_values.
- `zip` requires a fourth value, `param_zip_group_id`, which must be a
  non-negative integer or non-empty string.
- All `zip` parameters in the same group must have value lists of the same
  length.
- `discrete_random_zip` is explicitly unsupported.

Canonical deck-style examples:

```json
{
  "density": ["def", "continuous", [1.0, 2.5]],
  "material": ["def", "discrete", ["steel", "aluminum"]],
  "mesh": ["def", "discrete_lhs", ["coarse", "medium", "fine"]],
  "checkpoint": ["def", "discrete_random", ["chk_a", "chk_b", "chk_c"], 2],
  "solver": ["exe", "discrete", ["skeleton_gpu"]],
  "diagnostics": ["cli", "discrete", [["--diagnostics", "on", "--verbose"]]],
  "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], 1],
  "source_scale": ["def", "zip", [1.0, 0.8], 1],
  "case_id": ["def", "discrete", ["debug_case"]]
}
```

Common invalid examples:

```json
{
  "density": ["continuous", "lhs", [1.0, 2.5]],
  "material": ["categorical", "grid", ["steel", "aluminum"]],
  "solver": ["fixed", "value", "skeleton_gpu"],
  "case_id": ["string", "constant", "debug_case"]
}
```

Use `["def", "continuous", [min, max]]` plus top-level `num_samples` for
continuous LHS. Use `["def", "discrete", [value1, value2]]` for grid sweeps.
Use `["exe", "discrete", ["solver_name"]]` for a fixed executable.
Use `discrete_lhs` only for explicit lists of choices, not numeric `[min, max]`
ranges. Zip group identifiers may be non-negative JSON integers or non-empty
strings. CLI values must include the full argv tokens, not just put the flag
name in the parameter key.

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

`discrete_random` first chooses `param_num_selections` values without replacement from
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
        """
        Generate DeckSim run directories from structured parameter specifications.

        Use this tool when the user asks to create a parameter sweep, sampling
        study, or set of simulation runs from one input deck.

        The `parameters` argument must be a JSON object. Each key is a parameter
        name. Each value must be one of:
          [param_type, param_selection, param_values]
          [param_type, "discrete_random", param_values, param_num_selections]
          [param_type, "zip", param_values, param_zip_group_id]

        The first item is the server parameter type, not a data type. It must be
        exactly one of "def", "cli", or "exe". Use "def" for all simulation
        variables, including numeric values, strings, file names, labels, and
        case ids. Do not use invented data-type labels such as "continuous",
        "categorical", "string", "float", "file", "fixed", "parameter", or
        "value" in the first position.

        The second item, param_selection, is the selection mode. It must be exactly one of
        "continuous", "discrete", "discrete_lhs", "discrete_random", or "zip".
        Do not use invented selection labels such as "lhs", "grid",
        "grid_values", "range", "uniform", "random", "constant",
        "continuous_lhs", "values", "set", or "list".

        Supported parameter types:
          - "def": simulation variable passed as "-def name=value"
          - "cli": raw command-line arguments appended to the executable
          - "exe": executable selector. At most one "exe" parameter is allowed.

        Supported selections:
          - "continuous": param_values must be [min, max]; requires num_samples.
            Use this for numeric LHS ranges.
          - "discrete": param_values are fully enumerated in a grid.
          - "discrete_lhs": one listed value is sampled per LHS row; requires
            num_samples. Use this only for explicit lists of choices, not
            numeric [min, max] ranges.
          - "discrete_random": param_num_selections is the number of listed
            param_values to select.
          - "zip": param_values are paired by index with other zip parameters
            in the same zip group. param_zip_group_id is required and must be a
            non-negative JSON integer or non-empty string.

        Common mistakes to avoid:
          - Do not use "continuous", "categorical", "string", "float", or
            "file" as parameter types. Use "def" unless the parameter is the
            executable ("exe") or raw command-line argv ("cli").
          - Do not split LHS into ["continuous", "lhs", param_values]. Correct
            continuous LHS parameters use ["def", "continuous", [min, max]]
            and set num_samples as a top-level argument.
          - Do not use "discrete_lhs" for numeric [min, max] ranges. Numeric
            ranges must use "continuous".
          - Do not use "grid" for grid sweeps. Correct grid parameters use
            ["def", "discrete", [value1, value2, ...]].
          - Fixed values still use "discrete" with a one-element values list,
            such as ["def", "discrete", ["debug_case"]].
          - The third item, param_values, must always be a list, including for
            zip and one fixed value. Incorrect: ["def", "zip", "src/a.deck", 1].
          - Zip group identifiers may be non-negative integers such as 0 or 1,
            or non-empty strings such as "source_group".
          - For cli parameters, values must include the full argv tokens. Do
            not put the flag only in the parameter key. Correct:
            "restart_args": ["cli", "discrete", [["-restart", "old.chk"]]].
            Incorrect: "-restart": ["cli", "discrete", ["old.chk"]].
          - Do not put bounds in separate lower_bounds or upper_bounds fields.
          - Do not use a JSON string for `parameters`; pass an object.
          - Do not omit num_samples when using "continuous" or "discrete_lhs".
          - Put executables and CLI options inside `parameters`, not in
            separate top-level fields.
          - For zip parameters, use the same zip group identifier for parameters
            that should be paired by index.
          - If the user gives /path/to/deck_dir/main.deck, pass
            input_deck_path="/path/to/deck_dir" and
            input_deck_entrypoint="main.deck".
          - If dependency paths are relative to input_deck_path, preserve them
            as relative strings in dependency_paths. Do not prefix
            input_deck_path.

        Canonical parameter examples:
          - Continuous numeric LHS variable:
            "density": ["def", "continuous", [1.0, 2.5]]
          - Discrete/grid variable:
            "material": ["def", "discrete", ["steel", "aluminum"]]
          - Discrete LHS variable:
            "mesh": ["def", "discrete_lhs", ["coarse", "medium", "fine"]]
          - Random subset:
            "checkpoint": ["def", "discrete_random", ["chk_a", "chk_b", "chk_c"], 2]
          - Executable:
            "solver": ["exe", "discrete", ["decksim_gpu"]]
          - Raw CLI argv:
            "diagnostics": ["cli", "discrete", [["--diagnostics", "on", "--verbose"]]]
          - Zip group:
            "source_file": ["def", "zip", ["src/a.deck", "src/b.deck"], "source_group"]

        Example:
          parameters={
            "temperature": ["def", "continuous", [300.0, 900.0]],
            "material": ["def", "discrete", ["steel", "aluminum"]],
            "solver": ["exe", "discrete", ["decksim_cpu"]],
          },
          num_samples=4
        """
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

        run_info: dict[str, list[dict[str, Any]]] = {"runs":[]}
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
            run_info["runs"].append(run_data)

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

### Example Prompts

The skeleton docstring should be paired with natural-language examples that
exercise the schema. These prompts are useful for manual testing, LLM tool-call
evaluation fixtures, and server-specific documentation:

```text
Create 8 DeckSim runs from /data/cases/blast with main.deck as the entrypoint.
Sample density from 1.0 to 2.5 and pressure from 10 to 50 using LHS. Use kernel
name blast_sweep and write the runs under ./runs/blast_lhs.

Generate a grid sweep for plate_thickness values 1.0, 1.5, and 2.0 and material
values steel and aluminum. Use deck ./inputs/plate/plate.deck and output to
./runs/plate_grid.

Create runs where source_file and source_scale are zipped together. Use
source_file values src/a.deck, src/b.deck, and src/c.deck with source_scale
values 1.0, 0.8, and 1.2. Also sample temperature continuously from 300 to 700
with 5 LHS samples.

Run one case with executable decksim_gpu, add raw CLI args "-restart old.chk
--verbose", copy dependencies Materials and Tables, and write output to
./runs/restart_case.

Generate 6 runs using PCG64DXSM and seed 12345. Sample temperature continuously
from 400 to 1200, choose one mesh from coarse, medium, and fine per LHS row, and
write the output to ./runs/reproducible.
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
