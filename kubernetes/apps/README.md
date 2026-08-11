# Kubernetes applications and integrations

This directory is a Kustomize root for workloads, observability resources, application routes, local GPU storage, and encrypted SealedSecrets.

## Included resources

| Area | Main resources |
| --- | --- |
| Applications | SearXNG, Wavelog, Open WebUI, and AREDN resources. |
| Storage | Ceph RBD StorageClass and node-local AI storage resources. |
| Observability | Grafana integration, ServiceMonitors, dashboards, and SNMP integration. |
| Networking | External-service routes and application HTTPRoutes. |
| GPU | AMD DeviceConfig, AMD node metadata, and the GPU Workers dashboard. |
| Secrets | Encrypted SealedSecrets only. |

The temporary llama GPU smoke deployment is intentionally not retained. Use a reviewed, vendor-specific workload when a future GPU validation is needed.

## Validate

```bash
kubectl kustomize .
kubectl apply --dry-run=server -k .
```

The target cluster must already contain the CRDs for Grafana Operator, Prometheus Operator, Gateway API, and the AMD GPU operator. A server-side dry run does not create a Namespace for other resources in the same request.

## Storage policy

Application storage uses the StorageClass selected by each manifest. Prometheus and Grafana use Ceph RBD. GPU-worker model storage is a static, retained local PV on its matching physical node. It has no failover capability.

## Observability policy

The `GPU Workers` Grafana dashboard uses metrics from NVIDIA DCGM and the AMD exporter. Do not create dashboards only in the Grafana UI. Add durable dashboards as `GrafanaDashboard` resources.

## Secrets policy

Do not put a plain `Secret`, kubeconfig, API token, or password in this directory. Store encrypted SealedSecret manifests in `secrets/`. See `secrets/README.md` for the generation policy.

## AI inference policy

The `ai` namespace has three separate layers:

- `oci-registry` is the internal OCI Distribution registry. Its data PVC uses `nas-nfs`.
- `litellm` is the stable OpenAI-compatible text gateway. It maps public model names to internal runtime Services. The LAN-only internal Gateway is available at `http://litellm.local.cisien.com/v1` and `https://litellm.local.cisien.com/v1`; it uses `172.16.0.239`, has no HTTP redirect, and uses a publicly trusted wildcard certificate issued through the HE DNS-01 webhook. It is separate from the public Gateway address `172.16.0.240`.
- Each runtime is its own Deployment and Service. Runtime flags, images, GPU placement, and model artifacts are explicit in its manifest.

The active aliases are `incompetent-robot`, `robot`, and `robot-laguna`. Model blobs are OCI artifacts in `ai.cisien.com/ai-models`. Each runtime init container copies its selected immutable tag to a retained node-local cache before it starts llama.cpp.

All GPU runtime Deployments start at zero replicas. This prevents an incomplete model import from starting a Pod. It also prevents two AMD workloads from claiming the one AMD GPU. Set exactly one of `amd-qwen`, `amd-laguna`, or `flux-image` to one replica when that workload must run. `nvidia-qwopus` can run independently on both NVIDIA GPUs.

Use `registry.cisien.com` for OCI clients. It is separate from `ai.cisien.com`, which belongs to Open WebUI. The registry requires the `registry` account stored in the `oci-registry-client` Secret. Do not copy that Secret into source control.

The NAS NFSv3 rpcbind lookup is not reachable from worker VLANs. The `nas-nfs` StorageClass pins the verified TCP NFS and mountd ports. If the NAS changes its mountd port after a restart, get its current TCP mountd port with `rpcinfo -p 192.168.1.250`, then update both the StorageClass and each affected PV `spec.mountOptions` before creating or remounting workloads.
