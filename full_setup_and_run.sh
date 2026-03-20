#!/bin/bash

# Exit on error
set -e

PORT=5580

echo "--- 1. Checking Prerequisites ---"
if ! command -v node &> /dev/null; then
    echo "Error: 'node' is not installed. Please install Node.js."
    exit 1
fi
if ! command -v npm &> /dev/null; then
    echo "Error: 'npm' is not installed. Please install npm."
    exit 1
fi

echo "--- 2. Cleaning up existing processes on port $PORT ---"
PID=$(lsof -t -i:$PORT) || true
if [ -n "$PID" ]; then
    echo "Killing process $PID..."
    kill -9 $PID
fi

echo "--- 3. Setting up Python Environment ---"
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[server]"
else
    source .venv/bin/activate
fi

echo "--- 4. Building Dashboard UI ---"
# Check if we need to build or if it's already there
# We'll build it to be sure, as it might be missing on a new machine
cd dashboard
echo "Installing dashboard dependencies (this may take a minute)..."
npm install
echo "Compiling dashboard..."
# Running the build script directly
./script/build
cd ..

echo "--- 5. Starting Matter Server ---"
# Determine the IP address to show the correct URL
IP_ADDR=$(hostname -I | awk '{print $1}')
echo "Matter Server UI will be available at: http://$IP_ADDR:$PORT"
echo "Starting server... (Press Ctrl+C to stop)"

# Open browser if on Mac, otherwise just print the URL
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 5 && open "http://localhost:$PORT") &
fi

# We use --listen-address 0.0.0.0 to ensure it's accessible on the network (Pi usage)
python3 -m matter_server.server --listen-address 0.0.0.0 --bluetooth-adapter 0
