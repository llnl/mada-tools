# MADA Tools Testing Guide

This page is intended to help devs understand the test suite for the MADA Tools repository. It walks through:

- [Test Requirements](#test-requirements)
- [Creating Tests](#creating-tests)
- [Running Tests](#running-tests)

## Test Requirements

This test suite uses the [Pytest library](https://docs.pytest.org/en/stable/).

In order to install the test requirements:

```bash
pip install -e .[tests]
```

To add new test requirements, go to the `pyproject.toml` file at the top of the repo, find the `[project.optional-dependencies]` section, and add your dependencies to the `tests` list.

## Creating Tests

It's recommended that you reference [Pytest's Documentation](https://docs.pytest.org/en/stable/) for understanding what all this library can do. This section will walk through:

- [File System Organization](#file-system-organization)
- [Marking Tests](#marking-tests)
- [Fixture Architecture](#fixture-architecture)

### File System Organization

The test suite is organized by test type:

- end-to-end (e2e) tests
- integration tests
- unit tests

Each test type has their own directory in the test suite.

When creating unit tests, please follow the same directory structure as the `src/` directory. In other words, create a new folder in the appropriate location for each server that unit tests are being written for. For example, the code for the `ServerManager` class has its source files at `mada_tools/server_management/server_manager.py` and therefore its test files live at `unit/server_management/test_server_manager_unit.py`.

### Marking Tests

Depending on which test type (e2e, integration, etc.) you put a test file under, the test will be automatically marked with one of the following marks:

- `unit`: Marks tests as unit tests
- `integration`: Marks tests as integration tests
- `e2e`: Marks tests as end-to-end tests

If you create a test that requires an allocation, mark the test with `@pytest.mark.allocation_required`.

If you create a test that requires a specific environment variable, mark the test with `@pytest.mark.requires_env("MY_VAR")`.

You'll see how these marks are utilized in the [Running Tests](#running-tests) section.

### Fixture Architecture

Fixtures can be defined at different levels of a test suite by using `conftest.py` files, and they can also be defined directly inside individual test modules. Where you define a fixture determines how broadly it is available. In general, fixtures defined in a test module are only available in that module, while fixtures defined in a `conftest.py` file are available to tests in that directory and its subdirectories. Because fixture discovery is scoped this way, fixture names should still be chosen carefully to avoid confusion or unintended overriding.

## Running Tests

There are multiple ways to run the test suite, due to the [marks mentioned earlier](#marking-tests). Here is how the test suite can be ran:

- Run all tests not requiring an allocation:

    ```bash
    pytest tests/
    ```

- Run all unit tests not requiring an allocation:

    ```bash
    pytest -m unit tests/
    ```

- Run all integration tests not requiring an allocation:

    ```bash
    pytest -m integration tests/
    ```

- Run all end-to-end tests not requiring an allocation:

    ```bash
    pytest -m e2e tests/
    ```

For all of the commands given above, this will *not* automatically run tests that require an allocation. To include these tests, first get an allocation and then add `--include-allocation-required` as an argument to pytest. For example, to run all integration tests, including tests requiring an allocation, execute:

```bash
flux alloc -N 1 -q pdebug -t 60 pytest -m integration --include-allocation-required tests/
```

You can also choose to run *only* the tests that require an allocation using:

```bash
flux alloc -N 1 -q pdebug -t 60  pytest -m allocation_required --include-allocation-required tests/
```
