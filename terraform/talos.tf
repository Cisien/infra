resource "talos_machine_secrets" "this" {
  talos_version = var.talos_version
}

data "talos_machine_configuration" "fixed_node" {
  for_each = local.fixed_nodes

  cluster_name       = var.cluster_name
  cluster_endpoint   = var.cluster_endpoint
  machine_type       = each.value.role
  machine_secrets    = talos_machine_secrets.this.machine_secrets
  kubernetes_version = var.kubernetes_version
  talos_version      = var.talos_version

  config_patches = concat(
    [
      yamlencode(local.talos_network_patch),
      yamlencode({
        machine = {
          network = {
            interfaces = [{
              interface = "eth0"
              addresses = ["${each.value.ipv4_address}/${split("/", var.network.cidr)[1]}"]
              routes = [{
                network = "0.0.0.0/0"
                gateway = var.network.gateway
              }]
            }]
          }
        }
      }),
    ],
    each.value.role == "controlplane" ? [
      yamlencode({
        cluster = {
          etcd = {
            extraArgs = {
              listen-metrics-urls = "http://0.0.0.0:2381"
            }
          }
        }
      }),
      yamlencode({
        cluster = {
          allowSchedulingOnControlPlanes = false
        }
      }),
      ] : [
      yamlencode({
        machine = {
          nodeLabels = {
            "games.cisien.com/role" = "palworld"
          }
          kubelet = {
            extraArgs = {
              "register-with-taints" = "games.cisien.com/dedicated=palworld:NoSchedule"
            }
          }
        }
      }),
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "UserVolumeConfig"
        name       = "game-data"
        volumeType = "directory"
      }),
    ],
  )
}

resource "talos_machine_configuration_apply" "control_plane" {
  for_each = var.control_planes

  node                        = each.value.ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.fixed_node[each.key].machine_configuration
  apply_mode                  = "auto"

  depends_on = [proxmox_virtual_environment_vm.fixed_node]
}

resource "talos_machine_configuration_apply" "game_worker" {
  for_each = local.game_nodes

  node                        = each.value.ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.fixed_node[each.key].machine_configuration
  apply_mode                  = "auto"

  depends_on = [
    proxmox_virtual_environment_vm.fixed_node,
    talos_machine_bootstrap.this,
  ]
}

resource "talos_machine_bootstrap" "this" {
  node                 = var.control_planes[local.bootstrap_node].ipv4_address
  endpoint             = var.control_planes[local.bootstrap_node].ipv4_address
  client_configuration = talos_machine_secrets.this.client_configuration

  depends_on = [talos_machine_configuration_apply.control_plane]
}

resource "talos_cluster_kubeconfig" "this" {
  node                 = var.control_planes[local.bootstrap_node].ipv4_address
  endpoint             = var.control_planes[local.bootstrap_node].ipv4_address
  client_configuration = talos_machine_secrets.this.client_configuration

  depends_on = [talos_machine_bootstrap.this]
}

locals {
  karpenter_talos_values = yamlencode({
    apiVersion = "v1"
    kind       = "Secret"
    metadata = {
      name      = "karpenter-talos-values"
      namespace = "kube-system"
    }
    type = "Opaque"
    stringData = {
      machineCA       = talos_machine_secrets.this.machine_secrets.certs.os.cert
      machineToken    = talos_machine_secrets.this.machine_secrets.trustdinfo.token
      clusterID       = talos_machine_secrets.this.machine_secrets.cluster.id
      clusterSecret   = talos_machine_secrets.this.machine_secrets.cluster.secret
      clusterEndpoint = var.cluster_endpoint
      clusterName     = var.cluster_name
      kubeletVersion  = var.kubernetes_version
      talosVersion    = var.talos_version
    }
  })
}

output "kubeconfig" {
  description = "Kubeconfig for the new Talos cluster. Keep this secret."
  value       = talos_cluster_kubeconfig.this.kubeconfig_raw
  sensitive   = true
}

output "talosconfig" {
  description = "Talos client configuration for the new cluster. Keep this secret."
  value       = data.talos_client_configuration.this.talos_config
  sensitive   = true
}

output "karpenter_talos_values" {
  description = "Write this sensitive output to kubernetes/karpenter/talos-values.secret.yaml after the initial Talos apply."
  value       = local.karpenter_talos_values
  sensitive   = true
}

data "talos_client_configuration" "this" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.this.client_configuration
  endpoints            = local.control_plane_ips
  nodes                = local.control_plane_ips
}
