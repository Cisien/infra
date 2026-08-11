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
