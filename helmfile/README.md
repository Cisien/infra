# Platform Helm releases

`helmfile.yaml` pins the cluster platform releases. It manages Cilium, NFS CSI, Ceph RBD CSI, Metrics Server, the monitoring stack, Grafana Operator, SNMP exporter, cert-manager, Sealed Secrets, Karpenter Provider for Proxmox, and both GPU operators.

## Use

Set `KUBERNETES_API_HOST` only when the Cilium values template requires the Kubernetes API host. Use a host name or address without a URL scheme or port.

```bash
export KUBERNETES_API_HOST=REPLACE_WITH_API_HOST
helmfile -f helmfile.yaml build
```

Run a reviewed, release-specific synchronization command. Do not run a full synchronization during unrelated work.

## GPU operators

Talos owns host GPU drivers and the NVIDIA container toolkit through Image Factory extensions. The GPU operators manage Kubernetes discovery, device plugins, metrics, and resource advertisement only.

- The NVIDIA operator exposes `nvidia.com/gpu` on the NVIDIA worker.
- The AMD operator exposes `amd.com/gpu` on the AMD worker.
- The NFD worker DaemonSet is restricted to the NVIDIA worker. NFD master and garbage-collection components are central control components.
- GPU-facing DaemonSets select their matching vendor worker and tolerate the dedicated GPU taint.

## Observability

The `monitoring` release provides Prometheus and Grafana. Prometheus uses Ceph RBD claims; it does not use NFS for its time-series database.

Grafana is managed through the Grafana Operator as an external representation of the chart-managed Grafana Service. The Prometheus data source remains chart-managed. GitOps-managed dashboards include cluster, storage, gateway, NAS, and GPU views.

GPU metrics use the NVIDIA DCGM exporter and the AMD metrics exporter. The AMD exporter is discovered by the `amd-gpu-metrics` ServiceMonitor in `kubernetes/apps/metrics-integrations.yaml`. The `GPU Workers` dashboard is declared in `kubernetes/apps/gpu-dashboard.yaml`.

## Prerequisites

Apply required local Secret manifests before the Helm releases that mount them. These files are ignored and must never be committed. Encrypted SealedSecret resources belong under `kubernetes/apps/secrets/` and are applied through the applications Kustomization.

Node Exporter uses host paths and runs in the privileged `monitoring-node-exporter` namespace. Prometheus and Grafana do not require that privileged namespace.
