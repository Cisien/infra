# Karpenter Provider for Proxmox

This directory declares elastic Talos workers for Karpenter Provider for Proxmox.

## Current design

- `ProxmoxTemplate` uses an uncompressed Talos Image Factory raw image on `local` storage.
- Worker boot disks use `local-storage-pool`.
- The NodePool permits only the configured Proxmox zones and instance types.
- Provider-local IPAM allocates worker addresses from the reserved worker CIDR in `proxmox-template.yaml`.
- UniFi DHCP must not allocate from the provider-local IPAM range.
- NFS exports must allow the worker range before a PVC-backed workload can run.

## Required local inputs

Two plain Secret files are ignored and must be supplied locally:

- `proxmox-config.secret.yaml`: dedicated least-privilege Proxmox credentials for the provider.
- `talos-values.secret.yaml`: sensitive Talos values generated after fixed-cluster bootstrap.

Use the tracked `*.secret.example.yaml` files as schemas. Do not commit the generated files.

## Apply order

1. Apply the local Proxmox configuration Secret before the Karpenter Helm release.
2. Install or update the Karpenter Provider for Proxmox release through Helmfile.
3. Apply this Kustomization after the provider CRDs and Talos values Secret exist.
4. Verify NodeClaim conditions and Kubernetes Node readiness before relying on elastic capacity.

Do not treat a launched Proxmox VM as a usable worker. Confirm Talos registration, Cilium, storage access, and Kubernetes readiness.
