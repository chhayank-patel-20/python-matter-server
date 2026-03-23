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
- **Decision**: Added automatic extraction of the discriminator from the setup code (QR or manual) using `chip.setup_payload.setup_payload.SetupPayload`. The logic now supports both long and short discriminators.
- **Rationale**: The CHIP SDK's `CommissionWithCode` requires a discriminator when searching for a device via BLE or mDNS. Manual pairing codes often only contain a short discriminator. By extracting whichever is available (long or short) and passing it to the SDK with the correct `isShortDiscriminator` flag, we ensure the SDK has the necessary information to find the device.
