# Project Context: Matter Server (python-matter-server)

## Overview
An open-source implementation of a Matter controller server using the official Matter (CHIP) SDK. It provides a WebSocket API for managing Matter nodes, commissioning devices, and interacting with clusters.

## Architecture
- **Server**: `matter_server/server/` (asyncio-based, using `aiohttp`).
- **SDK Wrapper**: `matter_server/server/sdk.py` (wraps synchronous/native CHIP SDK methods).
- **Client**: `matter_server/client/` (Python client for the server).
- **Dashboard**: `dashboard/` (Web-based UI for managing nodes).
- **Common**: `matter_server/common/` (Shared models and constants).

## Key Patterns
- **API Commands**: Decorated with `@api_command(APICommand.NAME)` in the server.
- **SDK Calls**: Synchronous SDK calls must be wrapped in `_call_sdk` to run in an executor.
- **Discovery**: The `discover_commissionable_nodes` command uses the underlying CHIP SDK to find devices via both BLE and mDNS. BLE discovery requires a valid `bluetooth_adapter_id` and the target device must be in pairing mode.
- **Events**: System-wide events (e.g., `discovery_updated`) are signaled via `server.signal_event`.

## Important Files
- `matter_server/common/models.py`: API command enums and data models.
- `matter_server/server/sdk.py`: The bridge to the native Matter SDK.
- `docs/websockets_api.md`: Documentation for the WebSocket interface.
