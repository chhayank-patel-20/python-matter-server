# Project Tasks

## Completed
- [x] Fix Discovery API (TypeError in `sdk.py`).
- [x] Align command naming between server and dashboard (`discover_commissionable_nodes`).
- [x] Update `docs/websockets_api.md` with corrected command and error notes.
- [x] Initialize `.ai/` project memory structure.
- [x] Fix `CHIP Error 0x000000AC` in `group_send_command` via automatic `init_group_testing_data`.
- [x] Add server-side group registry and APIs (`get_groups`, `add_group`, `remove_group`).
- [x] Include groups in `get_diagnostics`.
- [x] Implement automatic retry for `0xAC` in `group_send_command`.
- [x] Add node-side group key management APIs (`group_add_key_set`, `group_bind_key_set`).
- [x] Fix critical group key derivation bug: TLV injection was storing raw epoch key instead of HKDF-derived encryption key + wrong array size (kEpochKeysMax=3) + wrong hash. Added `_derive_group_encryption_key`, `_derive_group_session_id`, and `_overwrite_controller_keyset` (startup migration).
- [x] Fix Raspberry Pi startup crash (CHIP Error 0x00000026: Wrong TLV type): root cause was Python TLVWriter writing signed integers for all int values, but C++ expects unsigned. Fixed by using `tlv_uint()` everywhere in TLV writes. Widened cleanup to delete all group-related KVS entries (FabricData, GroupInfo, KeyMapData, keysets) before NewController() runs.
- [x] Fix ruff TC002 lint error: move `chip.storage.PersistentStorage` import into `TYPE_CHECKING` block in `server.py`.
- [x] Add startup fallback: wrap `_cleanup_corrupted_group_storage()` in try/except so unexpected errors log a warning instead of crashing the server.
- [x] Fix `group_send_command` 0xAC ordering bug: `init_group_testing_data()` was overwriting FabricData after custom key injection, orphaning group 1 entries. Fixed by calling `init_group_testing_data()` first in `start()`.
- [x] Fix "Required network information not provided" error during BLE commissioning: updated `commission_ble` in `sdk.py` to use specialized `CommissionWiFi` and `CommissionThread` methods instead of `ConnectBLE` when network credentials are provided.

## Backlog
- [ ] Add `discover` command to `scripts/cli_client.py`.
- [ ] Investigate why `discovery_updated` events are not appearing in the dashboard (optional).
- [ ] Investigate mDNS/CASE session timeout for Node 27 (hardware/network issue — `CHIP Error 0x32: Timeout`). Node unreachable on mDNS; this is separate from group commands.
