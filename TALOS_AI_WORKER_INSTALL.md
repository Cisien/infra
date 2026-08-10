# Manual Talos installation for physical AI workers

This runbook installs Talos Linux on the two AI machines and places them on the Kubernetes worker VLAN. It is for a manual USB/ISO installation. It does not use PXE.

## Scope and safety

The installation erases the Fedora system disk on each host. Complete the backup and router-migration steps before booting Talos installer media.

Install one machine at a time. Start with the NVIDIA machine. Do not reimage the AMD machine until the NVIDIA worker is Ready, Cilium is healthy, and a GPU allocation test succeeds.

Do not run `talosctl bootstrap`. These are worker Nodes joining the existing three-member control plane.

## Target inventory

| Purpose | Talos hostname | Planned address | Network | Gateway and DNS | Active physical NIC | NIC MAC | Install disk | GPU |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NVIDIA worker | `ai-nvidia-01` | `172.16.200.105/24` | VLAN 2000 | `172.16.200.1` | current Fedora `enp5s0` | `3c:7c:3f:21:8d:37` | `/dev/nvme0n1` — Samsung 970 EVO Plus 2 TB | 2 × RTX 3090 |
| AMD worker | `ai-amd-01` | `172.16.200.106/24` | VLAN 2000 | `172.16.200.1` | current Fedora `enp98s0` | `38:05:25:36:87:02` | `/dev/nvme0n1` — Kingston 2 TB | Radeon 8060S / `gfx1151` |

The target worker network is `172.16.200.0/24` on VLAN 2000. Karpenter owns `172.16.200.193–.254`. Do not use that range for physical machines.

## Important DHCP requirement

UniFi DHCP currently uses `172.16.200.2–.191`. This includes the planned static addresses `.105` and `.106`.

Before Talos installation, reserve or exclude both addresses in UniFi DHCP. A static Talos address is not safe while DHCP can later assign the same address to another client.

Use this policy:

1. Add a fixed-address reservation or exclusion for `172.16.200.105` using MAC `3c:7c:3f:21:8d:37`.
2. Add a fixed-address reservation or exclusion for `172.16.200.106` using MAC `38:05:25:36:87:02`.
3. Check active leases before changing the DHCP pool. Do not reduce the DHCP range if an existing lease uses an address that the new range would exclude.
4. Keep the Karpenter reservation unchanged: `172.16.200.192/26`.

If the UniFi controller cannot reserve a static address that is also used in Talos configuration, change the DHCP scope so it excludes a small physical-worker block such as `.105–.106`. First verify that no active DHCP leases use that block.

## 1. Prepare backups and cutover

Do this before changing the switch port or booting installation media.

1. Record the services, ports, Compose files, model sources, runtime images, and required environment variables on both Fedora hosts.
2. Back up all non-reproducible data from `~/llm/state` and any other service paths. The local NVMe contents will be lost.
3. Create a model-source manifest with the model name, source, revision or checksum, intended node, and expected local storage path. Do not commit access tokens to Git.
4. Move the llama-swap router off `192.168.1.105`, or provide a tested replacement route, before reimaging that host.
5. Confirm that clients still have a healthy backend when one current host is shut down.

Stop condition: do not proceed until the backup has been checked and the router cutover plan is ready.

## 2. Prepare VLAN 2000 on UniFi and the switch

VLAN 2000 is a network tag. It is not inferred from the `172.16.200.x` address.

### 2.1 Verify the VLAN network

In UniFi Network, verify the network with all these properties:

```text
VLAN ID:       2000
IPv4 network:  172.16.200.0/24
Gateway:       172.16.200.1
DHCP:          enabled only for the permitted dynamic range
DNS:           172.16.200.1, unless the network has an intentional alternative
```

Do not create a second network that reuses this subnet or VLAN ID.

### 2.2 Identify the physical switch ports

Find the switch port for each active NIC by MAC address:

```text
NVIDIA host: 3c:7c:3f:21:8d:37
AMD host:    38:05:25:36:87:02
```

Use the active NIC only. Disconnect or leave disabled the extra NICs unless they have a separate documented purpose. This prevents Talos from receiving management traffic on an unintended link.

### 2.3 Configure each host-facing port

For the normal, untagged Talos design, set the host-facing switch port to an access/native profile for VLAN 2000:

```text
Native or untagged network: VLAN 2000 / 172.16.200.0/24
Tagged VLANs:               none, unless an explicit separate design requires them
Port profile:               dedicated Kubernetes AI worker profile
```

Do not configure a VLAN subinterface in Talos for this access-port design. Talos should use an ordinary untagged Ethernet interface with its static `172.16.200.x/24` address.

A trunk design is possible, but it is out of scope for this runbook. Use it only if the physical port must carry more than VLAN 2000. A trunk requires explicit Talos VLAN interface configuration and separate validation.

### 2.4 Test the VLAN before erasing a host

Connect a temporary test client to each configured physical switch port, or temporarily connect the existing Fedora host before reimaging it. Confirm all of these facts:

```bash
ip address
ip route
ping -c 3 172.16.200.1
curl --connect-timeout 5 -k https://172.16.0.230:6443/readyz
curl --connect-timeout 5 -k https://172.16.0.231:6443/readyz
curl --connect-timeout 5 -k https://172.16.0.232:6443/readyz
```

A Kubernetes API authentication error or `403`/`401` response proves the TCP route works. The important failure is a timeout or connection refusal caused by the network path.

Stop condition: do not install Talos if the VLAN cannot reach `172.16.200.1` and all three control-plane API addresses.

## 3. Generate the Talos worker configuration

The physical-worker OpenTofu implementation must exist before installation. It must generate separate worker machine configurations using the existing cluster secrets. It must not create a new cluster, rotate `talos_machine_secrets`, or alter control-plane configuration.

For each worker configuration, verify these settings before use:

```text
machine type:         worker
hostname:             ai-nvidia-01 or ai-amd-01
install disk:         /dev/nvme0n1
address:              172.16.200.105/24 or 172.16.200.106/24
default gateway:      172.16.200.1
DNS:                  172.16.200.1
network match:        target active NIC MAC address
cluster endpoint:     existing cluster endpoint
etcd configuration:   absent
CNI/proxy settings:   match existing cluster worker requirements
```

The images must use Talos `v1.13.8`, which includes Linux kernel `6.18.42`. This meets the AMD Strix host requirement for Linux `6.18` or newer.

Create two vendor-specific Talos Image Factory schematics:

```text
ai-nvidia-01: NVIDIA kernel driver and container-toolkit extensions
ai-amd-01:    siderolabs/amdgpu and siderolabs/amd-ucode extensions
```

Do not add AMD APU-specific IOMMU or memory-aperture kernel arguments unless the direct Talos test shows a real requirement.

Write each generated configuration to a protected temporary directory. Do not add it to Git.

```bash
install_dir="$(mktemp -d)"
chmod 700 "$install_dir"
# Write the generated files as "$install_dir/ai-nvidia-01.yaml" and
# "$install_dir/ai-amd-01.yaml".
chmod 600 "$install_dir/ai-nvidia-01.yaml" "$install_dir/ai-amd-01.yaml"
talosctl validate --config "$install_dir/ai-nvidia-01.yaml" --mode metal --strict
talosctl validate --config "$install_dir/ai-amd-01.yaml" --mode metal --strict
```

Stop condition: do not boot installer media until both configurations pass strict validation and a reviewed OpenTofu plan shows no changes to control planes, Proxmox VMs, or cluster secrets.

## 4. Create the manual installer media

Use the vendor-specific Image Factory schematic to download the Talos `metal-amd64.iso` asset for `v1.13.8`.

The Image Factory URL format is:

```text
https://factory.talos.dev/image/<SCHEMATIC_ID>/v1.13.8/metal-amd64.iso
```

Use one USB device at a time. Confirm its device path before writing the image.

```bash
lsblk -o NAME,MODEL,SIZE,TRAN,RM,MOUNTPOINTS
sudo dd if=metal-amd64.iso of=/dev/REPLACE_USB_DEVICE bs=4M conv=fsync status=progress
sync
```

`dd` permanently overwrites the selected USB device. Do not use `/dev/nvme0n1` here.

Optionally verify the downloaded ISO checksum from the Image Factory release data before writing it.

## 5. Install ai-nvidia-01

The NVIDIA machine is the first conversion because it has conventional discrete GPUs and is the lower-risk path.

1. Confirm the old service has been drained or routed away.
2. Connect only the intended active Ethernet NIC to the prepared VLAN 2000 switch port.
3. Insert the NVIDIA Talos USB media.
4. In UEFI, boot the USB in UEFI mode. Keep local NVMe as the next boot device after USB.
5. At the Talos console, confirm:
   - the expected NIC is present;
   - the maintenance address is `172.16.200.105`, normally from the DHCP reservation;
   - the target disk is the Samsung NVMe at `/dev/nvme0n1`;
   - no unexpected disk will be selected.
6. From an administration client that can reach VLAN 2000, apply the validated configuration to the maintenance-mode Talos API:

```bash
export TALOSCONFIG="$PWD/talosconfig"
talosctl apply-config \
  --insecure \
  --nodes 172.16.200.105 \
  --file "$install_dir/ai-nvidia-01.yaml"
```

The `--insecure` flag is only for the first configuration application to an unconfigured Talos installer node. Do not use it for later administration.

7. Talos installs to `/dev/nvme0n1` according to the machine configuration. Wait for the local-disk boot, then remove the USB media.
8. Wait for the Kubernetes Node to register.

Verify:

```bash
kubectl --kubeconfig ./kubeconfig get node ai-nvidia-01 -o wide
kubectl --kubeconfig ./kubeconfig describe node ai-nvidia-01
talosctl --talosconfig ./talosconfig --nodes 172.16.200.105 health
kubectl --kubeconfig ./kubeconfig -n kube-system get pods -o wide
```

Expected:

```text
InternalIP: 172.16.200.105
Node Ready: True
Cilium Pod: Running and Ready on ai-nvidia-01
```

Do not continue until these checks pass.

## 6. Validate NVIDIA GPU support

After the node is healthy, install the scoped NVIDIA GPU Operator through Helmfile.

The operator must run only on nodes with the NVIDIA AI-worker label and the required GPU-taint toleration. On Talos, disable the operator-managed NVIDIA driver and container toolkit because the Talos Image Factory extensions provide them.

Verify before migration:

```bash
kubectl --kubeconfig ./kubeconfig describe node ai-nvidia-01
kubectl --kubeconfig ./kubeconfig get pods -A -o wide
```

Expected: the node advertises the NVIDIA GPU resource and no NVIDIA driver/operator workload runs on a control-plane, Karpenter worker, or AMD node.

Run one GPU-requesting smoke-test Pod before moving a real model service.

## 7. Install ai-amd-01

Start this section only after `ai-nvidia-01` passes its Node, Cilium, GPU, and smoke-test checks.

1. Confirm the AMD service has a safe routing or downtime window.
2. Connect `enp98s0` hardware, MAC `38:05:25:36:87:02`, to its prepared VLAN 2000 switch port.
3. Use the AMD-specific Image Factory `metal-amd64.iso` asset.
4. Boot the USB in UEFI mode.
5. At the Talos console, confirm the maintenance address is `172.16.200.106` and the Kingston NVMe target is `/dev/nvme0n1`.
6. Apply the validated AMD configuration:

```bash
export TALOSCONFIG="$PWD/talosconfig"
talosctl apply-config \
  --insecure \
  --nodes 172.16.200.106 \
  --file "$install_dir/ai-amd-01.yaml"
```

7. Wait for local-NVMe boot and remove the USB media.
8. Confirm Node and Cilium health before installing the ROCm GPU Operator.

```bash
kubectl --kubeconfig ./kubeconfig get node ai-amd-01 -o wide
talosctl --talosconfig ./talosconfig --nodes 172.16.200.106 health
```

Expected:

```text
InternalIP: 172.16.200.106
Node Ready: True
Cilium Pod: Running and Ready on ai-amd-01
```

## 8. Validate AMD GPU support

Install the ROCm GPU Operator only on the AMD-labelled node with the AI GPU taint toleration.

Verify the operator exposes a usable AMD GPU device/resource according to the selected ROCm operator version. Run a small ROCm inference or runtime smoke test before migrating the full `llama.cpp` or Flux workload.

Do not add special Strix kernel parameters unless the standard extension configuration fails or a measurement proves a need.

## 9. Configure node-local storage before application migration

The AI model data must remain local to each physical host. It will not fail over.

1. Configure a Talos User Volume named `ai-data` on each node's NVMe disk.
2. Keep Talos system partitions and sufficient ephemeral space separate from the AI-data allocation.
3. Confirm the mounted Talos User Volume path on each worker.
4. Create static Kubernetes `local` PersistentVolumes with:
   - node affinity for exactly `ai-nvidia-01` or `ai-amd-01`;
   - the matching local volume path;
   - `persistentVolumeReclaimPolicy: Retain`.
5. Create separate claims for each model/runtime workload.
6. Pin every AI workload with required node affinity, the vendor GPU resource request, and the `ai.cisien.dev/gpu=true:NoSchedule` toleration.

Verify a temporary Pod can write to its own volume and cannot schedule on the other physical worker.

## 10. Final acceptance checks

Run these checks after both workers and GPU operators are ready:

```bash
kubectl --kubeconfig ./kubeconfig get nodes -o wide
kubectl --kubeconfig ./kubeconfig get ciliumnode
kubectl --kubeconfig ./kubeconfig get pods -A -o wide
kubectl --kubeconfig ./kubeconfig get pv,pvc -A
```

Confirm all of the following:

- `ai-nvidia-01` is `Ready` at `172.16.200.105`.
- `ai-amd-01` is `Ready` at `172.16.200.106`.
- Existing control-plane nodes remain Ready and etcd retains quorum.
- Cilium runs on both physical workers.
- NVIDIA resources appear only on the NVIDIA worker.
- AMD resources appear only on the AMD worker.
- Local PVs are bound only to their owning node.
- No ordinary workload can land on the AI workers without the dedicated GPU taint toleration.
- The existing Karpenter allocation range `.193–.254` remains unchanged.

## References

- Talos Image Factory: https://docs.siderolabs.com/talos/v1.13/learn-more/image-factory
- Talos boot assets: https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/boot-assets
- Talos bare-metal ISO installation: https://docs.siderolabs.com/talos/v1.13/platform-specific-installations/bare-metal-platforms/iso
- Talos NVIDIA GPU support: https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/hardware-and-drivers/nvidia-gpu
- Talos AMD GPU support: https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/hardware-and-drivers/amd-gpu
- Talos User Volumes: https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/storage-and-disk-management/disk-management/user
