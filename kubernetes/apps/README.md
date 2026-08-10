# Portainer-to-Kubernetes migration

The migrated workloads, NFS data, and Gateway HTTPRoutes are applied. The
production Let's Encrypt Gateway certificate is active. Router TCP 80 and TCP
443 forward to `172.16.0.240`.

## In-scope running services

| Current service | Kubernetes resources | Public hostname | Persistent source | Target PVC |
| --- | --- | --- | --- | --- |
| `searx_redis` | `searx/redis` | none | tmpfs; no data migration | none |
| `searx_searxng` | `searx/searxng` | `search.cisien.dev` | `/mnt/shared-volumes/searx-searxng` | `searx/config` |
| `wavelog_wavelog-db` | `wavelog/wavelog-db` | none | `/mnt/shared-volumes/wavelog/dbdata` | `wavelog/dbdata` |
| `wavelog_wavelog-main` | `wavelog/wavelog-main` | `wavelog.cisien.dev` | `/mnt/shared-volumes/wavelog/config`, `/uploads`, `/userdata` | `wavelog/config`, `uploads`, `userdata` |

## Open WebUI direct-Docker migration

Open WebUI ran outside Portainer on `192.168.1.167` as Docker container
`open-webui`. Its single named volume, `open-webui`, mounted at
`/app/backend/data` and used 1,227,216 KiB. It was stopped before the SQLite
and vector data were streamed to `open-webui/data`. The source and target
275-file SHA-256 manifests matched exactly.

The initial Kubernetes deployment used the source image
`ghcr.io/open-webui/open-webui:main`, a `2Gi` `nas-nfs` PVC, an encrypted
`runtime-env` SealedSecret, and the existing `ai.cisien.com` Gateway hostname.
The source Docker container remains stopped.

On 2026-08-09, the deployment was moved to the separate `data-rbd` `2Gi` RWO
Ceph RBD PVC. The original `data` NFS PVC remains bound and unchanged as the
point-in-time rollback source. The application still runs one replica.

The application runs as UID:GID `977:988`, which matches the copied data
ownership. Its health endpoint and static assets are available. The upstream
image has root-owned static files and logs non-fatal permission errors when it
tries to refresh default branding assets; a custom image or a root init
container is required to remove those log messages.

### Ceph RBD cutover and rollback

`ceph-csi-rbd` version `3.17.0` is managed by Helmfile in namespace
`ceph-csi-rbd`. Its least-privilege CephX key exists only as the encrypted
`ceph-csi-rbd-secret` SealedSecret. The `proxmox-ceph-rbd` StorageClass uses
`WaitForFirstConsumer`, `ReadWriteOnce`, and `Retain` policies.

Open WebUI was scaled to zero before copy. The complete data tree was copied
from `data` to `data-rbd` with `tar`, preserving UID:GID `977:988`. The two
278-file SHA-256 manifests matched with digest
`0013f44e61e3ef9fbc2ed3b12a5b2c053f4e5032e9602344c3d0e759f523f3ce`.

The NFS claim is a point-in-time rollback only. Do not change the Deployment
back to `data` after users have written new RBD data unless the application is
first stopped and the new state is copied back to NFS. The retained NFS claim
must not be deleted before the RBD trial is accepted.

The original host paths for the three Wavelog application directories are:

```text
/mnt/shared-volumes/wavelog/config
/mnt/shared-volumes/wavelog/uploads
/mnt/shared-volumes/wavelog/userdata
```

All non-Open-WebUI target claims use the existing `nas-nfs` StorageClass. The
claims are bound at `1Gi`, which is larger than the largest copied source
directory. The actual
consistent source sizes at copy time were:

| Data | Source size |
| --- | --- |
| SearXNG config | 60 KiB |
| Wavelog MariaDB | 235,693 KiB |
| Wavelog config | 30 KiB |
| Wavelog uploads | 17,418 KiB |
| Wavelog userdata | 0 KiB |

Wavelog MariaDB is placed on NFS because this migration requires NFS-backed
PVs. The source Wavelog application and database were both scaled to zero
before its raw data directory was copied. The copied database files are owned
by UID:GID `977:988`; the MariaDB workload runs with that identity because the
NFS export rejects the image entrypoint's root-only recursive `chown`. Test
database write latency and the backup/restore procedure before cutover.

## Explicit exclusions

- The user chose to keep Portainer in Swarm. `portainer_portainer`,
  `portainer_agent`, and the Portainer updater are not ported.
- `system_swag` is replaced by the existing Cilium Gateway API and is not
  ported. Its Let’s Encrypt state is not migrated.
- All Portainer services currently desired at zero are excluded: IoT webhook,
  pgAdmin, Meowbot, Paste, BlazeBin, Passbolt and MariaDB, WeatherLink IoT,
  Authelia, Grafana, Prometheus, InfluxDB, Chronograf, and UniFi Poller.
- The `octo.cisien.dev` SWAG configuration refers to `octoprint` and
  `mjpg-streamer`, but neither has a current Swarm service, running container,
  or resolved external address. No Kubernetes route is created for it.

## SWAG routes whose backends remain external

`external-services.yaml` replaces these SWAG reverse-proxy routes with an
`HTTPRoute` and a selector-free Service plus EndpointSlice. It also keeps the
GitLab HTTPS upstream through a small NGINX proxy deployment.

| Hostname | Current upstream | Discovery result |
| --- | --- | --- |
| `dash.cisien.dev` | `172.16.0.250:4080` | TCP probe timed out; address is not in current Proxmox guest inventory. |
| `ha.cisien.com` | `192.168.1.111:8123` | Home Assistant VM; HTTP 200. |
| `gitlab.cisien.com` | `172.16.0.190:443` | GitLab LXC is stopped; HTTPS probe timed out. |
| `ai.cisien.com` | `192.168.1.167:80` | LLM VM; HTTP 200. |
| `cloud.cisien.com` | `172.16.0.253:11000` | Nextcloud VM; HTTP 302. |

The current `cloud.cisien.com` CardDAV and CalDAV redirects are preserved.
The external endpoint addresses must be re-tested before application.

## Completed data migration

A temporary Swarm service mounted the live named volumes read-only and the
Kubernetes NFS export read-write. It copied each directory with `tar`, then ran
`diff -qr` between every source and target directory. All five comparisons
succeeded. The target PVC directories are the directories identified by the
bound PV volume handles.

The temporary Swarm migration services were removed after the copy. The four
migrated Swarm services remain scaled to zero:

```text
searx_searxng
searx_redis
wavelog_wavelog-main
wavelog_wavelog-db
```

Before cutover:

1. Start and validate the Kubernetes workloads using the local Gateway address.
2. Run the curl commands in the pre-cutover validation section.
3. Change router forwards only after the local tests pass.
4. Keep the Swarm services at zero unless rollback is required.

## Sealed secrets

The Sealed Secrets Helm release is installed and healthy in `kube-system`.
The generated `wavelog/db-env` and `wavelog/app-env` SealedSecrets are applied
and report `Synced=True`. Their encrypted manifests are included in this
Kustomization.

To regenerate them after a source credential change, run from the repository
root:

```bash
export PORTAINER_URL=https://portainer.cisien.dev
export PORTAINER_API_KEY='read from your secret store'
python3 kubernetes/apps/scripts/port-wavelog-secrets.py
kubectl apply -f kubernetes/apps/secrets/wavelog-db-env.sealed.yaml
kubectl apply -f kubernetes/apps/secrets/wavelog-app-env.sealed.yaml
```

The script reads only the current Wavelog service environment, creates each
plain Kubernetes Secret in memory, and sends it directly to `kubeseal`. It
never writes a plain secret to the repository or disk. The output SealedSecret
files are safe to commit and must be applied before `wavelog.yaml`.

## Gateway validation

The Gateway has a publicly trusted certificate. To test the Gateway address
without depending on split DNS, use explicit address resolution without `-k`:

```bash
curl --resolve search.cisien.dev:443:172.16.0.240 https://search.cisien.dev/
curl --resolve wavelog.cisien.dev:443:172.16.0.240 https://wavelog.cisien.dev/
curl --resolve ha.cisien.com:443:172.16.0.240 https://ha.cisien.com/
curl --resolve cloud.cisien.com:443:172.16.0.240 https://cloud.cisien.com/
```

`dash.cisien.dev` and `gitlab.cisien.com` currently have no active Kubernetes
backend and return Gateway 404 responses. `ai.cisien.com` routes to the active
Open WebUI deployment. Use `curl -I` for redirect checks on the Nextcloud
well-known paths.
