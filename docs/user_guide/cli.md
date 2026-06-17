# Command-Line Interface (CLI)

The MADA Tools library defines a number of commands to help manage your MCP servers.

This module will detail every command available with MADA Tools.

## MADA-Tools

The entrypoint to everything related to executing MADA Tools commands.

**Usage:**

```bash
mada-tools [OPTIONS] COMMAND [ARGS] ...
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
| `-v`, `--version` | boolean | Show program's version number and exit | `False` |
| `-l`, `--log-level` | choice(`CRITICAL` | `ERROR` | `WARNING` | `INFO` | `DEBUG` | `NOTSET` ) | Level of logging messages to be output. The smaller the number in the table below, the more output that's produced: <table>  <thead>  <th></th>  <th>Log Level Choice</th>  </thead>  <tbody> <tr>  <td>5</td>  <td>CRITICAL</td>  </tr>  <tr>  <td>4</td>  <td>ERROR</td>  </tr>  <tr>  <td>3</td>  <td>WARNING</td>  </tr>  <tr>  <td>2</td>  <td>INFO (default)</td>  </tr>  <tr>  <td>1</td>  <td>DEBUG</td>  </tr> <tr>  <td>0</td>  <td>NOTSET</td>  </tr>  </tbody>  </table> | INFO |
| `--log-file` | string | Optional path to a log file | None |

## Start Servers (`mada-tools start-servers`)

Given a configuration file of servers that need to be started, spin them up with the `mada-tools start-servers` command.

This command allows you to tailor which servers can be started and where by defining them in a configuration file. You can also pick and choose individual servers from the configuration file to start using the `-s` or `--servers` flag.

When servers are started, they are tracked in a state file. You can provide a custom state file with the `-f` or `--state-file` flag.

See [Starting Servers](./server_management.md#starting-servers) for more information.

**Usage:**

```bash
mada-tools start-servers CONFIG_FILE [OPTIONS]
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
| `-s`, `--servers` | List[string] | Optional, space-delimited list of servers to start. If none are provided, all servers will be started | None |
| `-f`, `--state-file` | string | Path to a file tracking server state | `~/.mada/server_statuses.json` |

## Stop Servers (`mada-tools stop-servers`)

Stop currently running servers with the `mada-tools stop-servers` command.

This command allows you to stop:

- All servers (no flags)
- Specific servers (`-s` or `--servers` flag)
- All servers in a single configuration file (`-c` or `--config` flag)

When servers are stopped, their statuses must be updated in the state file. To point to a different state file than the default (`~/.mada/server_statuses.json`), you can use the `-f` or `--state-file` flag.

See [Stopping Servers](./server_management.md#stopping-servers) for more information.

**Usage:**

```bash
mada-tools stop-servers [OPTIONS]
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
| `-c`, `--config` | string | Optional path to a server configuration file. If provided, only the servers defined in this file will be stopped | None |
| `-s`, `--servers` | List[string] | Optional, space-delimited list of servers to stop. If none are provided all running servers will be stopped | None |
| `-f`, `--state-file` | string | Path to a file tracking server state | `~/.mada/server_statuses.json` |

## Restart Servers (`mada-tools restart-servers`)

You may find yourself needing to restart servers. This can be accomplished with the `mada-tools restart-servers` command.

This command will first stop all running servers from the configuration file you pass it, and then start them all up again.

To select only specific servers from your configuration file to restart, use the `-s` or `--servers` flag.

When servers are restarted, their statuses must be updated in the state file. To point to a different state file than the default (`~/.mada/server_statuses.json`), you can use the `-f` or `--state-file` flag.

See [Restarting Servers](./server_management.md#restarting-servers) for more information.

**Usage:**

```bash
mada-tools restart-servers CONFIG_FILE [OPTIONS]
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
| `-s`, `--servers` | List[string] | Optional, space-delimited list of servers to start. If none are provided, all servers will be started | None |
| `-f`, `--state-file` | string | Path to a file tracking server state | `~/.mada/server_statuses.json` |

## Servers Status (`mada-tools servers-status`)

To check the status of your servers, you can utilize the `mada-tools servers-status` command.

This command interacts with the state file that's created when your servers are spun up. By default this state file will be located at `~/.mada/server_statuses.json`. To point to a different state file than the default (`~/.mada/server_statuses.json`), you can use the `-f` or `--state-file` flag.

This command allows you to get the status of:

- All servers (no flags)
- Specific servers (`-s` or `--servers` flag)
- All servers in a single configuration file (`-c` or `--config` flag)

See [Checking Server Statuses](./server_management.md#checking-server-statuses) for more information.

**Usage:**

```bash
mada-tools servers-status [OPTIONS]
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
| `-c`, `--config` | string | Optional path to a server configuration file. If provided, status is only checked for the servers defined in this file | None |
| `-s`, `--servers` | List[string] | Optional, space-delimited list of servers to check. If none are provided all servers will be shown | None |
| `-f`, `--state-file` | string | Path to a file tracking server state | `~/.mada/server_statuses.json` |

## Available Servers (`mada-tools available-servers`)

View the servers available with MADA. This will include built in servers and any [plugin servers](../developer_guide/server_creation/plugin_servers.md) installed in your environment.

**Usage:**

```bash
mada-tools available-servers [OPTIONS]
```

**Options:**

| Name | Type | Description | Default |
| ---- | ---- | ----------- | ------- |
| `-h`, `--help` | boolean | Show this help message and exit | `False` |
