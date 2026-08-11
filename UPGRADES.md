# Upgrade runbook

Use this runbook for a reviewed Talos or Kubernetes upgrade. Upgrade one failure domain at a time and stop when a health check fails.

## Preconditions

1. Review the Talos and Kubernetes compatibility matrix.
2. Take and verify an etcd backup.
3. Confirm all Nodes are Ready and required workloads are healthy.
4. Confirm the current `talosconfig` and `kubeconfig` are local, protected, and ignored by Git.
5. Review PodDisruptionBudgets and storage dependencies.
6. Render the affected OpenTofu, Helmfile, and Kustomize changes before applying them.

## Talos OS upgrade

Upgrade control-plane nodes sequentially. Wait for cluster health after each node so etcd quorum remains available.

```bash
export TALOSCONFIG="$PWD/talosconfig"
talosctl upgrade --nodes REPLACE_WITH_NODE --image REPLACE_WITH_INSTALLER_IMAGE
talosctl health --nodes REPLACE_WITH_CONTROL_PLANE
```

Do not use one generic installer image for the physical GPU workers. Their Talos Image Factory schematics include vendor-specific extensions. The AMD schematic also includes required UMA and IOMMU kernel arguments.

For each physical GPU worker:

1. Build or select the matching vendor-specific Image Factory installer from the OpenTofu configuration.
2. Upgrade one GPU worker at a time.
3. Confirm the node is Ready, the vendor resource is still advertised, and the matching GPU operator Pods are healthy.
4. Confirm Prometheus target health and the GPU dashboard metrics after the upgrade.

For elastic workers, update the Karpenter Talos template only after the control plane is healthy. Karpenter replaces drifted workers according to its disruption policy.

## Kubernetes upgrade

First inspect the operation:

```bash
export TALOSCONFIG="$PWD/talosconfig"
talosctl upgrade-k8s \
  --nodes REPLACE_WITH_CONTROL_PLANE \
  --to vREPLACE_WITH_TARGET_KUBERNETES_VERSION \
  --dry-run
```

Then run the reviewed operation without `--dry-run`. When Cilium runs with kube-proxy disabled, inspect the manifest inventory. If it proposes only obsolete kube-proxy removals, use `--manifests-no-prune` to preserve the existing inventory during the upgrade.

## Post-upgrade checks

1. Confirm every Node is Ready.
2. Confirm Cilium, CSI, cert-manager, monitoring, and GPU operator workloads are healthy.
3. Confirm Prometheus targets and Grafana dashboards return current data.
4. Confirm a PVC-backed application can mount its expected storage.
5. Record the new version source and run the repository validation commands before committing it.
