# Matter Binding: How Devices Talk Directly (Device-to-Device)

Matter's **Binding Cluster** allows devices to control each other directly. For example, a light switch (the **Source**) can directly tell a light bulb (the **Target**) to turn on, even if your phone or hub is disconnected.

---

## 1. The Relationship: Client vs Server

In Binding, every communication has two roles:
*   **The Client (Source)**: The device that "gives" the command (e.g., a Light Switch).
*   **The Server (Target)**: The device that "receives" and "acts" on the command (e.g., a Light Bulb).

**The Secret**: Binding configuration is always written to the **Client** (Source) device, telling it where to send its commands.

---

## 2. The Two-Step Handshake (Prerequisites)

Before a switch can control a bulb, two things must happen:

### Step A: Permission (Target ACL)
You must tell the **Target** (Bulb) that it is allowed to accept commands from the **Source** (Switch). By default, Matter devices only listen to "Managers" (Controllers). 
*   **You must add an ACL entry** to the Bulb that specifically names the Switch as a permitted user.

### Step B: Association (Source Binding)
You must tell the **Source** (Switch) exactly which device it should talk to when someone presses a button.
*   **You must update the Binding Table** on the Switch with the Bulb's NodeID and Endpoint.

---

## 3. Factual Configuration Flow (chip-tool)

Imagine you have two devices:
*   **Light Switch (Source)**: Node ID `0x00AA`
*   **Light Bulb (Target)**: Node ID `0x00BB`

### Step 1: Discover Target Info
Find the endpoint of the bulb (usually Endpoint 1).
```bash
./chip-tool descriptor read server-list 0x00BB 0
```

### Step 2: Grant Permission (On the Target/Bulb)
This command tells the Bulb (`0xBB`): "You are allowed to be operated by Switch `0xAA`".
```bash
# Syntax: accesscontrol write acl <JSON> <destination_node> <destination_endpoint>
./chip-tool accesscontrol write acl '[{"fabricIndex": 1, "privilege": 5, "authMode": 2, "subjects": null, "targets": null}, {"fabricIndex": 1, "privilege": 4, "authMode": 2, "subjects": [170], "targets": null}]' 187 0
```
*Note: `170` is the decimal version of `0xAA`. `187` is the decimal version of `0xBB`.*

### Step 3: Create the Link (On the Source/Switch)
This command tells the Switch (`0xAA`): "When you have an On/Off command to send, send it to Bulb `0xBB` on Endpoint 1".
```bash
# Syntax: binding write binding <JSON> <source_node> <source_endpoint>
./chip-tool binding write binding '[{"node": 187, "endpoint": 1, "cluster": 6}]' 170 1
```

---

## 4. Why Bindings Fail (Troubleshooting)

1.  **"Permission Denied" (0x7E)**: You skipped Step 2. The Bulb received the command from the Switch but didn't see the Switch on its "VIP list" (ACL), so it ignored it.
2.  **"Resource Exhausted" (0x89)**: The Switch has a limited Binding Table (sometimes only 4-5 slots). You must overwrite or clear old bindings if you have too many.
3.  **Different Fabrics**: Binding only works if both devices are on the **same fabric**. They must share the same "Root Certificate".
4.  **Endpoint Confusion**: If you bind the switch to the bulb's Endpoint 0 (management) instead of Endpoint 1 (light control), the light won't turn on.
