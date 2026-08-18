# Homelab Infrastructure

This repository defines the desired state for a Talos Linux Kubernetes homelab on Proxmox.

It is infrastructure source code, not a turnkey installer. It assumes that the operator has access to the Proxmox environment, the Talos cluster, and the local secret files that are intentionally not versioned.

## What this repository manages

- Fixed Talos control-plane and general worker nodes through OpenTofu.
- Dedicated physical NVIDIA and AMD Talos GPU workers.
- Cilium networking and Gateway API ingress.
- NFS CSI and Ceph RBD storage integration.
- Platform Helm releases, monitoring, Grafana, and cert-manager.
- Kubernetes applications, dashboards, external-service routes, and SealedSecret manifests.

The cluster currently has three control-plane nodes, two general workers, and three dedicated GPU workers. The NVIDIA GB10 advertises two time-sliced shared GPU resources; the vendor operators advertise the remaining NVIDIA and AMD resources.

## Repository layout

| Path | Purpose |
| --- | --- |
| `terraform/` | Proxmox, Talos bootstrap, and physical GPU-worker definitions. |
| `helmfile/` | Version-pinned platform Helm releases and values. |
| `kubernetes/apps/` | Application manifests, observability resources, dashboards, and SealedSecrets. |
| `kubernetes/network/` | Cilium LoadBalancer and L2 announcement resources. |
| `kubernetes/gateway/` | Gateway API and certificate resources. |
| `kubernetes/storage/` | StorageClass resources and examples. |

## Documentation

- `TALOS_AI_WORKER_INSTALL.md`: physical GPU-worker installation and recovery procedure.
- `UPGRADES.md`: Talos, Kubernetes, worker, and GPU-worker upgrade procedure.
- `helmfile/README.md`: platform release and observability notes.
- `kubernetes/apps/README.md`: current application and dashboard inventory.
- `kubernetes/apps/secrets/README.md`: SealedSecret policy.

## Secrets and local state

Do not commit credentials, generated kubeconfig files, Talos configuration, Terraform state, or plain Kubernetes Secrets.

The repository tracks encrypted `SealedSecret` manifests. Local inputs such as `terraform.tfvars`, `kubeconfig`, `talosconfig`, `.env` files, and plain Secret manifests are ignored. Pre-commit hooks run Gitleaks, private-key detection, and AWS credential detection before each commit.

## Validation

Run validation before applying a change:

```bash
pre-commit run --all-files
tofu -chdir=terraform fmt -check -recursive
tofu -chdir=terraform validate
helmfile -f helmfile/helmfile.yaml build
kubectl kustomize kubernetes/apps
```

Use a reviewed, component-specific apply or Helmfile synchronization command. Do not apply the whole repository to a production cluster without checking prerequisites, release dependencies, and the current cluster state.

## GPU design

Talos Image Factory extensions provide host GPU drivers and the NVIDIA container toolkit. The NVIDIA and AMD GPU operators provide Kubernetes discovery, device plugins, metrics, and resource advertisement. They do not manage host drivers.

GPU workloads must select the matching vendor node, tolerate the dedicated GPU taint, and request the vendor resource. Model data on GPU workers is node-local and is not highly available.
