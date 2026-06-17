#!/bin/bash
# Start all MADA MCP servers

set -e

CONFIG_FILE=${1:-"configs/development.json"}
LOG_DIR="logs"

# Create log directory
mkdir -p $LOG_DIR

echo "Starting MADA MCP Servers with config: $CONFIG_FILE"

# Start each server in background
echo "Starting Flux server..."
mada-mcp-flux --config $CONFIG_FILE > $LOG_DIR/flux.log 2>&1 &
FLUX_PID=$!

echo "Starting Professor server..."
mada-mcp-professor --config $CONFIG_FILE > $LOG_DIR/professor.log 2>&1 &
PROFESSOR_PID=$!

echo "Starting Job Monitor server..."
mada-mcp-monitor --config "$CONFIG_FILE" > "$LOG_DIR/monitor.log" 2>&1 &
MONITOR_PID=$!

# Write PIDs to file for easy cleanup
echo "$FLUX_PID $SLURM_PID $MERLIN_PID $PROFESSOR_PID $MONITOR_PID" > $LOG_DIR/server_pids.txt

echo "All servers started successfully!"
echo "Server PIDs saved to $LOG_DIR/server_pids.txt"
echo "Logs available in $LOG_DIR/"

# Wait for interrupt
trap 'echo "Stopping all servers..."; kill $FLUX_PID $MERLIN_PID $PROFESSOR_PID $MONITOR_PID; exit 0' INT
wait
