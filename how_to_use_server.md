# How to Use Matter Server

This guide provides instructions on how to set up, run, and interact with the Matter Server in this repository.

## Prerequisites

- macOS or Linux
- Python 3.12+

## Initial Setup

If you haven't already, set up the development environment by running the setup script. This will create a virtual environment and install dependencies.

```bash
bash scripts/setup.sh
```

## Running the Server

We provide a convenient script `run.sh` that handles process cleanup and environment activation.

1.  **Start the server:**

    ```bash
    bash run.sh
    ```

    This script will:
    - Kill any process already running on port `5580`.
    - Activate the `.venv` virtual environment.
    - Start the Matter Server.

### Running on Raspberry Pi / Linux (Full Setup)

If you are running on a fresh Raspberry Pi or Linux machine and the UI is not appearing, use the **Full Setup** script. This will compile the Dashboard for you automatically.

```bash
bash full_setup_and_run.sh
```

**What this does:**

1. Installs dashboard dependencies (`npm install`).
2. Compiles the UI (`rollup`/`tsc`).
3. Starts the server on `0.0.0.0` (accessible from your network).
4. Prints your IP address so you know where to visit the UI.

5. **Stop the server:**
   Press `Ctrl + C` in the terminal where the server is running.

## Advanced Usage

You can run the server manually with additional arguments if needed (e.g., changing port or logging level).

```bash
source .venv/bin/activate
python3 -m matter_server.server --help
```

### Common Arguments

- `--port`: Specify a different port (default: 5580).
- `--log-level`: Set log level (debug, info, warning, error).
- `--storage-path`: Path to persistent storage (default: ~/.matter_server).

## Interacting with the Server

The Matter Server provides several ways to interact with it: a Web UI (Dashboard), a WebSocket API, and a basic HTTP info endpoint.

### 1. Web UI (Dashboard)

The server hosts a web-based dashboard for debugging and testing.

- **URL:** [http://localhost:5580](http://localhost:5580)
- **Note:** The dashboard is only available if it has been pre-built. If you see a "404 Not Found" or a blank page, you may need to build it manually (see the `dashboard` directory for instructions).

### 2. WebSocket API

The primary way to control Matter devices is through the WebSocket API.

- **Endpoint:** `ws://localhost:5580/ws`
- **Commands:** You can send JSON commands to commission devices, read/write attributes, and send device commands. Refer to [docs/websockets_api.md](docs/websockets_api.md) for a list of available commands.

#### Example: Get Commissioned Nodes

Send this JSON over the WebSocket:

```json
{
  "message_id": "1",
  "command": "get_nodes"
}
```

### 3. HTTP Info Endpoint

You can get basic server information (like versions and fabric ID) via a simple GET request.

- **URL:** [http://localhost:5580/info](http://localhost:5580/info)
- **Method:** `GET`

### 4. Python Client (Recommended)

The easiest way to interact with the server programmatically is using the provided client library.

```bash
source .venv/bin/activate
python3 scripts/example.py
```

### 5. CLI Client Utility (New)

We have provided a versatile CLI client script in `scripts/cli_client.py` that allows you to manage the server without writing any code or manual WebSocket JSON.

**Basic Usage:**

```bash
source .venv/bin/activate
python3 scripts/cli_client.py --help
```

**Common CLI Commands:**

- **List All Nodes:**
  ```bash
  python3 scripts/cli_client.py nodes
  ```
- **Get Server Info:**
  ```bash
  python3 scripts/cli_client.py info
  ```
- **Commission a New Device:**
  ```bash
  python3 scripts/cli_client.py commission <PAIRING_CODE_OR_QR_CODE>
  ```
- **Control a Device (On/Off/Toggle):**

  ```bash
  # Turn on node 1, endpoint 1
  python3 scripts/cli_client.py on 1 1

  # Toggle node 1
  python3 scripts/cli_client.py toggle 1
  ```

- **Listen for Real-Time Events:**
  ```bash
  python3 scripts/cli_client.py listen
  ```

## Common Tasks

### Commissioning a New Device

To add a new Matter device to your fabric, you can use the CLI:

```bash
python3 scripts/cli_client.py commission MT:Y.ABCDEFG123456789
```

Or use the Web UI/Dashboard if available.

### Getting Live Events

To see exactly what's happening on the server in real-time (e.g., attribute changes, node additions):

```bash
python3 scripts/cli_client.py listen
```

This will print every event received from the server until you stop it with `Ctrl+C`.

## Troubleshooting

- **Port Conflict:** If the server fails to start because of a port conflict, `run.sh` should handle it. If not, manual cleanup might be needed: `kill -9 $(lsof -t -i:5580)`.
- **Dependencies:** Ensure you are in the virtual environment (`source .venv/bin/activate`) before running any python commands.
- **Connection Refused:** Ensure the server is running (`bash run.sh`) before using the CLI client.
- **Web UI 404:** If the dashboard doesn't load, it might not be built. Check the `dashboard/README.md` for build instructions.
