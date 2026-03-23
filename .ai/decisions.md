# Architectural Decisions

## 2026-03-20: Discovery API Fixes

### 1. Rename DISCOVER command to discover_commissionable_nodes
- **Decision**: Renamed `APICommand.DISCOVER` from `"discover"` to `"discover_commissionable_nodes"`.
- **Rationale**:
  - Aligns with the method name in `device_controller.py` and `sdk.py`.
  - Fixes a mismatch with the dashboard (which was already using the longer name).
  - Provides a more descriptive and unambiguous command name.

### 3. Log incoming command payloads
- **Decision**: Added `self._logger.debug("Received command %s with args: %s", command_msg.command, command_msg.args)` in `WebsocketClientHandler`.
- **Rationale**: Facilitates debugging by providing visibility into the exact payloads sent by clients.

### 4. Fix AttributeError in discovery (coroutine and list objects)
- **Decision**: Added explicit resolution for both coroutines and nested lists in the SDK discovery result.
- **Rationale**: The underlying CHIP SDK's `DiscoverCommissionableNodes` might return a single node, a list of nodes, or a list of coroutines/objects that resolve to nodes or lists of nodes. The updated logic robustly flattens and awaits these results to prevent `AttributeError` for both `'coroutine'` and `'list'` objects.

### 5. Fix "Long discriminator is required" error during commissioning
- **Decision**: Implemented a fallback mechanism that uses `ChipDeviceController.ConnectBLE` (via a new `commission_ble` SDK wrapper) when a discriminator is extracted from the setup code.
- **Rationale**: The SDK's standard `CommissionWithCode` does not accept an explicit discriminator as an argument, which can cause discovery to fail over BLE (e.g., "Long discriminator is required" or timeouts). By extracting the discriminator and PIN from the setup code and using `ConnectBLE` directly, we provide the SDK with the exact parameters it needs for successful discovery and pairing.

### 6. Persistent storage of WiFi/Thread credentials for commissioning
- **Decision**: Added internal storage for the last provided WiFi and Thread credentials in `MatterDeviceController`.
- **Rationale**: Matter devices being commissioned over BLE need network credentials to join the local network. By storing these credentials when they are set via the API, we can automatically provide them to the SDK during the `commission_ble` process, resolving "Required network information not provided" errors.

## 2026-03-23: Group Management APIs and Automatic Group Key Initialization

### 1. Add Server-side Group Registry
- **Decision**: Added `get_groups`, `add_group`, and `remove_group` API commands and a persistent group registry in `MatterDeviceController`.
- **Rationale**: Users need a centralized way to manage Matter groups at the server level, rather than just querying distributed node membership. This registry stores `group_id` and `group_name` mapping.

### 2. Automatic Initialization of Group Testing Data
- **Decision**: Added an automatic call to `init_group_testing_data` in `MatterDeviceController.start()`.
- **Rationale**: Fixes `CHIP Error 0x000000AC: Internal error` when sending group commands. This error occurs if the controller's group data provider hasn't been initialized with keys. By doing this automatically at startup, we provide a "works out of the box" experience for group commands in development/testing environments.

### 3. Sync node group membership with server registry
- **Decision**: Updated `group_add` to automatically add a group to the server-side registry if it doesn't already exist.
- **Rationale**: Ensures consistency between what's configured on nodes and what's known to the server.
