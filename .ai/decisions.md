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

### Bug 4: Crash on startup when chip.json contains corrupted keysets from old code (Raspberry Pi deployment fix)
- **Decision**: Added `_cleanup_corrupted_keysets(storage_path, logger)` in `server.py`, called before `MatterDeviceController` is instantiated in `start()`. It reads `chip.json` directly, finds all non-IPK keyset entries (`f/X/k/Y` where Y != 0), removes them, and saves the file.
- **Rationale**: The buggy old code (1-item TLV array) left corrupted keyset entries in `chip.json`. On the next startup, `GroupDataProviderImpl.SetSingleIpkEpochKey` traverses the keyset linked list and hits the malformed TLV → `CHIP Error 0x00000026: Wrong TLV type` → server cannot start. By scrubbing these entries before `NewController()` is called, the C++ sees a clean linked list. The entries are recreated correctly by `MatterDeviceController.start()` via `_ensure_controller_group_keys`.
