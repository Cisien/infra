# Homelab Kubernetes IaC

This repository defines a Talos Kubernetes cluster on Proxmox with:

- three fixed Talos control-plane VMs for etcd quorum;
- one fixed Talos bootstrap worker for platform controllers;
- Karpenter Provider for Proxmox to create and replace elastic Talos workers;
- Cilium Gateway API for ingress;
- one Cilium LAN LoadBalancer IP for the public Gateway;
- NAS-backed NFS persistent volumes through the Kubernetes NFS CSI driver.

The fixed cluster, Cilium Gateway, NFS CSI driver, cert-manager, and Karpenter
platform are applied. Application migration manifests are staged locally in
`kubernetes/apps/`; they are not applied.

## Facts already set

The NFS StorageClass uses this NAS export:

```text
192.168.1.250:/volume/a86e2708-3047-42c6-8f99-1d8cc5192c9d/.srv/.unifi-drive/kubernetes/.data
```

The Proxmox API endpoint is `https://pve.local.cisien.com:8006/`.

Talos uses the empty Image Factory schematic
`376567988ad370138ad8b2698212367b8edcb69b5fd68c80be1f2ec7d603b4ba`.
Terraform downloads its compressed raw image. Karpenter downloads the matching
uncompressed raw image because its Proxmox provider cannot import compressed
source images.

Fixed VM placement and IP allocation are configured as follows:

| VM | Proxmox host | Storage pool | IP |
| --- | --- | --- | --- |
| `cp-01` | `pve-02` | `local-storage-pool` | `172.16.0.230` |
| `cp-02` | `pve-03` | `local-storage-pool` | `172.16.0.231` |
| `cp-03` | `pve-04` | `ssd-pool` | `172.16.0.232` |
| bootstrap worker | `pve-02` | `local-storage-pool` | `172.16.0.233` |
| Cilium public Gateway | LAN | n/a | `172.16.0.240` |

Elastic Karpenter workers are constrained to `pve-02` and `pve-03` and use
`local-storage-pool`. They attach to Proxmox SDN VNet `workvnet` on VLAN 2000.
Karpenter allocates static worker IPs from `172.16.200.192/26` (`.193–.254`),
while UniFi DHCP must remain limited to `172.16.200.2–.191`.

## Current bootstrap decisions

The initial API endpoint is `https://172.16.0.230:6443` on `cp-01`. This is
not highly available. Replace it with a VIP or load balancer before relying on
control-plane failover.

The fixed VM addresses and Gateway address remain outside DHCP. Karpenter workers
use provider-managed static allocation from `172.16.200.192/26`; UniFi DHCP for
VLAN 2000 must remain within `172.16.200.2–.191`.

The confirmed Proxmox inventory has shared NFS `share` storage with `import`
content on all three hosts. Talos raw images download there, then Proxmox imports
them into each selected VM disk pool. `local-storage-pool` is active on
`pve-02` and `pve-03`, and `ssd-pool` is active on `pve-04`.

The Kubernetes NAS export must permit the complete VLAN 2000 Karpenter range
`172.16.200.193–.254` before PVC-backed workers can run. It currently permits
the fixed `172.16.0.x` cluster addresses only.

cert-manager manages the production Let's Encrypt `gateway-system/gateway-tls`
Secret through Gateway API HTTP-01 challenges. The certificate covers the public
Gateway hostnames and is renewed by cert-manager.

## Configuration phases

The phases are explicit to avoid the Karpenter bootstrap cycle.

1. `terraform/terraform.tfvars` contains the local shared Proxmox token, Talos
   Image Factory URL, and temporary API endpoint. It is ignored by Git.
2. Validate and review the Terraform plan. Its resources create fixed Proxmox VMs, apply Talos config, bootstrap etcd, and generate sensitive Karpenter Talos values.
3. After the Talos phase, write the generated sensitive Karpenter values to the ignored file:

   ```bash
   terraform -chdir=terraform output -raw karpenter_talos_values > kubernetes/karpenter/talos-values.secret.yaml
   ```

4. `kubernetes/karpenter/proxmox-config.secret.yaml` uses the same local shared
   Proxmox token. Apply it before Helmfile so the Karpenter chart can mount it:

   ```bash
   kubectl apply -f kubernetes/karpenter/proxmox-config.secret.yaml
   ```

5. Set `KUBERNETES_API_HOST=172.16.0.230`, then use `helmfile/helmfile.yaml` to install Cilium, NFS CSI, cert-manager, and Karpenter Provider for Proxmox. Cilium uses the temporary direct cluster endpoint and requires Talos configuration with `cluster.network.cni.name: none` and `cluster.proxy.disabled: true`.
6. Install the Gateway API v1.6.0 Standard CRDs before applying the Gateway:

   ```bash
   kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/standard-install.yaml
   ```

7. Apply the Kubernetes directories only after their CRDs exist, in this order:

   ```text
   kubernetes/network
   kubernetes/storage
   kubernetes/karpenter
   kubernetes/gateway
   ```

## Public ingress cutover

There is one public IP. This is sufficient: Cilium Gateway API routes by hostname and path after the router forwards TCP 80 and TCP 443 to the one Cilium Gateway LoadBalancer address.

Keep the present router forwards directed at Swarm until the Gateway reports a ready address and a test HTTPRoute works. At cutover, change only the router targets for TCP 80 and TCP 443 from the Swarm VM address to the reserved IP in `kubernetes/network/gateway-ip-pool.yaml`.

## Version lifecycle

- Change `talos_version`, `talos_installer_image`, and the matching Image Factory URL for Talos OS upgrades. Run the sequential `talosctl upgrade` procedure in `UPGRADES.md`; Talos uses image-based upgrades with rollback.
- Change `kubernetes_version` before adding nodes. Upgrade existing Kubernetes nodes with the safe `talosctl upgrade-k8s` procedure in `UPGRADES.md`.
- Change the Karpenter Talos Image Factory URL to create worker drift. Use the
  same schematic and Talos version as Terraform, but use Karpenter's
  uncompressed `nocloud-amd64.raw` artifact. Karpenter replaces workers while it
  respects PodDisruptionBudgets and the NodePool disruption budget.

Review Talos compatibility support before every version change.
