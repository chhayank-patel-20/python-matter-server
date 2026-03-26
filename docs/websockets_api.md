# WebSocket API Documentation

This document describes the WebSocket API for the Python Matter Server.

---

## Connection

When a client connects, the server immediately pushes a `server_info` message (no command needed).

**Server Info message (pushed on connect):**

```json
{
  "fabric_id": 1,
  "compressed_fabric_id": 3735928559,
  "schema_version": 6,
  "min_supported_schema_version": 1,
  "sdk_version": "1.0.0",
  "wifi_credentials_set": true,
  "thread_credentials_set": false,
  "bluetooth_enabled": true
}
```

| Field | Type | Description |
|---|---|---|
| `fabric_id` | int | Fabric ID of this controller |
| `compressed_fabric_id` | int | Compressed fabric ID (64-bit) |
| `schema_version` | int | Current API schema version |
| `min_supported_schema_version` | int | Minimum schema version this server accepts |
| `sdk_version` | str | Matter SDK version string |
| `wifi_credentials_set` | bool | Whether WiFi credentials have been configured |
| `thread_credentials_set` | bool | Whether Thread credentials have been configured |
| `bluetooth_enabled` | bool | Whether BLE is available on this host |

---

## Message Format

All commands follow this structure:

```json
{
  "message_id": "unique-string",
  "command": "command_name",
  "args": {}
}
```

All responses follow this structure:

```json
{
  "message_id": "unique-string",
  "result": null
}
```

On error, the response is:

```json
{
  "message_id": "unique-string",
  "error_code": "InvalidArguments",
  "details": "Human-readable error description"
}
```

---

## Commands

### Server Information

---

**`server_info`** — Get server version and status

```json
{ "message_id": "1", "command": "server_info" }
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "fabric_id": 1,
    "compressed_fabric_id": 3735928559,
    "schema_version": 6,
    "min_supported_schema_version": 1,
    "sdk_version": "1.0.0",
    "wifi_credentials_set": true,
    "thread_credentials_set": false,
    "bluetooth_enabled": true
  }
}
```

---

**`diagnostics`** — Full server dump for debugging

Returns the server info, all commissioned nodes, and the last 25 server-side events.

```json
{ "message_id": "1", "command": "diagnostics" }
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "info": { "fabric_id": 1, "...": "..." },
    "nodes": [ { "node_id": 1, "available": true, "...": "..." } ],
    "events": []
  }
}
```

---

**`get_vendor_names`** — Resolve vendor IDs to vendor names

Fetches from the CSA vendor database. Use `filter_vendors` to limit the lookup.

```json
{
  "message_id": "1",
  "command": "get_vendor_names",
  "args": {
    "filter_vendors": [4937, 4151]
  }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "4937": "TP-Link",
    "4151": "Tapo"
  }
}
```

---

### Commissioning

---

**`scan_ble_devices`** — Scan for nearby BLE devices

Returns raw advertisement data for all nearby BLE devices. Optionally filter by MAC address.
Use a `timeout` of 20–30 seconds for reliable results (devices advertise periodically).

> A Matter device only includes UUID `0000fff6-0000-1000-8000-00805f9b34fb` in its advertisement
> when a **commissioning window is open** (button press or factory reset). When `is_matter` is
> `false`, the device cannot be commissioned — open the commissioning window first.

```json
{
  "message_id": "1",
  "command": "scan_ble_devices",
  "args": {
    "mac_address": "50:3D:D1:C0:5B:AB",
    "timeout": 30.0
  }
}
```

| Arg | Required | Default | Description |
|---|---|---|---|
| `mac_address` | No | `null` | Filter to a specific MAC. Omit to return all devices. |
| `timeout` | No | `10.0` | Scan duration in seconds. Use 20–30 for reliability. |

**Response (device in commissioning mode):**
```json
{
  "message_id": "1",
  "result": [
    {
      "address": "50:3D:D1:C0:5B:AB",
      "name": "P210M_P3H6ucHr",
      "rssi": -69,
      "service_uuids": [
        "00008641-0000-1000-8000-00805f9b34fb",
        "0000fff6-0000-1000-8000-00805f9b34fb"
      ],
      "service_data": {
        "0000fff6-0000-1000-8000-00805f9b34fb": "00 00 04 92 13 00 00 BF"
      },
      "manufacturer_data": {},
      "is_matter": true,
      "matter_discriminator": 0,
      "matter_vendor_id": 37396,
      "matter_product_id": 1170
    }
  ]
}
```

**Response (device NOT in commissioning mode):**
```json
{
  "message_id": "1",
  "result": [
    {
      "address": "50:3D:D1:C0:5B:AB",
      "name": "P210M_P3H6ucHr",
      "rssi": -69,
      "service_uuids": ["00008641-0000-1000-8000-00805f9b34fb"],
      "service_data": {},
      "manufacturer_data": {},
      "is_matter": false,
      "matter_discriminator": null,
      "matter_vendor_id": null,
      "matter_product_id": null
    }
  ]
}
```

---

**`set_wifi_credentials`** — Set WiFi credentials for commissioning

Must be called before commissioning a WiFi-based device.

```json
{
  "message_id": "1",
  "command": "set_wifi_credentials",
  "args": {
    "ssid": "MyNetwork",
    "credentials": "MyPassword"
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`set_thread_dataset`** — Set Thread operational dataset for commissioning

Must be called before commissioning a Thread-based device.

```json
{
  "message_id": "1",
  "command": "set_thread_dataset",
  "args": {
    "dataset": "0e080000000000010000000300001235..."
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`set_default_fabric_label`** — Set a default fabric label applied after every commissioning

```json
{
  "message_id": "1",
  "command": "set_default_fabric_label",
  "args": {
    "label": "MyHome"
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`commission_with_code`** — Commission a device using a QR or manual pairing code

Supports both QR-code syntax (`MT:...`) and 11-digit manual pairing codes.

For WiFi or Thread devices, set credentials first with `set_wifi_credentials` or
`set_thread_dataset`. The server automatically uses the BLE commissioning path when
a discriminator can be extracted from the setup code.

```json
{
  "message_id": "2",
  "command": "commission_with_code",
  "args": {
    "code": "MT:Y.ABCDEFG123456789",
    "fabric_label": "MyServer"
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `code` | Yes | QR code (`MT:...`) or 11-digit manual pairing code |
| `fabric_label` | No | Label stored on the device for this fabric (visible in `get_fabrics`) |

**Response:** Full `MatterNodeData` of the newly commissioned node.

```json
{
  "message_id": "2",
  "result": {
    "node_id": 3,
    "date_commissioned": "2026-03-26T10:00:00",
    "last_interview": "2026-03-26T10:00:05",
    "interview_version": 1,
    "available": true,
    "is_bridge": false,
    "attributes": { "0/40/3": "Tapo", "1/6/0": false }
  }
}
```

---

**`commission_with_mac`** — Commission a device by BLE MAC address and PIN code

No QR code needed. The server scans for the device by MAC, extracts the discriminator
from the Matter BLE advertisement (`fff6` service data), and commissions using any
pre-set WiFi/Thread credentials.

**Requirements:**
- Device must be in commissioning mode (`is_matter: true` in `scan_ble_devices`)
- WiFi/Thread credentials must be set beforehand

```json
{
  "message_id": "2",
  "command": "commission_with_mac",
  "args": {
    "mac_address": "50:3D:D1:C0:5B:AB",
    "setup_pin_code": 12345678,
    "scan_timeout": 30.0
  }
}
```

| Arg | Required | Default | Description |
|---|---|---|---|
| `mac_address` | Yes | — | BLE MAC address of the device |
| `setup_pin_code` | Yes | — | Setup PIN code from device label |
| `scan_timeout` | No | `10.0` | BLE scan duration in seconds |

**Response:** Full `MatterNodeData` of the commissioned node (same shape as `commission_with_code`).

**Errors:**
- Device not found in BLE range
- Device is not in commissioning mode (no `fff6` UUID — open commissioning window first)
- BLE commissioning failure

**Typical workflow:**
1. `scan_ble_devices` → confirm `is_matter: true`
2. `set_wifi_credentials` → set network password
3. `commission_with_mac` → device commissioned and returned

---

**`commission_on_network`** — Commission a device already on the network

```json
{
  "message_id": "2",
  "command": "commission_on_network",
  "args": {
    "setup_pin_code": 12345678,
    "filter_type": 0,
    "filter": null,
    "fabric_label": "MyServer"
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `setup_pin_code` | Yes | Setup PIN code |
| `filter_type` | No | `FilterType` enum value (0=NONE, 2=LONG_DISCRIMINATOR, etc.) |
| `filter` | No | Filter value matching `filter_type` |
| `fabric_label` | No | Label for this fabric on the device |

**Response:** Full `MatterNodeData` of the commissioned node.

---

**`discover_commissionable_nodes`** — Discover devices available for commissioning

Returns the current list of discovered commissionable nodes (via BLE and mDNS).
New discoveries are also pushed as `discovery_updated` events.

```json
{ "message_id": "1", "command": "discover_commissionable_nodes" }
```

**Response:**
```json
{
  "message_id": "1",
  "result": [
    {
      "instance_name": "1A2B3C4D5E6F7A8B",
      "host_name": "E45F01234567.local.",
      "port": 5540,
      "long_discriminator": 3840,
      "vendor_id": 4151,
      "product_id": 131,
      "commissioning_mode": 1,
      "device_type": 257,
      "device_name": "Tapo P210M",
      "pairing_instruction": "",
      "pairing_hint": 33,
      "addresses": ["192.168.1.42", "fe80::e65f:1ff:fe23:4567"]
    }
  ]
}
```

---

**`open_commissioning_window`** — Open a commissioning window on an already-commissioned device

Used for **Multi-Fabric Commissioning (Step 1)**. Returns the pairing codes needed by a
second controller to add this device to their fabric.

```json
{
  "message_id": "2",
  "command": "open_commissioning_window",
  "args": {
    "node_id": 1,
    "timeout": 300,
    "iteration": 1000
  }
}
```

| Arg | Required | Default | Description |
|---|---|---|---|
| `node_id` | Yes | — | Node whose commissioning window to open |
| `timeout` | No | `300` | Window open duration in seconds |
| `iteration` | No | `1000` | PBKDF2 iteration count (higher = slower brute-force) |

**Response:**
```json
{
  "message_id": "2",
  "result": {
    "setup_pin_code": 98765432,
    "setup_manual_code": "35325335079",
    "setup_qr_code": "MT:Y.ABCDEFG123456789",
    "discriminator": 3840
  }
}
```

---

**`commission_on_commissioning_window`** — Add a device to this fabric via an open commissioning window

Used for **Multi-Fabric Commissioning (Step 2)**. Use the `setup_pin_code` and
`discriminator` returned by another controller's `open_commissioning_window` call.

> **Multi-Fabric flow:**
> 1. Device is already on **Fabric A** (another controller).
> 2. Fabric A calls `open_commissioning_window(node_id)` → shares `setup_pin_code` and `discriminator`.
> 3. You call `commission_on_commissioning_window` → device is now on **both fabrics**.
>
> To share **your** device: call `open_commissioning_window` on your node and give the codes to the other controller.

```json
{
  "message_id": "2",
  "command": "commission_on_commissioning_window",
  "args": {
    "setup_pin_code": 98765432,
    "discriminator": 3840,
    "ip_addr": null,
    "fabric_label": "MyServer"
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `setup_pin_code` | Yes | From the other controller's `open_commissioning_window` result |
| `discriminator` | Yes | From the other controller's `open_commissioning_window` result |
| `ip_addr` | No | Direct IP to skip mDNS discovery (use when IP is known) |
| `fabric_label` | No | Label to identify this fabric on the device |

**Response:** Full `MatterNodeData` of the commissioned node.

---

**`get_fabrics`** — List all fabrics a node belongs to

```json
{
  "message_id": "1",
  "command": "get_fabrics",
  "args": { "node_id": 1 }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": [
    {
      "fabric_index": 1,
      "root_public_key": "...",
      "vendor_id": 4937,
      "fabric_id": 1,
      "node_id": 1,
      "label": "MyServer"
    },
    {
      "fabric_index": 2,
      "root_public_key": "...",
      "vendor_id": 4937,
      "fabric_id": 2,
      "node_id": 1,
      "label": "HomeAssistant"
    }
  ]
}
```

---

**`remove_fabric`** — Remove a specific fabric from a node

```json
{
  "message_id": "1",
  "command": "remove_fabric",
  "args": {
    "node_id": 1,
    "fabric_index": 2
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`update_fabric_label`** — Update the fabric label on an already-commissioned node

```json
{
  "message_id": "1",
  "command": "update_fabric_label",
  "args": {
    "node_id": 1,
    "label": "LivingRoom"
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

### Node Management

---

**`get_nodes`** — Get all commissioned nodes

```json
{ "message_id": "2", "command": "get_nodes" }
```

**Response:**
```json
{
  "message_id": "2",
  "result": [
    {
      "node_id": 1,
      "date_commissioned": "2026-03-20T09:00:00",
      "last_interview": "2026-03-26T08:00:00",
      "interview_version": 3,
      "available": true,
      "is_bridge": false,
      "attributes": {
        "0/40/3": "Tapo",
        "0/40/4": "P210M",
        "1/6/0": false
      }
    }
  ]
}
```

---

**`get_node`** — Get a single node by ID

```json
{
  "message_id": "2",
  "command": "get_node",
  "args": { "node_id": 1 }
}
```

**Response:** Single `MatterNodeData` object (same shape as items in `get_nodes`).

---

**`start_listening`** — Subscribe to all node events

After sending this command, the server dumps all existing nodes in the response and then
continuously pushes `attribute_updated`, `node_added`, `node_removed`, and other events.

```json
{ "message_id": "3", "command": "start_listening" }
```

**Response:**
```json
{
  "message_id": "3",
  "result": {
    "nodes": [
      { "node_id": 1, "available": true, "...": "..." }
    ]
  }
}
```

---

**`interview_node`** — Re-interview a node (read all attributes fresh)

Triggers a full attribute read and updates the server's cached node data.

```json
{
  "message_id": "1",
  "command": "interview_node",
  "args": { "node_id": 1 }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`remove_node`** — Remove a node from the fabric

Sends `RemoveFabric` to the device and removes it from the server.

```json
{
  "message_id": "1",
  "command": "remove_node",
  "args": { "node_id": 1 }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`ping_node`** — Ping a node by IP address

```json
{
  "message_id": "1",
  "command": "ping_node",
  "args": {
    "node_id": 1,
    "attempts": 1
  }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "192.168.1.42": true,
    "fe80::e65f:1ff:fe23:4567": false
  }
}
```

---

**`get_node_ip_addresses`** — Get known IP addresses for a node

```json
{
  "message_id": "1",
  "command": "get_node_ip_addresses",
  "args": {
    "node_id": 1,
    "prefer_cache": false,
    "scoped": false
  }
}
```

| Arg | Required | Default | Description |
|---|---|---|---|
| `node_id` | Yes | — | Target node |
| `prefer_cache` | No | `false` | Return cached addresses without resolving mDNS |
| `scoped` | No | `false` | Return link-local addresses with interface scope (e.g. `fe80::1%eth0`) |

**Response:**
```json
{
  "message_id": "1",
  "result": ["192.168.1.42", "fe80::e65f:1ff:fe23:4567"]
}
```

---

### Attributes and Commands

---

**`read_attribute`** — Read a specific attribute from a node

Attribute path format: `ENDPOINT_ID/CLUSTER_ID/ATTRIBUTE_ID`

```json
{
  "message_id": "read1",
  "command": "read_attribute",
  "args": {
    "node_id": 1,
    "attribute_path": "1/6/0"
  }
}
```

**Response:**
```json
{
  "message_id": "read1",
  "result": false
}
```

Common attribute paths:

| Path | Description |
|---|---|
| `1/6/0` | OnOff cluster, OnOff attribute (endpoint 1) |
| `1/8/0` | LevelControl cluster, CurrentLevel |
| `1/768/1` | ColorControl cluster, CurrentHue |
| `0/40/3` | BasicInformation, VendorName |
| `0/40/5` | BasicInformation, NodeLabel |

---

**`write_attribute`** — Write a value to a node attribute

```json
{
  "message_id": "write1",
  "command": "write_attribute",
  "args": {
    "node_id": 1,
    "attribute_path": "1/6/16385",
    "value": 100
  }
}
```

**Response:** `{ "message_id": "write1", "result": null }`

---

**`device_command`** — Send a cluster command to a node endpoint

```json
{
  "message_id": "cmd1",
  "command": "device_command",
  "args": {
    "node_id": 1,
    "endpoint_id": 1,
    "cluster_id": 6,
    "command_name": "On",
    "payload": {}
  }
}
```

**Response:** Command response payload (or `null` if the command has no response).

```json
{ "message_id": "cmd1", "result": null }
```

**Example — move brightness to 50%:**
```json
{
  "message_id": "cmd2",
  "command": "device_command",
  "args": {
    "node_id": 1,
    "endpoint_id": 1,
    "cluster_id": 8,
    "command_name": "MoveToLevelWithOnOff",
    "payload": { "level": 128, "transitionTime": 0 }
  }
}
```

---

**`set_acl_entry`** — Set Access Control List entries on a node

```json
{
  "message_id": "1",
  "command": "set_acl_entry",
  "args": {
    "node_id": 1,
    "entry": []
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`set_node_binding`** — Set bindings on a node endpoint

```json
{
  "message_id": "1",
  "command": "set_node_binding",
  "args": {
    "node_id": 1,
    "endpoint": 1,
    "bindings": []
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

### Groups and Bindings

Groups in Matter are managed entirely on the **device** — the server does not maintain a
group registry. Group membership is stored on each endpoint via the Groups cluster and
is queried directly from the device with `group_list` or `group_get_membership`.

**Server-side state (what the server does persist):**
- `group_keys` — one entry per group ID: the epoch key and keyset ID used to encrypt groupcast frames. Required so the controller can send multicast after a restart without re-running `group_add` on every node.
- `node_keysets` — per-node set of keyset IDs the server has explicitly written via `KeySetWrite`. Used as a fallback source for keyset cleanup on devices that do not expose `GroupKeyManagement.Attributes.GroupKeyTable` (e.g. Tapo).

Everything else (group membership, group names, keyset bindings) lives on the device.

---

**`group_add`** — Add a node endpoint to a group

The server:
1. Validates the endpoint supports the Groups cluster via `Descriptor.ServerList`
2. Generates a random 128-bit epoch key for the group (first time only) and injects it into the controller's `GroupDataProvider`
3. Calls `Groups.GetGroupMembership` to check the current group table and remaining capacity
4. If the table is **full** (`remaining_capacity == 0`) and the group is not already a member, the **oldest group is removed (FIFO)** to free a slot before proceeding
5. Reads the device's `GroupKeyManagement.GroupKeyMap` to determine which keysets are already installed
6. Calls `GroupKeyManagement.KeySetWrite` only if the keyset is **not** already on the device (avoids redundant writes and prevents `ResourceExhausted`)
7. If the device keyset table is full (`ResourceExhausted`), reuses a server-managed keyset already present on the device
8. Updates the device's `GroupKeyMap` to bind the group ID to the keyset
9. Sends `Groups.AddGroup` to the device endpoint

Call this once per endpoint/node you want to add to the group. Group membership is stored
on the device — not on the server.

```json
{
  "message_id": "1",
  "command": "group_add",
  "args": {
    "node_id": 1,
    "endpoint": 1,
    "group_id": 100,
    "group_name": "Living Room Lights"
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `node_id` | Yes | Node to add to the group |
| `endpoint` | Yes | Endpoint on that node (must support Groups cluster) |
| `group_id` | Yes | Group ID (1–65527). Shared across all members. |
| `group_name` | Yes | Human-readable name stored on the device (max 16 chars) |

**Response:** `{ "message_id": "1", "result": null }`

**Errors:**
- `InvalidArguments` — endpoint does not support the Groups cluster
- `InvalidArguments` — group table is reported full but `GetGroupMembership` returned no existing groups (device in unexpected state)
- `InvalidArguments` — device keyset table is full even after orphan cleanup and no server-managed keyset is already installed on the device; call `group_remove` or `group_remove_all` (which also clean up keysets) then retry

> **Automatic FIFO eviction:** If `GetGroupMembership` reports `remaining_capacity == 0`, `group_add` automatically removes the oldest group on that endpoint before adding the new one. Use `group_list` first if you want to choose which group to remove manually.
>
> **Automatic keyset cleanup on ResourceExhausted:** If `KeySetWrite` fails with `ResourceExhausted`, the server calls `KeySetRemove` on all orphaned keysets and retries before falling back to keyset reuse. Orphaned keysets are discovered via `GroupKeyTable` if the device exposes it; otherwise the server falls back to its own `node_keysets` tracker.
>
> **Keyset reuse:** Devices typically support only 3 group keysets. `group_add` reuses existing keysets across multiple groups so you can manage more groups than the keyset limit.

**Typical workflow:**
```
group_add(node_id=1, endpoint=1, group_id=100, group_name="Lights")
group_add(node_id=2, endpoint=1, group_id=100, group_name="Lights")
group_add(node_id=3, endpoint=1, group_id=100, group_name="Lights")
→ group_send_command(group_id=100, cluster_id=6, command_name="On", payload={})
```

---

**`group_remove`** — Remove a node endpoint from a group

Sends `Groups.RemoveGroup` to the device, then automatically removes any keysets that are no longer referenced by any group on that node.

> **Matter spec note:** `RemoveGroup` clears the group membership entry but does **not** remove the associated keyset. The server calls `KeySetRemove` on any keyset that is no longer referenced by a group binding. Orphaned keysets are discovered via `GroupKeyTable` first; if unavailable, the server falls back to its `node_keysets` tracker.

```json
{
  "message_id": "1",
  "command": "group_remove",
  "args": {
    "node_id": 1,
    "endpoint": 1,
    "group_id": 100
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`group_remove_all`** — Remove all groups from a node endpoint

Sends `Groups.RemoveAllGroups` to the device, then automatically removes all orphaned keysets.

> **Matter spec note:** `RemoveAllGroups` clears the group table but does **not** remove keysets. The server tries to read `GroupKeyTable` to discover provisioned keysets; if the device does not expose it (e.g. Tapo), it falls back to the controller-side keyset tracker. It then calls `KeySetRemove` on every keyset no longer referenced by a group binding. After this call the node's keyset slots are fully reclaimed.

```json
{
  "message_id": "1",
  "command": "group_remove_all",
  "args": {
    "node_id": 1,
    "endpoint": 1
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`group_list`** — List all groups on a node endpoint with names and remaining capacity

Calls `Groups.GetGroupMembership` (for IDs and remaining capacity) then `Groups.ViewGroup` for each group to fetch its name. All data comes from the device — no server-side cache is used.

```json
{
  "message_id": "1",
  "command": "group_list",
  "args": {
    "node_id": 1,
    "endpoint": 1
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `node_id` | Yes | Target node |
| `endpoint` | Yes | Target endpoint |

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "node_id": 1,
    "endpoint": 1,
    "remaining_capacity": 2,
    "groups": [
      { "group_id": 100, "group_name": "Living Room Lights" },
      { "group_id": 200, "group_name": "Kitchen" }
    ]
  }
}
```

| Field | Type | Description |
|---|---|---|
| `node_id` | int | Node ID echoed from request |
| `endpoint` | int | Endpoint echoed from request |
| `remaining_capacity` | int \| null | How many more groups can be added on this endpoint. `null` means the device did not report a capacity. |
| `groups` | array | List of group objects currently bound to this endpoint |
| `groups[].group_id` | int | Group ID |
| `groups[].group_name` | str \| null | Name stored on device. `null` if `ViewGroup` failed or returned no name. |

> **Typical UI workflow:**
> ```
> group_list(node_id=1, endpoint=1)
> → show groups + remaining_capacity to user
> → user picks a group to delete → group_remove(...)
> → user adds a new group → group_add(...)
> ```

---

**`group_get_membership`** — Query which groups an endpoint belongs to

Sends `Groups.GetGroupMembership` to the device. Returns live data from the device — the
server does not cache group membership.

```json
{
  "message_id": "1",
  "command": "group_get_membership",
  "args": {
    "node_id": 1,
    "endpoint": 1
  }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": [100, 200, 300]
}
```

The result is the list of group IDs this endpoint currently belongs to.

---

**`group_send_command`** — Send a command to a group using Matter multicast (groupcast)

The CHIP controller sends a single encrypted multicast frame addressed to the group ID.
No per-node unicast loop is used. All nodes that are members of the group and have matching
keys will process the command simultaneously.

The group must have at least one endpoint added via `group_add` so that the controller has
the encryption keys for that group ID.

```json
{
  "message_id": "1",
  "command": "group_send_command",
  "args": {
    "group_id": 100,
    "cluster_id": 6,
    "command_name": "On",
    "payload": {}
  }
}
```

| Arg | Required | Description |
|---|---|---|
| `group_id` | Yes | Target group ID |
| `cluster_id` | Yes | Matter cluster ID (e.g. 6 = OnOff, 8 = LevelControl) |
| `command_name` | Yes | Command name as a string (e.g. `"On"`, `"MoveToLevel"`) |
| `payload` | Yes | Command arguments as a JSON object. Use `{}` for no-argument commands. |

**Response:** `{ "message_id": "1", "result": null }`

> `group_send_command` is fire-and-forget — Matter groupcast does not have acknowledgements.
> There is no confirmation that individual nodes received or executed the command.

**Common Errors:**
- `CHIP Error 0xAC (Internal Error)` — The controller lacks encryption keys for this group ID. Call `group_add` first to provision the controller and nodes. If keys were orphaned (e.g. after calling `init_group_testing_data`), the server automatically re-injects them and retries once.
- `CHIP Error 0x32 (Timeout)` — A CASE session could not be established with a node (mDNS lookup failed or device is offline). This does not affect groupcast delivery to other online nodes.

---

**`group_debug_info`** — Raw group key state dump for a node

Returns the device's live `GroupKeyMap`, the controller-tracked keysets for the node, and the controller's inferred list of orphaned keysets. Useful for diagnosing groupcast failures and keyset exhaustion on devices that do not expose `GroupKeyTable`.

```json
{
  "message_id": "1",
  "command": "group_debug_info",
  "args": { "node_id": 1 }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "node_id": 1,
    "group_key_map": [
      { "group_id": 100, "keyset_id": 101 },
      { "group_id": 200, "keyset_id": 101 }
    ],
    "controller_tracked_keysets": [101],
    "inferred_orphaned_keysets": [],
    "group_key_store_entries": [
      { "group_id": 100, "keyset_id": 101 },
      { "group_id": 200, "keyset_id": 101 }
    ]
  }
}
```

| Field | Description |
|---|---|
| `group_key_map` | Live read of `GroupKeyManagement.GroupKeyMap` from the device |
| `controller_tracked_keysets` | Keyset IDs the server has written to this node via `KeySetWrite` |
| `inferred_orphaned_keysets` | `controller_tracked - referenced_by_map - {0}` — these will be removed on next cleanup |
| `group_key_store_entries` | The server's crypto store — group→keyset mappings used for groupcast encryption |

---

**`group_add_key_set`** — Manually install a group key set on a node

Sends `GroupKeyManagement.KeySetWrite` to the node's endpoint 0.

> **Advanced use only.** `group_add` handles key provisioning automatically, including skipping this call if the keyset is already on the device. Call this directly only if you need to install a specific keyset outside of the `group_add` workflow.

```json
{
  "message_id": "1",
  "command": "group_add_key_set",
  "args": {
    "node_id": 1,
    "keyset_id": 100,
    "key_hex": "0102030405060708090a0b0c0d0e0f10"
  }
}
```

| Arg | Required | Default | Description |
|---|---|---|---|
| `node_id` | Yes | — | Target node |
| `keyset_id` | Yes | — | Keyset ID (1–65534) |
| `key_hex` | No | `"0102030405060708090a0b0c0d0e0f10"` | 16-byte epoch key as hex |

**Response:** `{ "message_id": "1", "result": null }`

---

**`group_bind_key_set`** — Manually bind a group ID to a keyset on a node

Writes to `GroupKeyManagement.GroupKeyMap` (attribute 0) on endpoint 0.

> **Advanced use only.** `group_add` updates the `GroupKeyMap` automatically after key provisioning. Call this directly only if you need to rebind a group to a different keyset outside of the `group_add` workflow.

```json
{
  "message_id": "1",
  "command": "group_bind_key_set",
  "args": {
    "node_id": 1,
    "group_id": 100,
    "keyset_id": 100
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`init_group_testing_data`** — Populate controller with hardcoded test group keys

Initializes the controller's `GroupDataProvider` with test keys for group IDs **257** and
**258** only. Use in development/testing environments with test devices.

> **Warning:** Do not call this after creating production groups. It rewrites the
> controller's group-key linked list and will orphan custom group keys, causing
> `SendGroupCommand` to fail with `0xAC` for any custom group IDs.

```json
{ "message_id": "1", "command": "init_group_testing_data" }
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`binding_add`** — Add a binding to a node endpoint

```json
{
  "message_id": "1",
  "command": "binding_add",
  "args": {
    "node_id": 1,
    "endpoint_id": 1,
    "target_node_id": 2,
    "target_endpoint_id": 1,
    "cluster_id": 6
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

**`binding_remove`** — Remove a binding from a node endpoint

```json
{
  "message_id": "1",
  "command": "binding_remove",
  "args": {
    "node_id": 1,
    "endpoint_id": 1,
    "target_node_id": 2,
    "target_endpoint_id": 1,
    "cluster_id": 6
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

### OTA Updates

---

**`check_node_update`** — Check if a firmware update is available for a node

```json
{
  "message_id": "1",
  "command": "check_node_update",
  "args": { "node_id": 1 }
}
```

**Response:**
```json
{
  "message_id": "1",
  "result": {
    "software_version": 2,
    "software_version_string": "2.0.0",
    "update_token": "...",
    "min_applicable_software_version": 0,
    "max_applicable_software_version": 1
  }
}
```

Returns `null` if no update is available.

---

**`update_node`** — Start an OTA firmware update on a node

```json
{
  "message_id": "1",
  "command": "update_node",
  "args": {
    "node_id": 1,
    "software_version": 2
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

### Miscellaneous

---

**`import_test_node`** — Import test node(s) from a diagnostics dump

Accepts a Home Assistant or Matter server diagnostics JSON dump. Useful for testing
without physical hardware.

```json
{
  "message_id": "1",
  "command": "import_test_node",
  "args": {
    "dump": "{\"data\": {\"node\": {...}}}"
  }
}
```

**Response:** `{ "message_id": "1", "result": null }`

---

## WebSocket Events

After sending `start_listening`, the server pushes events as they occur.
Each event has the shape `{ "event": "event_name", "data": ... }`.

---

**`node_added`** — A new node was commissioned and added to the fabric

```json
{
  "event": "node_added",
  "data": {
    "node_id": 4,
    "date_commissioned": "2026-03-26T10:00:00",
    "last_interview": "2026-03-26T10:00:05",
    "interview_version": 1,
    "available": true,
    "is_bridge": false,
    "attributes": { "0/40/3": "Tapo", "1/6/0": false }
  }
}
```

---

**`node_updated`** — A node's information was updated (e.g. after re-interview)

```json
{
  "event": "node_updated",
  "data": {
    "node_id": 1,
    "available": true,
    "attributes": { "0/40/3": "Tapo", "1/6/0": true }
  }
}
```

---

**`node_removed`** — A node was removed from the fabric

```json
{
  "event": "node_removed",
  "data": 1
}
```

`data` is the `node_id` of the removed node.

---

**`attribute_updated`** — An attribute value changed on a node

```json
{
  "event": "attribute_updated",
  "data": [1, "1/6/0", true]
}
```

`data` is `[node_id, attribute_path, new_value]`.

---

**`node_event`** — A cluster event was fired on a node

```json
{
  "event": "node_event",
  "data": {
    "node_id": 1,
    "endpoint_id": 1,
    "cluster_id": 6,
    "event_id": 0,
    "event_number": 42,
    "priority": 1,
    "timestamp": 1711446000000,
    "timestamp_type": 0,
    "data": {}
  }
}
```

---

**`discovery_updated`** — A commissionable node was discovered or disappeared from mDNS/BLE

New discovery:
```json
{
  "event": "discovery_updated",
  "data": {
    "instance_name": "1A2B3C4D5E6F7A8B",
    "host_name": "E45F01234567.local.",
    "port": 5540,
    "long_discriminator": 3840,
    "vendor_id": 4151,
    "product_id": 131,
    "commissioning_mode": 1,
    "device_type": 257,
    "device_name": "Tapo P210M",
    "pairing_instruction": "",
    "pairing_hint": 33,
    "addresses": ["192.168.1.42"]
  }
}
```

Node disappeared:
```json
{
  "event": "discovery_updated",
  "data": {
    "name": "1A2B3C4D5E6F7A8B._matterc._udp.local.",
    "removed": true
  }
}
```

---

**`commissioning_progress`** — Progress update during commissioning

```json
{
  "event": "commissioning_progress",
  "data": {
    "node_id": 4,
    "stage": "started"
  }
}
```

`stage` values: `"started"`, `"commissioning"`, `"interview"`, `"done"`, `"failed"`

---

**`endpoint_added`** — An endpoint was added to a node (e.g. bridge child device added)

```json
{
  "event": "endpoint_added",
  "data": {
    "node_id": 1,
    "endpoint_id": 3
  }
}
```

---

**`endpoint_removed`** — An endpoint was removed from a node

```json
{
  "event": "endpoint_removed",
  "data": {
    "node_id": 1,
    "endpoint_id": 3
  }
}
```

---

**`server_info_updated`** — Server state changed (e.g. WiFi credentials updated)

```json
{
  "event": "server_info_updated",
  "data": {
    "wifi_credentials_set": true,
    "thread_credentials_set": false
  }
}
```

---

**`server_shutdown`** — Server is shutting down

```json
{
  "event": "server_shutdown",
  "data": null
}
```

---

## Python Client Example

```python
import asyncio
import json
import websockets

async def turn_on_switch():
    uri = "ws://localhost:5580/ws"
    async with websockets.connect(uri) as ws:
        # Wait for server_info push
        server_info = json.loads(await ws.recv())
        print("Connected:", server_info)

        # Start listening to receive events
        await ws.send(json.dumps({"message_id": "1", "command": "start_listening"}))
        response = json.loads(await ws.recv())
        nodes = response["result"]["nodes"]
        print(f"Commissioned nodes: {[n['node_id'] for n in nodes]}")

        # Turn on a switch (OnOff cluster, endpoint 1)
        await ws.send(json.dumps({
            "message_id": "cmd1",
            "command": "device_command",
            "args": {
                "node_id": 1,
                "endpoint_id": 1,
                "cluster_id": 6,
                "command_name": "On",
                "payload": {}
            }
        }))
        result = json.loads(await ws.recv())
        print("Command result:", result)

asyncio.run(turn_on_switch())
```

**Using the built-in Python SDK types:**

```python
from chip.clusters import Objects as clusters
from matter_server.common.helpers.util import dataclass_from_dict, dataclass_to_dict

# Build a MoveToLevel command with a level of 128 (50%)
command = clusters.LevelControl.Commands.MoveToLevelWithOnOff(
    level=128,
    transitionTime=0,
    optionsMask=0,
    optionsOverride=0,
)

message = {
    "message_id": "level1",
    "command": "device_command",
    "args": {
        "node_id": 1,
        "endpoint_id": 1,
        "cluster_id": command.cluster_id,
        "command_name": "MoveToLevelWithOnOff",
        "payload": dataclass_to_dict(command),
    }
}
```
