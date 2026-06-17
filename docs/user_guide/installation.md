# Installing MADA Tools

In this page you'll find [Basic Installation](#basic-installation) instructions (most users should just look at this section) and instructions for [Installing Optional Dependencies](#installing-optional-dependencies) which will likely only be needed by developers.

## Basic Installation

Here are the steps required to install the MADA MCP Servers project:

1. First, clone the repository:

    === "ssh"

        ```bash
        git clone git@github.com:llnl/mada-tools.git
        ```

    === "https"

        ```csh
        git clone https://github.com/llnl/mada-tools.git
        ```

2. Next, move into the cloned repository:

    ```bash
    cd mada-tools/
    ```

3. Create a python virtual environment:

    ```bash
    python -m venv mada_venv
    ```

    **Note:** If you've already installed [MADA](https://software.llnl.gov/mada) into a virtual environment, install MADA Tools in the same virtual environment.

4. Activate the environment:

    === "bash"

        ```bash
        source mada_venv/bin/activate
        ```

    === "csh"

        ```csh
        source mada_venv/bin/activate.csh
        ```

5. From the top level of the repository, run:

    ```bash
    pip install -e .
    ```

Congratulations, the MADA Tools project is now installed!

You may also want to configure environment variables related to your API key and endpoint:

```bash
export API_KEY="your-api-key-here"
export API_BASE_URL="https://api.openai.com/v1/responses"
```

## Installing Optional Dependencies

There are four sets of optional dependencies that can be installed:

- Documentation
- Examples
- Flux
- Tests

These can be installed together:

=== "Shorthand"

    ```bash
    pip install -e ".[all]"
    ```

=== "Verbose"

    ```bash
    pip install -e .[tests,docs,examples,flux]
    ```

Or separately:

=== "Install Test Dependencies"

    ```bash
    pip install -e .[tests]
    ```

=== "Install Documentation Dependencies"

    ```bash
    pip install -e .[docs]
    ```

=== "Install Example Dependencies"

    ```bash
    pip install -e .[examples]
    ```

=== "Install Flux Dependencies"

    ```bash
    pip install -e .[flux]
    ```
