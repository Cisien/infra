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

## Split-horizon ExternalDNS

Public `.com` Gateway names use two DNS views:

- HE public DNS stores CNAMEs to `cable.cisien.com`, which tracks the dynamic public address.
- AdGuard Home at `192.168.1.2` stores A rewrites to the public Gateway address `172.16.200.254` for LAN clients.

Internal service names are not published in HE DNS. AdGuard stores individual A rewrites for `.local.cisien.com` names to the internal Gateway at `172.16.200.253`. The wildcard certificate does not create a wildcard DNS record.

The two ExternalDNS Helm releases use CRD sources only and label filters:

- `external-dns-public` manages `dns.cisien.com/scope=public-he` CNAME endpoints in HE.
- `external-dns-adguard` manages `dns.cisien.com/scope=adguard` A endpoints in AdGuard Home.

Add explicit `DNSEndpoint` objects in `adguard-dns-endpoints.yaml` before publishing a new Gateway hostname. Keep the HE and AdGuard objects separate. Both releases use `upsert-only` and a 24-hour polling interval with event-triggered reconciliation. The HE webhook uses separate ExternalDNS credentials from cert-manager; cert-manager continues to manage only ACME TXT records.

## Storage policy

Application storage uses the StorageClass selected by each manifest. Prometheus and Grafana use Ceph RBD. GPU-worker model storage is a static, retained local PV on its matching physical node. It has no failover capability.

## Observability policy

The `GPU Workers` Grafana dashboard uses metrics from NVIDIA DCGM and the AMD exporter. Do not create dashboards only in the Grafana UI. Add durable dashboards as `GrafanaDashboard` resources.

## Secrets policy

Do not put a plain `Secret`, kubeconfig, API token, or password in this directory. Store encrypted SealedSecret manifests in `secrets/`. See `secrets/README.md` for the generation policy.

## AI inference policy

The `ai` namespace has three separate layers:

- `oci-registry` is the internal Zot OCI registry with its web UI. Its data PVC uses `nas-nfs`.
- `litellm` is the stable OpenAI-compatible text gateway. It maps public model names to internal runtime Services. The internal Gateway is available at `http://litellm.local.cisien.com/v1` and `https://litellm.local.cisien.com/v1`; it uses `172.16.200.253`, has no HTTP redirect, and uses a publicly trusted wildcard certificate issued through the HE DNS-01 webhook. It is separate from the public Gateway address `172.16.200.254`.
- `litellm-db` is the retained PostgreSQL backend for LiteLLM UI users, keys, and spend data. LiteLLM requires `DATABASE_URL` for UI authentication; the database credentials and URL are SealedSecrets, and the database uses the retained `proxmox-ceph-rbd` StorageClass.
- Each runtime is its own Deployment and Service. Runtime flags, images, GPU placement, and model artifacts are explicit in its manifest.

The active aliases are `incompetent-robot`, `robot`, `robot-laguna`, and `gemma-classifier`. `gemma-classifier` is the always-on small AMD model for simple requests and request classification. Model blobs are OCI artifacts in `ai.cisien.com/ai-models`. Each runtime init container copies its selected immutable tag to a retained node-local cache before it starts llama.cpp.

All GPU runtime Deployments start at zero replicas. This prevents an incomplete model import from starting a Pod. The AMD runtimes use the shared `ai/shared-amd-gpu` Dynamic Resource Allocation claim, so independent AMD Pods can share the same physical GPU. The GB10 exposes two `nvidia.com/gpu.shared` time-sliced resources; use its `ai.cisien.com/accelerator: gb10` selector with one shared-GPU request per Pod. GPU memory and compute contention remain application-level concerns. Set any combination of `amd-qwen`, `amd-laguna`, or `flux-image` to one replica when testing concurrent access. `nvidia-qwopus` can run independently on both NVIDIA GPUs.

The AMD GPU Operator uses its DRA driver instead of the legacy device plugin. The DRA driver is pinned to `rocm/k8s-gpu-dra-driver:v1.0.1`; the `latest` image is not used because it published an invalid empty driver-version attribute on this Talos host. AMD workloads must tolerate the GPU taint and target the existing AMD node.

Use `registry.cisien.com` for OCI clients. It is separate from `ai.cisien.com`, which belongs to Open WebUI. The registry requires the `registry` account stored in the `oci-registry-client` Secret. Do not copy that Secret into source control.

The NAS NFSv3 rpcbind lookup is not reachable from worker VLANs. The `nas-nfs` StorageClass pins the verified TCP NFS and mountd ports. If the NAS changes its mountd port after a restart, get its current TCP mountd port with `rpcinfo -p 192.168.1.250`, then update both the StorageClass and each affected PV `spec.mountOptions` before creating or remounting workloads.
