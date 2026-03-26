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
- [x] Add `scan_ble_devices` API command: raw BLE scan using `bleak`, filters by MAC address, returns `BLEScanResult` with service UUIDs/data, is_matter flag, and decoded Matter discriminator/vendor/product IDs.
- [x] Add `commission_with_mac` API command: scans for device by MAC, auto-extracts discriminator from fff6 advertisement, commissions via existing `commission_ble` flow. No QR code needed.
- [x] Add Multi-Fabric Commissioning support: new `commission_on_commissioning_window` command + `fabric_label` parameter on all commissioning commands.
- [x] Fix `group_add` failures: added `timed_request_timeout_ms=5000` to `AddGroup` send_command, added timed-write support to `write_attribute` in `sdk.py` + `group_bind_key_set`, increased `group_add_key_set` timeout from 1000ms to 5000ms.
- [x] Fix `group_send_command` silent failures: fixed early-return guard for test group IDs (257+) and set `epochStartTime0=1` for non-test groups (satisfies Matter spec §11.2.6.1.1).

- [x] Refactor group management to be Matter spec-compliant: removed server-side group registry (`add_group`/`remove_group`/`get_groups`/`MatterGroupInfo`), removed auto `init_group_testing_data` at startup, added `Descriptor.ServerList` validation in `group_add`, simplified controller key injection (`_inject_controller_group_keys` replaces `_ensure_controller_group_keys` + `_overwrite_controller_keyset`).
- [x] Rewrite `docs/websockets_api.md` with full descriptions, parameter tables, and example responses for every command and event.
- [x] Fix `InteractionModelError: ResourceExhausted (0x89)` during `group_add` key provisioning: read device `GroupKeyMap` before writing, skip `KeySetWrite` if keyset already installed, fall back to reusing a server-managed keyset already on the device if the table is full. New helpers: `_get_node_group_key_map`, `_provision_group_keys_on_node`, `_is_resource_exhausted_err`.
- [x] Add `group_list` API command: calls `GetGroupMembership` + `ViewGroup` per group, returns `GroupListResult` with `remaining_capacity` and list of `{group_id, group_name}`. Live query — no server cache.
- [x] Add `group_remove_all` API command: sends `Groups.RemoveAllGroups` to the device endpoint.
- [x] Fix `group_add` group-table exhaustion: calls `GetGroupMembership` first; if `remaining_capacity == 0` and group not already a member, FIFO-evicts the oldest group before calling `AddGroup`.
- [x] Fix keyset leak: `group_remove` and `group_remove_all` now call `_cleanup_unused_keysets_on_node` after removing groups (`RemoveGroup`/`RemoveAllGroups` do not remove keysets per the Matter spec).
- [x] Add `_cleanup_unused_keysets_on_node`: reads `GroupKeyTable`, finds keyset IDs not referenced by `GroupKeyMap`, calls `KeySetRemove` on each. Returns number removed.
- [x] Fix keyset ResourceExhausted in `_provision_group_keys_on_node`: on `ResourceExhausted` from `KeySetWrite`, run cleanup + retry before falling back to keyset reuse.
- [x] Add controller-side keyset tracker (`_known_keysets_per_node`, persisted as `node_keysets`): records every `KeySetWrite` and confirmed keyset presence; used as fallback source for cleanup when device does not expose `GroupKeyTable` (e.g. Tapo).
- [x] Fix `_cleanup_unused_keysets_on_node` fallback: if `GroupKeyTable` read fails/empty, use `_known_keysets_per_node` as the keyset source; update tracker on each `KeySetRemove`.
- [x] Add `group_debug_info` API command: returns live `GroupKeyMap`, controller-tracked keysets, inferred orphaned keysets, and group key store entries for a node.

## Backlog
- [ ] Add `discover` command to `scripts/cli_client.py`.
- [ ] Investigate why `discovery_updated` events are not appearing in the dashboard (optional).
- [ ] Investigate mDNS/CASE session timeout for Node 27 (hardware/network issue — `CHIP Error 0x32: Timeout`). Node unreachable on mDNS; this is separate from group commands.
