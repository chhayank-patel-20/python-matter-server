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

### 4. Fix AttributeError in discovery
- **Decision**: Added explicit `await` for each item in the SDK discovery result if it's a coroutine.
- **Rationale**: The underlying CHIP SDK's `DiscoverCommissionableNodes` might return a list of coroutines (or objects that need to be awaited). Manually resolving them prevents `AttributeError: 'coroutine' object has no attribute 'instanceName'`.
