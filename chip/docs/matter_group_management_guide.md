
```markdown
# Matter Multicast Group Management: Technical Reference
**Target Audience**: Backend Developers / System Architects
**Protocol Version**: Matter 1.0+ (Group Messaging & ACLs)

---

## 1. Executive Summary
Matter Group Management allows a controller to manage multiple devices (Accessories) as a single logical entity. Unlike Unicast (CASE) which uses Node IDs, Group Messaging uses **IP Multicast** (over IPv6) and **Group IDs**.

**Critical Requirement**: For a device to process a group command (e.g., `OnOff`), it is **not enough** to just add it to a group. You must also:
1.  Install identical **Security Keys** on both the Controller and the Device.
2.  Map those Keys to a **Group ID**.
3.  Configure an **Access Control List (ACL)** entry that specifically allows `AuthMode: Group`.

---

## 2. Infrastructure Prerequisites
### 2.1 Addressing
*   **Multicast Address**: Derived from the Fabric ID and Group ID.
*   **Node ID Format**: When sending commands, use the "Group Node ID" format: `0xFFFF_FFFF_FFFF_XXXX` where `XXXX` is the Hex Group ID.
    *   *Example*: Group `257` (Hex `0x0101`) $\rightarrow$ Node ID `0xffffffffffff0101`.

### 2.2 Fabric Context
All group operations must happen within the same **Fabric Index**. If the device is factory reset or the KVS (Key Value Store) is cleared, the group configuration is lost.

---

## 3. The 7-Step Configuration Pipeline

This is the verified sequence required to enable multicast control.

### Step 1: Commissioning (Pairing)
Establish a secure CASE session with the device.
```bash
# Example: Pair node 1 with setup code 20202021
pairing onnetwork 1 20202021
```

### Step 2: Write Security Group Keys (KeySetWrite)
The device needs a set of keys to decrypt multicast messages. This is done via the `GroupKeyManagement` cluster.
*   **Epoch Keys**: 16-byte hex strings.
*   **Epoch Start Time**: Microseconds since Unix Epoch (or any synchronized counter).
*   **Security Policy**: `0` (TrustFirst).

```bash
# Note: Provide epochKey0, 1, and 2 if required by the SDK version.
groupkeymanagement key-set-write '{"groupKeySetID": 419, "groupKeySecurityPolicy": 0, "epochKey0": "hex:a0a1a2a3a4a5a6a7a8a9aaabacadaeaf", "epochStartTime0": 1}' 1 0
```

### Step 3: Map Group ID to KeySetID
Tell the device that Group ID `257` should use the keys in KeySet `419`.
```bash
groupkeymanagement write group-key-map '[{"fabricIndex": 1, "groupId": 257, "groupKeySetID": 419}]' 1 0
```

### Step 4: Define Group Membership
Add the device's endpoint (usually `1`) to the group.
```bash
groups add-group 257 "MyGroupName" 1 1
```

### Step 5: Configure Access Control (The "Missing Link")
Standard pairing only gives the **admin** rights via `CASE` (Unicast). You must explicitly allow **Group-authenticated** messages.
*   **AuthMode**: `3` (Group)
*   **Privilege**: `4` (Manage) or `5` (Admin)
```bash
accesscontrol write acl '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": null, "targets": null}, {"fabricIndex": 1, "privilege": 4, "authMode": 3, "subjects": null, "targets": null}]' 1 0
```

### Step 6: synchronize Controller Group Store (Python/Local Side)
The controller (the Python server) must ALSO know the keys is it sending.
```bash
# If using chip-tool:
groupsettings add-group "MyGroupName" 257
groupsettings add-keysets 419 0 1 hex:a0a1...
groupsettings bind-keyset 257 419
```

### Step 7: Execution (Multicast Toggle)
Send the command to the Group Address.
```bash
onoff toggle 0xffffffffffff0101 1
```

---

## 4. Common Troubleshooting Patterns

### 4.1 "Failed to Decrypt" Error
*   **Cause**: The `epochKey` or `groupKeySetID` on the controller does not match the one written to the device.
*   **Solution**: Re-run Step 2 and Step 6 with identical hex strings.

### 4.2 Message Sent but Device Ignores It
*   **Cause**: Missing ACL entry with `authMode: 3`.
*   **Symptom**: Server logs show "Received Groupcast" but "Access Control Denied".
*   **Solution**: Re-run Step 5.

### 4.3 "Duplicate Key ID"
*   **Cause**: Attempting to write a KeySet that already exists in the device's persistent storage.
*   **Solution**: This is a safe error. Proceed to binding.

---

## 5. Security Best Practices
1.  **Key Rotation**: In production, `epochKey0`, `1`, and `2` should be rotated periodically using the `epochStartTime` logic.
2.  **Least Privilege**: Give Group ACLs the minimum required privilege (Operaate/Manage) rather than Admin.
3.  **Endpoint Scoping**: Only add specific endpoints to groups to prevent unauthorized control of administrative clusters.
```