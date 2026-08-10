# Physical Talos GPU worker checklist

This checklist contains only work that needs a person at a machine or in the UniFi network controller. The agent and OpenTofu perform the Talos configuration, node join, GPU setup, local-storage setup, and validation remotely.

Do one machine at a time. Do not start the AMD installation until the NVIDIA node is complete and the agent confirms it is healthy.

## Machine identity

| Talos node | Current host | Target address | NIC MAC | GPU |
|---|---|---:|---|---|
| `ai-nvidia-01` | `192.168.1.105` | `172.16.200.105` | `3c:7c:3f:21:8d:37` | 2x RTX 3090 |
| `ai-amd-01` | `192.168.1.211` | `172.16.200.106` | `38:05:25:36:87:02` | Radeon 8060S, `gfx1151` |

The target network is `172.16.200.0/24`, on VLAN `2000`. Talos uses the single NVMe disk in each machine. This overwrites Fedora.

## Network-gear actions

Complete these actions before booting either Talos USB installer.

1. In UniFi, identify the switch port connected to each target NIC:
   - NVIDIA: NIC with MAC `3c:7c:3f:21:8d:37`.
   - AMD: NIC with MAC `38:05:25:36:87:02`.
2. Set each switch port as an untagged access port on VLAN `2000`.
   - Do not use a trunk profile unless the Talos configuration is changed first.
   - Do not configure a VLAN subinterface on Talos. The port provides untagged VLAN 2000 traffic.
3. Reserve or exclude the two target addresses in UniFi DHCP/IPAM:
   - `172.16.200.105` for `3c:7c:3f:21:8d:37`.
   - `172.16.200.106` for `38:05:25:36:87:02`.

   The current DHCP pool includes `.105` and `.106`. Do not leave these addresses available for dynamic allocation. A reservation is sufficient if UniFi excludes reserved addresses from its dynamic pool. Otherwise, create an explicit exclusion or adjust the DHCP range without disturbing active leases.
4. Record the switch name and port number for each machine. This is needed for reinstall and recovery.

Network connectivity is assumed. Do not perform routing, firewall, DNS, or backup work as part of this checklist.

## Physical actions: NVIDIA node first

1. Connect a keyboard and display to `192.168.1.105`.
2. Connect only the NIC with MAC `3c:7c:3f:21:8d:37` to its prepared VLAN 2000 switch port.
3. Insert the NVIDIA Talos installer USB that the agent prepared.
4. Boot the machine from the USB device. Use the one-time UEFI boot menu if available.
5. Leave the machine at the Talos maintenance console. Do not type a Talos configuration or select a disk manually.
6. Tell the agent that `ai-nvidia-01` is booted from USB.
7. Wait for the agent to apply the generated configuration and confirm that the NVMe installation and reboot completed.
8. Remove the USB. If needed, set the local NVMe disk as the first UEFI boot device.
9. Wait for the agent to confirm all of these checks:
   - `ai-nvidia-01` is Ready.
   - The `NoSchedule` GPU taint and node labels exist.
   - NVIDIA GPU capacity is visible to Kubernetes.
   - The local `ai-data` volume is mounted.

## Physical actions: AMD node second

1. Connect a keyboard and display to `192.168.1.211`.
2. Connect only the NIC with MAC `38:05:25:36:87:02` to its prepared VLAN 2000 switch port.
3. Insert the AMD Talos installer USB that the agent prepared.
4. Boot the machine from the USB device.
5. Leave the machine at the Talos maintenance console. Do not type a Talos configuration or select a disk manually.
6. Tell the agent that `ai-amd-01` is booted from USB.
7. Wait for the agent to apply the generated configuration and confirm that the NVMe installation and reboot completed.
8. Remove the USB. If needed, set the local NVMe disk as the first UEFI boot device.
9. Wait for the agent to confirm all of these checks:
   - `ai-amd-01` is Ready.
   - The `NoSchedule` GPU taint and node labels exist.
   - AMD GPU capacity is visible to Kubernetes.
   - The local `ai-data` volume is mounted.

## Remote work owned by the agent and OpenTofu

The remote workflow is already declared in this repository. It creates separate NVIDIA and AMD Talos Image Factory schematics, renders machine configurations, applies node labels and taints, creates the Talos user volume, reconciles later machine configuration changes, deploys vendor GPU operators, and creates retained static local PVs.

Do not manually install GPU drivers, container runtimes, Kubernetes labels, taints, GPU operators, or local PVs. Do not apply a Talos configuration from the console.
