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

## Backlog
- [ ] Add `discover` command to `scripts/cli_client.py`.
- [ ] Investigate why `discovery_updated` events are not appearing in the dashboard (optional).
- [ ] Investigate mDNS/CASE session timeout for Node 27 (hardware/network issue — `CHIP Error 0x32: Timeout`). Node unreachable on mDNS; this is separate from group commands.
