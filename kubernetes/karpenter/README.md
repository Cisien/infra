# Karpenter Proxmox configuration

The provider runs in a Kubernetes Pod. Configure its Proxmox API URL with a
numeric address that Pods can resolve and reach. Use `share` for the Talos raw
source image because `local-storage-pool` is ZFS-backed and cannot store image
imports. The worker boot disks still use `local-storage-pool`.

This directory uses the provider's Talos worker template pattern.

Required ignored Secret files:

- `proxmox-config.secret.yaml`: copy the example and add a dedicated least-privilege Karpenter Proxmox token.
- `talos-values.secret.yaml`: generate it from the sensitive Terraform output after the fixed Talos cluster bootstrap.

Before applying this directory:

1. Set the uncompressed Talos Image Factory raw URL in `proxmox-template.yaml`.
2. Confirm `local-storage-pool` accepts the Karpenter template image and VM disk contents on `pve-02` and `pve-03`, and that its template status lists only those zones.
3. Set NodePool limits below actual usable PVE capacity.
4. The template omits `address4`, so workers use DHCP. Keep `.230–.233` and
   `.240` outside that DHCP scope.
5. Confirm the NAS NFS export permits worker source addresses before workloads
   use PVCs.

Apply `proxmox-config.secret.yaml` directly before Helmfile. The Karpenter
Kustomization applies both ignored Secrets again after Terraform generates
`talos-values.secret.yaml`.

The first workload node is created only after a Pod cannot schedule onto the bootstrap worker.
