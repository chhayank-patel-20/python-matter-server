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

```json
{
  "message_id": "2",
  "command": "commission_with_code",
  "args": {
    "code": "MT:Y.ABCDEFG123456789"
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

Open a commissioning window to commission a device present on this controller to another.
Returns code to use as discriminator.

```json
{
  "message_id": "2",
  "command": "open_commissioning_window",
  "args": {
    "node_id": 1
  }
}
```

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
Note: If the command fails with "Internal Error (0xAC)", the server will automatically attempt to re-initialize group testing data and retry once.

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
