# Architectural Decisions

## 2026-03-20: Discovery API Fixes

### 1. Rename DISCOVER command to discover_commissionable_nodes
- **Decision**: Renamed `APICommand.DISCOVER` from `"discover"` to `"discover_commissionable_nodes"`.
- **Rationale**:
  - Aligns with the method name in `device_controller.py` and `sdk.py`.
  - Fixes a mismatch with the dashboard (which was already using the longer name).
  - Provides a more descriptive and unambiguous command name.

### 2. Wrap DiscoverCommissionableNodes in SDK executor
- **Decision**: Changed `discover_commissionable_nodes` in `sdk.py` to use `await self._call_sdk(...)` instead of direct `await`.
- **Rationale**: The native SDK's `DiscoverCommissionableNodes` is synchronous and returns a list. Awaiting it directly caused a `TypeError`. Using `_call_sdk` offloads it to a thread pool, preventing event loop blocking.
