#!/bin/bash

# Port used by Matter Server
PORT=5580

echo "--- 1. Killing existing Matter Server processes on port $PORT ---"
# Find and kill process using the port
PID=$(lsof -t -i:$PORT)
if [ -n "$PID" ]; then
    echo "Killing process $PID..."
    kill -9 $PID
else
    echo "No process found on port $PORT."
fi

echo "--- 2. Activating virtual environment ---"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "Virtual environment activated."
else
    echo "Error: Virtual environment (.venv) not found. Please run scripts/setup.sh first."
    exit 1
fi

echo "--- 3. Running Matter Server ---"
echo "Matter Server UI will be available at: http://localhost:$PORT"
echo "Starting server... (Press Ctrl+C to stop)"

# Open the UI in the default browser (Mac only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 2 && open "http://localhost:$PORT") &
fi

python3 -m matter_server.server --bluetooth-adapter 0 --log-level DEBUG
