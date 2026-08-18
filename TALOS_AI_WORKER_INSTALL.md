# Physical Talos GPU worker installation and recovery

The physical GPU workers are installed and registered in the cluster. Use this document only to replace, recover, or reinstall a physical GPU worker.

The OpenTofu configuration owns Talos machine configuration, vendor Image Factory schematics, Kubernetes labels and taints, local storage definitions, GPU operators, and validation. The physical operator owns only console and network-gear actions.

## Machine identity

| Talos node | Target address | NIC MAC | GPU |
| --- | --- | --- | --- |
| `ai-nvidia-01` | `172.16.200.105` | `3c:7c:3f:21:8d:37` | Two RTX 3090 GPUs |
| `ai-amd-01` | `172.16.200.106` | `38:05:25:36:87:02` | Radeon 8060S (`gfx1151`) |
| `ai-nvidia-02` | `172.16.200.107` | `30:c5:99:40:2c:8c` | NVIDIA GB10 Grace Blackwell |

The target network is VLAN 2000. Each host installs Talos on its NVMe disk. Reinstallation erases the existing host operating system and node-local model data.

## Network-gear actions

Before a reinstall:

1. Identify the switch port by the listed NIC MAC address.
2. Configure the port as untagged access traffic on VLAN 2000.
3. Reserve or exclude the listed static address in DHCP/IPAM.
4. Record the switch and port used for recovery.

Do not configure a Talos VLAN subinterface unless the switch port is intentionally changed to a trunk.

## Physical actions

Do one worker at a time.

1. Connect a display and keyboard to the selected host.
2. Connect the listed NIC to the prepared switch port.
3. Boot the matching vendor Talos installer USB prepared from the OpenTofu Image Factory output.
4. Leave the host at the Talos maintenance console. Do not select an install disk or enter a machine configuration manually.
5. Have the remote operator apply the reviewed generated machine configuration.
6. Remove the USB after the remote operator confirms NVMe installation and reboot.
7. Confirm local NVMe is the first UEFI boot device when required.

## Remote acceptance checks

Before returning the worker to service, confirm all checks below:

- The Kubernetes Node is Ready with the dedicated GPU labels and `NoSchedule` taint.
- The `ai-data` local volume is mounted.
- The matching vendor kernel driver is loaded.
- Kubernetes advertises the expected vendor GPU resource.
- `ai-nvidia-02` advertises two `nvidia.com/gpu.shared` time-sliced resources.
- The matching device plugin and metrics exporter are Ready on the worker.
- Prometheus and the `GPU Workers` dashboard show the matching exporter target as healthy.

Do not install GPU drivers, container runtimes, labels, taints, device plugins, or local PVs manually. Talos extensions, Helmfile, and Kubernetes manifests own those layers.
