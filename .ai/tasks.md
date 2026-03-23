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

## Backlog
- [ ] Add `discover` command to `scripts/cli_client.py`.
- [ ] Investigate why `discovery_updated` events are not appearing in the dashboard (optional).
