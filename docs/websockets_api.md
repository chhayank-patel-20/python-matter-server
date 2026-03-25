# Websocket documentation

This document describes the Websocket API for the Python Matter Server.

## Websocket connection

When a client connects to the Matter Server, it will automatically receive a `server_info` message with version information.

```json
{
  "fabric_id": 1,
  "compressed_fabric_id": 1234567890,
  "schema_version": 1,
  "min_supported_schema_version": 1,
  "sdk_version": "1.0.0",
  "wifi_credentials_set": true,
  "thread_credentials_set": false,
  "bluetooth_enabled": true
}
```

## Websocket commands

### Server Information

**Get Server Info**

Get version info of the Matter Server.

```json
{
  "message_id": "1",
  "command": "server_info"
}
```

**Get Server Diagnostics**

Return a full dump of the server (for diagnostics).

```json
{
  "message_id": "1",
  "command": "diagnostics"
}
```

**Get Vendor Names**

Get a map of vendor ids to vendor names.

```json
{
  "message_id": "1",
  "command": "get_vendor_names",
  "args": {
    "filter_vendors": [1, 2, 3]
  }
}
```

### Commissioning

**Scan BLE Devices**

Scan for nearby BLE devices and return raw advertisement data. Optionally filter by MAC address.
Use `timeout` of 20-30 seconds for reliable discovery (devices advertise periodically).

> **Why does my device show different data each time?**
> A Matter device only includes the Matter service UUID `0000fff6-0000-1000-8000-00805f9b34fb`
> in its advertisement when a **commissioning window is open** (triggered by a button press or
> factory reset). When `is_matter` is `false`, the device is not ready to be paired — open a
> commissioning window on the device first. When `is_matter` is `true`, the `matter_discriminator`
> is extracted automatically and can be used by `commission_with_mac`.

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

Omit `mac_address` to return all nearby BLE devices.

**Example Response (device in commissioning mode):**

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

**Example Response (device NOT in commissioning mode):**

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

**Commission with MAC Address**

Commission a Matter device using its BLE MAC address and setup PIN code — no QR code needed.
The server scans for the device, extracts the discriminator from its Matter BLE advertisement,
and commissions it using any pre-set WiFi/Thread credentials.

**Requirements:**
- Device must be in commissioning mode (`is_matter: true` in scan results)
- Set WiFi credentials first via `set_wifi_credentials` (for WiFi devices)
- Set Thread dataset first via `set_thread_dataset` (for Thread devices)

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

Returns the commissioned `MatterNodeData` on success. Raises an error if:
- The device is not found in range
- The device is not in Matter commissioning mode (no `fff6` UUID)
- BLE commissioning itself fails

**Typical workflow:**
1. `scan_ble_devices` → confirm `is_matter: true` (press button if false)
2. `set_wifi_credentials` → provide network credentials
3. `commission_with_mac` → device is commissioned and returned as a node

---

**Discover**

Discover Commissionable Nodes (discovered on BLE or mDNS). Returns the current list. New discoveries will be sent as `discovery_updated` events.

```json
{
  "message_id": "1",
  "command": "discover_commissionable_nodes"
}
```

**Example Response:**

```json
{
  "message_id": "1",
  "result": [
    {
      "instance_name": "...",
      "host_name": "...",
      "port": 5540,
      "long_discriminator": 1234,
      "vendor_id": 1,
      "product_id": 1,
      "commissioning_mode": 1,
      "device_type": 1,
      "device_name": "My Device",
      "pairing_instruction": "...",
      "pairing_hint": 1,
      "addresses": ["192.168.1.100"]
    }
  ]
}
```

If the command fails due to internal errors (e.g. `object list can't be used in 'await' expression`), it will return an ErrorResultMessage.

**Set WiFi credentials**

Inform the controller about the WiFi credentials it needs to send when commissioning a new device.

```json
{
  "message_id": "1",
  "command": "set_wifi_credentials",
  "args": {
    "ssid": "wifi-name-here",
    "credentials": "wifi-password-here"
  }
}
```

**Set Thread dataset**

Inform the controller about the Thread credentials it needs to use when commissioning a new device.

```json
{
  "message_id": "1",
  "command": "set_thread_dataset",
  "args": {
    "dataset": "put-credentials-here"
  }
}
```

**Set Default Fabric Label**

Set the default fabric label that will be set on a node after successful commissioning.

```json
{
  "message_id": "1",
  "command": "set_default_fabric_label",
  "args": {
    "label": "My Home"
  }
}
```

**Update Fabric Label**

Update the fabric label of an already commissioned node.

```json
{
  "message_id": "1",
  "command": "update_fabric_label",
  "args": {
    "node_id": 1,
    "label": "Living Room"
  }
}
```

**Commission with code**

Commission a new device using a pairing code. For WiFi or Thread based devices, the credentials need to be set upfront, otherwise, commissioning will fail. Supports both QR-code syntax (MT:...) and manual pairing code as string.

Note: The server includes an optimized BLE commissioning path that extracts the discriminator from the setup code to improve discovery reliability. When credentials are provided, it uses specialized SDK methods to ensure network parameters are correctly passed to the device.

Optional `fabric_label` sets a label for our fabric on the device (visible in `get_fabrics`). Useful in multi-fabric setups to identify which controller owns which entry.

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

**Commission on network**

Commission a device already present on the network.

```json
{
  "message_id": "2",
  "command": "commission_on_network",
  "args": {
    "setup_pin_code": 12345678,
    "filter_type": 0,
    "filter": null
  }
}
```

**Open Commissioning window**

Open a commissioning window on an already-commissioned device to allow a **second Matter controller** to add it to their fabric (Multi-Fabric Commissioning — Step 1).
Returns `setup_pin_code`, `setup_manual_code`, and `setup_qr_code` for the second controller to use.

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

**Example Response:**
```json
{
  "message_id": "2",
  "result": {
    "setup_pin_code": 12345678,
    "setup_manual_code": "35325335079",
    "setup_qr_code": "MT:Y.ABCDEFG123456789"
  }
}
```

---

**Commission on Commissioning Window (Multi-Fabric)**

Add a device to our fabric when it already belongs to another fabric (Multi-Fabric Commissioning — Step 2).
Use the `setup_pin_code` and `discriminator` returned by the other controller's `open_commissioning_window` call.

> **Multi-Fabric flow:**
> 1. Device is on **Fabric A** (another controller).
> 2. Fabric A calls `open_commissioning_window(node_id)` → shares `setup_pin_code` + `discriminator` with you.
> 3. You call `commission_on_commissioning_window` → device is now on **both fabrics**.
>
> To share **your** device to another fabric: call `open_commissioning_window` on your node and give the returned codes to the other controller.

```json
{
  "message_id": "2",
  "command": "commission_on_commissioning_window",
  "args": {
    "setup_pin_code": 12345678,
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
| `ip_addr` | No | Direct IP to skip mDNS discovery (faster, use when IP is known) |
| `fabric_label` | No | Label to identify our fabric on the device (visible in `get_fabrics`) |

Returns `MatterNodeData` of the newly commissioned node.

After commissioning, call `get_fabrics(node_id)` to confirm the device is on multiple fabrics.

---

**Get Fabrics**

Get all fabrics commissioned on a node.

```json
{
  "message_id": "1",
  "command": "get_fabrics",
  "args": {
    "node_id": 1
  }
}
```

**Remove Fabric**

Remove a specific fabric from a node.

```json
{
  "message_id": "1",
  "command": "remove_fabric",
  "args": {
    "node_id": 1,
    "fabric_index": 1
  }
}
```

### Node Management

**Get Nodes**

Get all nodes already commissioned on the controller.

```json
{
  "message_id": "2",
  "command": "get_nodes"
}
```

**Get Node**

Get info of a single Node.

```json
{
  "message_id": "2",
  "command": "get_node",
  "args": {
    "node_id": 1
  }
}
```

**Start listening**

When the `start_listening` command is issued, the server will dump all existing nodes. From that moment on all events (including node attribute changes) will be forwarded.

```json
{
  "message_id": "3",
  "command": "start_listening"
}
```

**Interview Node**

Manually trigger a full interview of a node.

```json
{
  "message_id": "1",
  "command": "interview_node",
  "args": {
    "node_id": 1
  }
}
```

**Remove Node**

Remove a Matter node/device from the fabric.

```json
{
  "message_id": "1",
  "command": "remove_node",
  "args": {
    "node_id": 1
  }
}
```

**Ping Node**

Ping node on the currently known IP-address(es).

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

**Get Node IP Addresses**

Return the currently known (scoped) IP-address(es) for a node.

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

### Groups and Bindings

**Group Add**

Add a node's endpoint to a group.

```json
{
  "message_id": "1",
  "command": "group_add",
  "args": {
    "node_id": 1,
    "endpoint": 1,
    "group_id": 1,
    "group_name": "My Group"
  }
}
```

**Group Remove**

Remove a node's endpoint from a group.

```json
{
  "message_id": "1",
  "command": "group_remove",
  "args": {
    "node_id": 1,
    "endpoint": 1,
    "group_id": 1
  }
}
```

**Group Get Membership**

Get all groups a node's endpoint belongs to.

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

**Group Send Command**

Send a command to a group of nodes.
Note: The server will automatically use generated keys. If a node was manually modified outside of the server, you may encounter `Internal Error (0xAC)`, in which case the server attempts to automatically re-provision it if possible.

```json
{
  "message_id": "1",
  "command": "group_send_command",
  "args": {
    "group_id": 1,
    "cluster_id": 6,
    "command_name": "On",
    "payload": {}
  }
}
```

**Common Errors during Group Commands:**
- `CHIP Error 0xAC (Internal Error)`: The controller doesn't have the group keys for the specified group ID. Ensure the group was created via the API (`add_group`) before sending commands.
- `CHIP Error 0x32 (Timeout)`: Operational discovery of one or more nodes in the group failed. This means the node is unreachable on the network or its mDNS record could not be found. Check if the device is powered on and connected to the same network.

**Group Add Key Set**

Add a group key set to a node. This is required for real devices to receive group commands.
Standard test key (if omitted): `0102030405060708090a0b0c0d0e0f10`

```json
{
  "message_id": "1",
  "command": "group_add_key_set",
  "args": {
    "node_id": 1,
    "keyset_id": 1,
    "key_hex": "0102030405060708090a0b0c0d0e0f10"
  }
}
```

**Group Bind Key Set**

Bind a group ID to a keyset ID on a node.

```json
{
  "message_id": "1",
  "command": "group_bind_key_set",
  "args": {
    "node_id": 1,
    "group_id": 1,
    "keyset_id": 1
  }
}
```

**Init Group Testing Data**

Initialize the controller with test group keys. Required for group commands in development.
Note: This is automatically called by the server at startup, but can be called manually if needed.

```json
{
  "message_id": "1",
  "command": "init_group_testing_data"
}
```

**Get Groups**

Get all groups in the server registry.

```json
{
  "message_id": "1",
  "command": "get_groups"
}
```

**Add Group**

Add a group to the server registry.

```json
{
  "message_id": "1",
  "command": "add_group",
  "args": {
    "group_id": 1,
    "group_name": "My Group"
  }
}
```

**Remove Group**

Remove a group from the server registry.

```json
{
  "message_id": "1",
  "command": "remove_group",
  "args": {
    "group_id": 1
  }
}
```

**Binding Add**

Add a binding to a node's endpoint.

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

**Binding Remove**

Remove a binding from a node's endpoint.

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

### Attributes and Commands

**Read an attribute**

Here is an example of reading `OnOff` attribute on a switch (OnOff cluster)

```json
{
  "message_id": "read",
  "command": "read_attribute",
  "args": {
    "node_id": 1,
    "attribute_path": "1/6/0"
  }
}
```

**Write an attribute**

Here is an example of writing `OnTime` attribute on a switch (OnOff cluster)

```json
{
  "message_id": "write",
  "command": "write_attribute",
  "args": {
    "node_id": 1,
    "attribute_path": "1/6/16385",
    "value": 10
  }
}
```

**Send a command**

Here is an example of turning on a switch (OnOff cluster)

```json
{
  "message_id": "example",
  "command": "device_command",
  "args": {
    "endpoint_id": 1,
    "node_id": 1,
    "payload": {},
    "cluster_id": 6,
    "command_name": "On"
  }
}
```

**Set ACL Entry**

Set access control entries for a node.

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

**Set Node Binding**

Set bindings for a node.

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

### OTA Updates

**Check Node Update**

Check if there is an update for a particular node.

```json
{
  "message_id": "1",
  "command": "check_node_update",
  "args": {
    "node_id": 1
  }
}
```

**Update Node**

Update a node to a new software version.

```json
{
  "message_id": "1",
  "command": "update_node",
  "args": {
    "node_id": 1,
    "software_version": 123
  }
}
```

### Miscellaneous

**Import Test Node**

Import test node(s) from a HA or Matter server diagnostics dump.

```json
{
  "message_id": "1",
  "command": "import_test_node",
  "args": {
    "dump": "{...}"
  }
}
```

## Websocket events

When a client is listening (after sending the `start_listening` command), it will receive events from the server.

**Node Added**

Fired when a new node is added to the fabric.

```json
{
  "event": "node_added",
  "data": {
    "node_id": 1,
    "...": "..."
  }
}
```

**Node Updated**

Fired when a node's information is updated.

```json
{
  "event": "node_updated",
  "data": {
    "node_id": 1,
    "...": "..."
  }
}
```

**Node Removed**

Fired when a node is removed from the fabric.

```json
{
  "event": "node_removed",
  "data": 1
}
```

**Discovery Updated**

Fired when a commissionable node is discovered or disappears from mDNS.

```json
{
  "event": "discovery_updated",
  "data": {
    "instance_name": "...",
    "host_name": "...",
    "port": 5540,
    "long_discriminator": 1234,
    "vendor_id": 1,
    "product_id": 1,
    "commissioning_mode": 1,
    "device_type": 1,
    "device_name": "...",
    "pairing_instruction": "...",
    "pairing_hint": 1,
    "addresses": ["..."]
  }
}
```

Or for removal:

```json
{
  "event": "discovery_updated",
  "data": {
    "name": "...",
    "removed": true
  }
}
```

**Commissioning Progress**

Fired during the commissioning process.

```json
{
  "event": "commissioning_progress",
  "data": {
    "node_id": 1,
    "stage": "started"
  }
}
```

**Attribute Updated**

Fired when an attribute value changes.

```json
{
  "event": "attribute_updated",
  "data": [
    1,
    "1/6/0",
    true
  ]
}
```

**Node Event**

Fired when a node event occurs.

```json
{
  "event": "node_event",
  "data": {
    "node_id": 1,
    "endpoint_id": 0,
    "cluster_id": 1,
    "event_id": 1,
    "event_number": 1,
    "priority": 1,
    "timestamp": 123456789,
    "timestamp_type": 0,
    "data": {}
  }
}
```

**Server Shutdown**

Fired when the server is shutting down.

```json
{
  "event": "server_shutdown",
  "data": null
}
```

**Server Info Updated**

Fired when the server information is updated.

```json
{
  "event": "server_info_updated",
  "data": {
    "...": "..."
  }
}
```

**Endpoint Added**

Fired when an endpoint is added to a node.

```json
{
  "event": "endpoint_added",
  "data": {
    "node_id": 1,
    "endpoint_id": 1
  }
}
```

**Endpoint Removed**

Fired when an endpoint is removed from a node.

```json
{
  "event": "endpoint_removed",
  "data": {
    "node_id": 1,
    "endpoint_id": 1
  }
}
```

## Python script to send a command

Because we use the datamodels of the Matter SDK, this is a little bit more involved.
Here is an example of turning on a switch:

```python
import json

# Import the CHIP clusters
from chip.clusters import Objects as clusters

# Import the ability to turn objects into dictionaries, and vice-versa
from matter_server.common.helpers.util import dataclass_from_dict,dataclass_to_dict

command = clusters.OnOff.Commands.On()
payload = dataclass_to_dict(command)


message = {
    "message_id": "example",
    "command": "device_command",
    "args": {
        "endpoint_id": 1,
        "node_id": 1,
        "payload": payload,
        "cluster_id": command.cluster_id,
        "command_name": "On"
    }
}

print(json.dumps(message, indent=2))
```

You can also provide parameters for the cluster commands. Here's how to change the brightness for example:

```python
command = clusters.LevelControl.Commands.MoveToLevelWithOnOff(
  level=int(value), # provide a percentage
  transitionTime=0, # in seconds
)
```
