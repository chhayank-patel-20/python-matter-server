# Matter Scenes Management Cluster (0x0062) Guide

The **Scenes Management Cluster** (added in Matter 1.2) is the modern way to handle "presets" or "scenes" in a Matter fabric. It allows a controller to capture the current state of one or more devices and recall that state later with a single command.

---

## 1. Cluster Offerings
The Scenes Management cluster provides the following capabilities:
- **Store Scene**: Captures the current active attributes (like brightness, color, or on/off state) and saves them into a specific Scene ID.
- **Recall Scene**: Actives a previously saved scene.
- **Add Scene**: Directly defines a scene's attributes via a complex JSON payload without needing to set the device state first.
- **Get Scene Membership**: Lists which scenes are currently stored for a specific group.
- **Copy/Remove Scenes**: Management tools for duplicating or deleting scene data.

---

## 2. Prerequisites
Before you can use scenes, the following must be true:

### A. Group Membership
Scenes are **Group-Scoped**. Every scene is associated with a specific **GroupID**.
- The device must be part of at least one group (Cluster 0x0004).
- **CRITICAL**: If the device is not a member of the GroupID you specify, the command will fail with `INVALID_COMMAND` (Status 133 / 0x85).
- If you use Group ID `0`, the scene is "global" (often used for non-group scenes, but group-based is standard).

### B. Access Control (ACL)
Multicast scenes (sent to a group) require a **Group-authenticated ACL**.
- **AuthMode**: 3 (Group)
- Without this, the device will receive the multicast packet but reject it for lack of permission.

---

## 3. Configuration Flow: "Store & Recall" (Recommended)
This is the easiest flow for most users:

1.  **Commission the Device**: Ensure the device is on the fabric.
2.  **Add to Group**: Assign the device to a Group ID (e.g., `0x0101`).
3.  **Configure ACL**: Inject the Group ACL for that device.
4.  **Set "The Look"**: Manually set the device attributes to what you want (e.g., Dim to 20%, Turn Warm White).
5.  **Store Scene**: Send the `StoreScene` command to the device to record this state into a Scene ID.
6.  **Recall Scene**: At any time, send `RecallScene` to return the device to that recorded state.

---

## 4. Factual Commands (chip-tool)

### Step 1: Add Device to Group
```bash
./chip-tool groups add-group <group_id> "SceneGroup" <node_id> <endpoint_id>
```

### Step 2: Configure ACL (Mandatory for Multicast)
```bash
./chip-tool accesscontrol write acl '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": null, "targets": null}, {"fabricIndex": 1, "privilege": 4, "authMode": 3, "subjects": null, "targets": null}]' <node_id> 0
```

### Step 3: Store a Scene
Sets the current state of `<node_id>` into Scene `<scene_id>` within Group `<group_id>`.
```bash
# Syntax: store-scene <groupId> <sceneId> <destination-id> <endpoint-id>
./chip-tool scenesmanagement store-scene 0x0101 1 <node_id> <endpoint_id>
```

### Step 4: Recall a Scene
Actives the recorded state.
```bash
# Syntax: recall-scene <groupId> <sceneId> <destination-id> <endpoint-id>
./chip-tool scenesmanagement recall-scene 0x0101 1 <node_id> <endpoint_id>
```
*Tip: Use the Group Node ID `0xffffffffffff0101` as the destination-id to recall the scene for the whole group at once via multicast.*

### Step 5: Advanced (Add Scene Directly)
Define a scene without "recording" it first.
```bash
# Syntax: add-scene <groupId> <sceneId> <transitionTime> <sceneName> <extensionFieldSets> <destination-id> <endpoint-id>
./chip-tool scenesmanagement add-scene 0x0101 1 10 "MyScene" '[{"clusterID": 6, "attributeValuePairs": [{"attributeID": 0, "attributeValue": "01"}]}]' <node_id> <endpoint_id>
```

---

## 5. Common Failures & Troubleshooting
- **Error 0x85 (INVALID_COMMAND / 133)**: The device is not a member of the `GroupID` you specified. You must run `groups add-group` first.
- **Error 0x89 (RESOURCE_EXHAUSTED)**: The device's scene table is full. You must remove old scenes using `remove-all-scenes`.
- **Error 0x8B (NOT_FOUND)**: You are trying to recall a `SceneID` or `GroupID` that hasn't been stored on that device.
- **Error 0x7E (UNSUPPORTED_ACCESS)**: The controller does not have permission to modify the group/scene table. Check your ACL settings.
- **No Response to Multicast**: Check your ACL settings. Ensure `authMode: 3` is present.
- **Scene Valid?**: You can read the `FabricSceneInfo` attribute to see if the device currently thinks its state matches a stored scene.
