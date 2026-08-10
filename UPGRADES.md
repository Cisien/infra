# Upgrade runbook

This repository pins the Talos and Kubernetes bootstrap versions in `terraform/terraform.tfvars`. The released Terraform Talos provider used by this repository manages initial bootstrap. Use Talos itself for the safe upgrade operations below.

Do not change versions and run an apply during a production upgrade without first following this runbook.

## Preconditions

1. Review the Talos support matrix for the selected Talos and Kubernetes versions.
2. Take an etcd backup.
3. Confirm every workload has a suitable PodDisruptionBudget or can tolerate restart.
4. Write Terraform outputs to local, ignored files:

   ```bash
   terraform -chdir=terraform output -raw talosconfig > ../talosconfig
   terraform -chdir=terraform output -raw kubeconfig > ../kubeconfig
   chmod 600 talosconfig kubeconfig
   ```

5. Use `talosctl health` and `kubectl get nodes` to confirm the cluster is healthy.

## Talos OS upgrade

Upgrade one control-plane node at a time. Wait for `talosctl health` to succeed after each node. This preserves etcd quorum.

```bash
export TALOSCONFIG="$PWD/talosconfig"
export TALOS_IMAGE="ghcr.io/siderolabs/installer:vREPLACE_WITH_TARGET_TALOS_VERSION"

# Repeat one command at a time for cp-01, cp-02, cp-03, then bootstrap worker.
talosctl upgrade --nodes REPLACE_WITH_NODE_IP --image "$TALOS_IMAGE"
talosctl health --nodes REPLACE_WITH_CONTROL_PLANE_IP
```

Talos uses an A/B image layout and can roll back if the new image fails to boot.

## Kubernetes upgrade

First compare the operation without changes:

```bash
export TALOSCONFIG="$PWD/talosconfig"
talosctl upgrade-k8s \
  --nodes REPLACE_WITH_CONTROL_PLANE_IP \
  --to vREPLACE_WITH_TARGET_KUBERNETES_VERSION \
  --dry-run
```

Then run the same operation without `--dry-run`:

```bash
talosctl upgrade-k8s \
  --nodes REPLACE_WITH_CONTROL_PLANE_IP \
  --to vREPLACE_WITH_TARGET_KUBERNETES_VERSION
```

Talos pre-pulls images, updates control-plane components, kube-proxy, and kubelet in sequence, then verifies node health. The operation is restartable if it fails.

## Karpenter worker replacement

After a Talos OS upgrade, update the Talos Image Factory schematic and release
in both locations:

- `terraform/terraform.tfvars` for later fixed-node rebuilds, using
  `nocloud-amd64.raw.xz`;
- `kubernetes/karpenter/proxmox-template.yaml` for elastic workers, using the
  uncompressed `nocloud-amd64.raw` artifact.

Karpenter detects the template change as drift and replaces elastic worker VMs. It respects PodDisruptionBudgets and the NodePool disruption budget. Do not change the worker template until the control plane and bootstrap worker are healthy on the new version.
