# Platform Helm releases

This directory pins the Cilium, NFS CSI, Ceph RBD CSI, Metrics Server,
Grafana Operator, kube-prometheus-stack, cert-manager, and Karpenter Provider
for Proxmox charts.

Before a future Helmfile apply, export the Kubernetes API endpoint host without a URL scheme or port:

```bash
export KUBERNETES_API_HOST=172.16.0.230
```

The Cilium values enable Gateway API, L2 announcements, and kube-proxy
replacement for Talos. After changing a Cilium ConfigMap setting, roll the
Cilium agent and operator before validating it; Helm upgrades alone do not
restart their existing Pods. cert-manager installs its CRDs and has Gateway API
HTTP-01 support enabled for the production Let's Encrypt Gateway certificate.

## Observability

Metrics Server runs in `kube-system`. Talos kubelet serving certificates lack
node IP SANs. Metrics Server therefore uses `--kubelet-insecure-tls` when it
scrapes kubelets by InternalIP. Its connection to the Kubernetes API remains
TLS-verified.

`monitoring` is the `kube-prometheus-stack` release namespace. Prometheus has
a single `25Gi` RWO `proxmox-ceph-rbd` claim, `15d` retention, and a `20GiB`
retention size. Grafana uses a separate `5Gi` RWO `proxmox-ceph-rbd` claim.
Neither service uses NFS storage. Helm-generated configuration uses ConfigMaps;
the Grafana administrator credential is `grafana-admin`, created only from the
encrypted `kubernetes/apps/secrets/grafana-admin.sealed.yaml` manifest.
Grafana Operator runs in `grafana-operator` and watches the in-cluster
`monitoring-grafana` Service as an external Grafana instance. It reconciles the
chart-generated default dashboard ConfigMaps through `GrafanaDashboard` CRs and
places them in the `Kubernetes Monitoring` `GrafanaFolder`. The Prometheus
datasource remains provisioned by kube-prometheus-stack so Grafana starts with a
working default datasource during upgrades.

Grafana remains a ClusterIP Service inside the cluster. The separate
`kubernetes/apps/grafana.yaml` HTTPRoute publishes it at
`https://dash.cisien.dev` through the Cilium Gateway. The shared cert-manager
`gateway-system/gateway-tls` certificate includes this hostname. Grafana still
requires its administrator login.

Node Exporter requires host namespaces and host paths. It runs alone in the
privileged `monitoring-node-exporter` namespace; Prometheus and Grafana remain
outside that namespace. Talos controller manager and scheduler metrics bind to
node loopback, so their remote ServiceMonitors are disabled instead of creating
permanently down targets.

Do not run Helmfile until the fixed Talos cluster exists. Apply
`kubernetes/karpenter/proxmox-config.secret.yaml` first because the Karpenter
chart mounts it. The Talos values Secret is needed later, before the Karpenter
Kustomization is applied. See the repository root README for the ordered rollout.
