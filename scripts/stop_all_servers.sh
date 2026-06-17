#!/bin/bash
# Stop all MADA MCP servers

LOG_DIR="logs"
PID_FILE="$LOG_DIR/server_pids.txt"

if [ -f "$PID_FILE" ]; then
    echo "Stopping MADA MCP servers..."
    PIDS=$(cat $PID_FILE)
    for pid in $PIDS; do
        if kill -0 $pid 2>/dev/null; then
            echo "Stopping process $pid"
            kill $pid
        fi
    done
    rm $PID_FILE
    echo "All servers stopped."
else
    echo "No PID file found. Servers may not be running."
fi
