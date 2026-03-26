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

## 2026-03-26: Spec-Compliant Group Management Refactor

### 1. Remove Server-side Group Registry
- **Decision**: Removed `get_groups`, `add_group`, `remove_group` API commands and the `_groups` dict / `MatterGroupInfo` model. Replaced with a minimal `_group_key_store` (group_id → keyset_id + epoch_key_hex) persisted under `DATA_KEY_GROUP_KEYS`.
- **Rationale**: Matter specifies that group membership is owned by the device (Groups cluster on each endpoint). The server-side registry created state divergence and violated the spec. Devices are now the source of truth; `group_get_membership` reads directly from the device.

### 2. Remove Automatic init_group_testing_data at Startup
- **Decision**: Removed the automatic `init_group_testing_data()` call from `MatterDeviceController.start()`. It is now only available as an explicit API command for testing.
- **Rationale**: This call rewrites the controller's FabricData linked list, orphaning any custom group keys. Custom groups survive restarts because chip.json already contains the correct entries from the initial `_inject_controller_group_keys` call; re-injection is not needed.

### 3. Descriptor Cluster Validation in group_add
- **Decision**: `group_add` now reads `Descriptor.ServerList` for the target endpoint and raises `InvalidArguments` if cluster ID 4 (Groups) is not present.
- **Rationale**: Follows Matter spec requirement to verify endpoint capability before issuing cluster commands. Prevents silent failures on endpoints that don't support the Groups cluster.

### 4. Simplified Controller Key Injection (_inject_controller_group_keys)
- **Decision**: Replaced `_ensure_controller_group_keys` (which also wrote GroupInfo entries) and `_overwrite_controller_keyset` (migration for old buggy keys) with a single `_inject_controller_group_keys(group_id, keyset_id, epoch_key_hex)`.
- **Rationale**: GroupInfo entries in the controller KVS are NOT required for `SendGroupCommand` (which traverses only the KeyMap→KeySet path). Removing GroupInfo writing significantly simplifies TLV injection. The migration helpers are no longer needed since the new code always writes correct HKDF-derived keys on first use.

## 2026-03-23: Group Management APIs (superseded by 2026-03-26 refactor)

## 2026-03-23: Robust Group Management and 0xAC Error Handling

### 1. Automatic Retry for CHIP Error 0xAC (Internal Error)
- **Decision**: Added a try-except block in `send_group_command` that catches `ChipStackError` with error code `0xAC`. Upon catching this error, the server calls `init_group_testing_data()` and retries the command once.
- **Rationale**: `0xAC` (CHIP_ERROR_INTERNAL) often occurs in `SendGroupCommand` if the controller's `GroupDataProvider` doesn't have keys for the current fabric. Re-initializing the testing data before retrying provides a self-healing mechanism for environments where the fabric state might have changed.

### 2. APIs for Node-side Group Key Management
- **Decision**: Implemented `group_add_key_set` and `group_bind_key_set` API commands.
- **Rationale**: Real Matter devices do not come with test group keys by default. To make group commands work with real hardware, the user must be able to program the node's `GroupKeyManagement` cluster. These new APIs allow the user to install keysets and map group IDs to those keysets on any commissioned node.

### 3. Documented Group ID Limitations in Test Mode
- **Decision**: Added documentation explaining that `init_group_testing_data` typically only supports Group IDs `257` (0x0101) and `258` (0x0102) for the controller.
- **Rationale**: The SDK's built-in test data is hardcoded to specific Group IDs. Users using IDs like `1` or `2` will receive `0xAC` because the controller lacks keys for those IDs. Explicit documentation and an improved error message guide the user to working IDs.

### 4. Production-Ready Group Keys (Transparent Key Generation)
- **Decision**: Implemented an automated group key generation and injection system in `MatterDeviceController`. When a new group is added, the server generates a 16-byte random `epoch_key` and unique `keyset_id`, stores them, and uses TLV encoding to inject these directly into the underlying `chip.storage.PersistentStorage` used by the controller's C++ `GroupDataProviderImpl`.
- **Rationale**: The Python Matter SDK wrapper doesn't expose native C++ methods to configure the controller's group keys locally, forcing users to rely on the hardcoded `InitGroupTestingData`. By writing directly to the underlying KVS (which `GroupDataProviderImpl` reads on every `GetGroupKey` call), we bypass this limitation. When `group_add` is called, the server now automatically pushes the generated `KeySetWrite` and `GroupKeyMap` to the node. This provides a transparent, "production-ready" Group Communication experience without manual key management.

### 5. Preservation of Identity Protection Key (IPK)
- **Decision**: Refined the TLV injection logic to use `0xFFFF` (`kInvalidKeysetId`) as the linked-list terminator and ensured that existing keysets (specifically the IPK with ID `0`) are preserved.
- **Rationale**: The IPK is essential for establishing secure CASE sessions between nodes. If the linked-list of keysets is corrupted or uses an incorrect terminator (like `0`), the SDK fails to find the IPK, resulting in `CHIP Error 0x000000D8: The item referenced in the function call was not found` and preventing all communication with commissioned nodes.

## 2026-03-24: Fix Group Key Derivation (Critical Bug Fix)

### Root Cause
`GroupDataProviderImpl` (C++) stores **derived** `GroupOperationalCredentials` in KVS, not raw epoch keys. The derivation is:
```
EncryptionKey = HKDF-SHA256(InputKey=epoch_key, Salt=CompressedFabricId, Info="GroupKey v1.0")
SessionId     = first 2 bytes of HKDF-SHA256(InputKey=EncryptionKey, Salt=zeros32, Info="GroupKeyHash")
```
The previous TLV injection stored the raw epoch key as `TagKeyValue` (tag 6) and a hardcoded `0` as `TagKeyHash` (tag 5). This caused every `SendGroupCommand` to encrypt with the wrong key → nodes could never decrypt group messages.

### Bug 1: Wrong key stored in KVS (critical)
- **Decision**: Added `_derive_group_encryption_key` and `_derive_group_session_id` static methods implementing the HKDF derivations from the Matter spec. The keyset TLV now stores the derived encryption key and correct session ID.
- **Rationale**: The C++ `SetKeySet` runs this derivation before writing to KVS. Our Python injection must mirror it exactly or the keys will never match.

### Bug 2: TLV keyset array had only 1 item instead of 3 (critical)
- **Decision**: The keyset `tag3` array now always has exactly 3 items (`kEpochKeysMax`), with slots 1 and 2 zero-filled.
- **Rationale**: `KeySetData::Deserialize` always reads exactly 3 items from the array via `for (auto & key : operational_keys)`. Writing only 1 item caused a TLV parse failure, so the keyset could never be loaded at all.

### Bug 3: Missing startup migration for existing groups
- **Decision**: Added `_overwrite_controller_keyset` method. Called in `start()` for every stored group before `_ensure_controller_group_keys`. It re-derives and overwrites the keyset KVS entry while preserving the linked-list `next` pointer.
- **Rationale**: Existing groups stored with the old buggy code need their keyset KVS entry updated. The `_ensure_controller_group_keys` early-return guard prevented this fix from taking effect for already-stored groups.

### Bug 4: All TLV integer values written as signed instead of unsigned (Critical root cause)
- **Decision**: Import `chip.tlv.uint as tlv_uint` in `device_controller.py` and wrap every integer value in `tlv_uint()` within `_ensure_controller_group_keys` and `_overwrite_controller_keyset`.
- **Rationale**: Python `TLVWriter.put()` dispatches plain `int` to `putSignedInt()`. C++ `TLVReader::Get(uint16_t/uint8_t)` only accepts `UInt8`/`UInt16` TLV element types — a signed `Int8` hits the default case → `CHIP_ERROR_WRONG_TLV_TYPE`. ALL our TLV fields were affected: FabricData, GroupInfo, KeyMapData, KeySetData. This was the root cause of every `CHIP Error 0x00000026` crash.

### Bug 6: `init_group_testing_data` ran after custom key injection, orphaning our entries
- **Decision**: Moved `init_group_testing_data()` call to **before** the group injection loop in `MatterDeviceController.start()`.
- **Rationale**: `init_group_testing_data()` calls the C++ `InitGroupDataForFabric` API which rewrites `f/X/g` (FabricData) with `first_map` and `first_keyset` pointers that reference only test groups (257, 258). Any GroupInfo/KeyMapData/KeySetData our Python code had already written for group 1 was still in KVS but orphaned — FabricData no longer pointed to it. `GetGroupSession` traversal starting from the test `first_map` never reached group_id=1, causing `CHIP_ERROR_INTERNAL` (0xAC) in `SessionManager.cpp:234` on every `SendGroupCommand`. By running test data init first, our subsequent `_ensure_controller_group_keys` reads the C++-written FabricData and correctly prepends group 1 into the existing linked lists.

### Bug 5: Startup cleanup missed FabricData, GroupData, and KeyMapData
- **Decision**: Renamed to `_cleanup_corrupted_group_storage()` and extended to also delete `f/X/g` (FabricData), `f/X/g/Y` (GroupInfo), and `f/X/gk/Y` (KeyMapData) in addition to non-IPK keysets. All are recreated with correct `tlv_uint` values by `MatterDeviceController.start()`.
- **Rationale**: After fixing the keyset-only cleanup, the crash persisted because FabricData/GroupInfo/KeyMapData entries remained with signed-int TLV. Deleting all group storage entries forces clean recreation on startup. Key note: `chip.json` has structure `{"sdk-config": {...}, "repl-config": {...}}` — SDK entries live under `sdk-config`, not at the top level.

## 2026-03-24: Fix BLE Commissioning Network Information Error

### 1. Use specialized CommissionWiFi and CommissionThread methods
- **Decision**: Updated `commission_ble` in `sdk.py` to use `self._chip_controller.CommissionWiFi` and `self._chip_controller.CommissionThread` when WiFi credentials or a Thread dataset are provided, instead of the generic `ConnectBLE`.
- **Rationale**: The SDK's `ConnectBLE` establishes a session but may fail to pass pre-set network credentials to the internal `AutoCommissioner`, resulting in `CHIP Error 0x0000002F: Invalid argument` and the log message "Required network information not provided in commissioning parameters". By using the specialized methods and passing credentials directly as arguments, we ensure the `AutoCommissioner` has the necessary information to complete the commissioning process for WiFi and Thread devices.

## 2026-03-25: BLE Scanner and MAC-based Commissioning APIs

### 1. Add `scan_ble_devices` API command (using bleak)
- **Decision**: Added `scan_ble_devices(mac_address, timeout)` API command in `device_controller.py` using the `bleak` library. Added `BLEScanResult` dataclass to `models.py` and `bleak>=0.21.0` to `pyproject.toml` server extras.
- **Rationale**: The existing `discover_commissionable_nodes` only returns CHIP-SDK parsed Matter nodes (filtered). Users need a lower-level raw BLE scan to: (a) find a device by MAC, (b) inspect advertisement data to diagnose commissioning readiness, (c) confirm whether `fff6` Matter service UUID is present before attempting commissioning.

### 2. Add `commission_with_mac` API command
- **Decision**: Added `commission_with_mac(mac_address, setup_pin_code, scan_timeout)` which scans for a device by MAC, extracts the discriminator from the `fff6` service data, and calls the existing `commission_ble` flow.
- **Rationale**: Users should not need the QR code to commission — the MAC address (visible on a label) + PIN code is sufficient when the device is in commissioning mode. The CHIP SDK does not support MAC-based BLE connection (requires discriminator), so we extract it automatically from the BLE advertisement. If the device is NOT in commissioning mode (no `fff6` UUID), a clear error is returned explaining the user must open a commissioning window first.

### 3. Why fff6 UUID is absent sometimes (documented)
- The Matter BLE commissioning window is only open for a limited time after a button press or factory reset. Without `fff6`, the CHIP SDK cannot commission the device — the discriminator, vendor ID, and product ID encoded in the 8-byte `fff6` service data are required. This is now explained in `docs/websockets_api.md`.

## 2026-03-25: Multi-Fabric Commissioning Support

### 1. Add `commission_on_commissioning_window` API command
- **Decision**: Added a dedicated `commission_on_commissioning_window(setup_pin_code, discriminator, ip_addr, fabric_label)` API command as the explicit Multi-Fabric Commissioning path.
- **Rationale**: While `commission_on_network` with `FilterType.LONG_DISCRIMINATOR` could technically do this, it is not obvious. A dedicated, clearly-named command makes the multi-fabric use case self-documenting. Internally it calls the same `commission_on_network` SDK path with the long-discriminator filter.

### 2. Add `fabric_label` parameter to all commissioning commands
- **Decision**: Added optional `fabric_label: str | None` parameter to `commission_with_code`, `commission_on_network`, `commission_with_mac`, and `commission_on_commissioning_window`. When provided, calls `update_fabric_label` after successful commissioning.
- **Rationale**: In multi-fabric setups, devices appear in multiple controllers' fabric tables. A fabric label (up to 32 chars) identifies which controller owns which fabric entry, visible via `get_fabrics(node_id)`. Errors in setting the label are logged as warnings and do not fail commissioning.

### 3. Multi-Fabric flow is now fully documented
- **Decision**: Updated `docs/websockets_api.md` with the full two-step multi-fabric flow, updated `open_commissioning_window` docs to explain its role (Step 1), and added `commission_on_commissioning_window` docs (Step 2).
- **Rationale**: The `open_commissioning_window` already existed but was not documented as part of a multi-fabric flow. Combined with the new command, users now have a complete, documented path.

## 2026-03-25: Fix group_add Failures (Timed Interaction)

### 1. Add timed interaction to `AddGroup` command
- **Decision**: Added `timed_request_timeout_ms=5000` to the `send_command` call for `AddGroup` in `group_add` (`device_controller.py`).
- **Rationale**: Matter spec §11.2.6.1 requires a timed interaction for `AddGroup`. Without it, real devices reject the command with `UNSUPPORTED_ACCESS` (0x7e).

### 2. Add timed-write support to `write_attribute` in `sdk.py`
- **Decision**: Added `timed_request_timeout_ms: int | None = None` parameter to `write_attribute` in `sdk.py`, passed through as `timedWriteTimeoutMs` to `chip_controller.WriteAttribute`. Updated `group_bind_key_set` to pass `timed_request_timeout_ms=5000`.
- **Rationale**: `GroupKeyMap` is a fabric-scoped security attribute that requires timed interaction per Matter spec §11.2.7.1. The `write_attribute` wrapper previously had no way to enable timed writes.

### 3. Increase `group_add_key_set` timed timeout from 1000ms to 5000ms
- **Decision**: Changed `timed_request_timeout_ms` from `1000` to `5000` in `group_add_key_set`.
- **Rationale**: 1 second was too tight for `KeySetWrite` over a wireless path, causing silent failures (exceptions caught as warnings in `group_add`) before the key was actually provisioned.

## 2026-03-25: group_send_command Fixes (Test and Non-Test Groups)

### 1. Fix early-return guard for Test Group IDs (257/258/259)
- **Decision**: Changed the early-return guard in `_ensure_controller_group_keys` from checking for the existence of the `GroupInfo` SDK key to checking if `group.keyset_id` is already set. Added conditional logic to only write `GroupInfo` and increment the group count if it doesn't already exist.
- **Rationale**: `init_group_testing_data()` creates `GroupInfo` entries for test groups at startup. The previous guard would see these entries and return early before generating keys or setting `keyset_id`, causing node provisioning to be skipped. The new logic ensures keys are always generated while avoiding circular references in the linked list for groups already initialized by the SDK.

### 2. Fix `InvalidCommand` (0x85) for Non-Test Groups
- **Decision**: Updated `group_add_key_set` to use `epochStartTime0=1` instead of `0`.
- **Rationale**: Per Matter Core Spec §11.2.6.1.1, if `EpochKey0` is not null, `EpochStartTime0` must be a non-zero value. Real devices (like Tapo) strictly enforce this and reject `KeySetWrite` with `InvalidCommand` if it is zero. Setting it to `1` (1 microsecond past the Matter epoch) satisfies the spec and allows successful key provisioning.

## 2026-03-26: ResourceExhausted Fix for group_add Key Provisioning

### 1. Device as source of truth for keyset state
- **Decision**: Before calling `KeySetWrite`, read the device's `GroupKeyManagement.Attributes.GroupKeyMap` to determine which keysets are already installed. Skip `KeySetWrite` if the exact keyset is already present; only write if the device doesn't have it yet.
- **Rationale**: Devices have a fixed keyset table (typically 3 slots). Blindly writing a new keyset on every `group_add` call exhausted the table, causing `ResourceExhausted (0x89)` on the second group. The device is authoritative; the server-side `_group_key_store` is only for crypto material persistence.

### 2. Fallback to reusable server-managed keyset on ResourceExhausted
- **Decision**: If `KeySetWrite` returns `ResourceExhausted`, compute the intersection of server-managed keyset IDs and the keyset IDs already on the device. Reuse the lowest-ID match by remapping `group_id → that keyset` in `_group_key_store` and updating the device's `GroupKeyMap`.
- **Rationale**: If the table is truly full, we cannot install a new keyset. But we can reuse a keyset the server already knows the key for — any server-managed keyset already on the device shares the same epoch key, so `SendGroupCommand` will still encrypt correctly.

### 3. New helpers: `_get_node_group_key_map`, `_provision_group_keys_on_node`, `_is_resource_exhausted_err`
- **Decision**: Extracted provisioning logic into a dedicated `_provision_group_keys_on_node` coroutine called by `group_add`. Reading the device state is always done via `_get_node_group_key_map`. Error classification is handled by the static `_is_resource_exhausted_err`.
- **Rationale**: Keeps `group_add` clean and readable; makes the provisioning algorithm independently testable.

## 2026-03-26: group_list, group_remove_all, and group-table Exhaustion Fix

### 1. Add `group_list` command
- **Decision**: New `group_list` API command that calls `Groups.GetGroupMembership(groupList=[])` for IDs and remaining capacity, then calls `Groups.ViewGroup` per group ID to get the name. Returns `GroupListResult` with `node_id`, `endpoint`, `remaining_capacity`, and `groups: list[MatterGroupInfo]`.
- **Rationale**: The UI had no way to display existing groups or know how many slots remain. `GetGroupMembership` alone gives only IDs; `ViewGroup` is required for names. Fetching both in one command gives the frontend everything it needs.

### 2. Add `group_remove_all` command
- **Decision**: New `group_remove_all` API command that sends `Groups.RemoveAllGroups()` to the specified endpoint.
- **Rationale**: When a device's group table is full and the user wants a clean slate (e.g. after a keyset table exhaustion error), there was no single-call way to clear all groups. `RemoveAllGroups` is part of the Matter Groups cluster spec (§11.2.7.4) and is the correct mechanism.

### 3. FIFO group eviction in `group_add` when table is full
- **Decision**: Before calling `AddGroup`, `group_add` now calls `_get_group_membership_and_capacity` (wraps `GetGroupMembership`). If `remaining_capacity == 0` and the target group is not already a member, the **first group in the returned list is removed** (FIFO) to free a slot.
- **Rationale**: Devices have a fixed group table size (e.g. 4 entries). Without a capacity check, `AddGroup` would succeed on the node level only to fail during key provisioning or vice versa, leaving the device in an inconsistent state. FIFO eviction is a simple, predictable strategy; the UI can call `group_list` first if it wants to choose which group to remove manually.

### 4. New dataclasses: `MatterGroupInfo` and `GroupListResult`
- **Decision**: Added to `matter_server/common/models.py`. `MatterGroupInfo(group_id, group_name)` and `GroupListResult(node_id, endpoint, remaining_capacity, groups)`.
- **Rationale**: Typed response objects keep the API contract explicit and make serialization via the existing JSON helpers automatic.

## 2026-03-26: Keyset Lifecycle Management (Fix Keyset Leak)

### 1. `RemoveGroup`/`RemoveAllGroups` do NOT remove keysets (Matter spec)
- **Decision**: After every `group_remove` and `group_remove_all` call, immediately invoke `_cleanup_unused_keysets_on_node`, which reads `GroupKeyTable`, diffs against `GroupKeyMap` (active bindings), and calls `KeySetRemove` on every orphaned keyset (excluding IPK id=0).
- **Rationale**: This is a Matter spec constraint: the Groups cluster `RemoveGroup`/`RemoveAllGroups` commands only clear the group membership table. The keyset table (managed by Group Key Management cluster) is completely separate and must be cleaned manually. Without this, repeated add/remove cycles fill the 3-slot keyset table, causing `ResourceExhausted` on every subsequent `KeySetWrite`.

### 2. Cleanup-then-retry on ResourceExhausted in `_provision_group_keys_on_node`
- **Decision**: When `KeySetWrite` returns `ResourceExhausted`, the code now: (a) calls `_cleanup_unused_keysets_on_node`, (b) retries `KeySetWrite` if any slots were freed, (c) only falls back to keyset reuse if cleanup freed nothing or the retry still fails.
- **Rationale**: Previous behavior jumped straight to keyset reuse, which shares encryption keys across groups (weaker isolation). Cleanup-first gives the device a fresh slot and keeps each group on its own keyset when possible.

### 3. `_cleanup_unused_keysets_on_node` reads `GroupKeyTable`, not server state
- **Decision**: The cleanup helper reads `GroupKeyManagement.Attributes.GroupKeyTable` from the device to discover all provisioned keysets — it does NOT rely on `_group_key_store` as the source of truth for what's on the device.
- **Rationale**: The server's `_group_key_store` only tracks crypto material for groups the server created. Keysets installed by other controllers (e.g. during multi-fabric commissioning) are invisible to the server's local store but would still be found via `GroupKeyTable`. This approach correctly handles all keysets regardless of origin.
