# Installing MADA Tools

In this page you'll find [Basic Installation](#basic-installation) instructions (most users should just look at this section) and instructions for [Installing Optional Dependencies](#installing-optional-dependencies).

## Basic Installation

Here are the steps required to install the MADA Tools project:

1. Create a python virtual environment:

    ```bash
    python -m venv mada_venv
    ```

    **Note:** If you've already installed [MADA](https://software.llnl.gov/mada) into a virtual environment, install MADA Tools in the same virtual environment.

2. Activate the environment:

    === "bash"

        ```bash
        source mada_venv/bin/activate
        ```

    === "csh"

        ```csh
        source mada_venv/bin/activate.csh
        ```

3. From the top level of the repository, run:

    ```bash
    pip install mada-tools
    ```

Congratulations, the MADA Tools project is now installed!

You may also want to configure environment variables related to your API key and endpoint:

```bash
export API_KEY="your-api-key-here"
export API_BASE_URL="https://api.openai.com/v1/responses"
```

## Server discovery and optional capabilities

MADA discovers each core and plugin server independently. If an optional
server dependency is missing, that server is omitted and the other available
servers continue to appear in `mada-tools available-servers`.

Flux is optional and requires the `flux-python` package plus a usable Flux
system executable when the server is run. Install the Python support with:

```bash
pip install "mada_tools[flux]"
```

Server discovery does not start Flux or probe the scheduler executable. The
Flux server will report configuration or executable problems when it is
started or used.

## Installing Optional Dependencies

There are four sets of optional dependencies that can be installed:

- Documentation
- Examples
- Flux
- Tests

These can be installed together:

=== "Shorthand"

    ```bash
    pip install "mada_tools[all]"
    ```

=== "Verbose"

    ```bash
    pip install "mada_tools[tests,docs,examples,flux]"
    ```

Or separately:

=== "Install Test Dependencies"

    ```bash
    pip install "mada_tools[tests]"
    ```

=== "Install Documentation Dependencies"

    ```bash
    pip install "mada_tools[docs]"
    ```

=== "Install Example Dependencies"

    ```bash
    pip install "mada_tools[examples]"
    ```

=== "Install Flux Dependencies"

    ```bash
    pip install "mada_tools[flux]"
    ```
