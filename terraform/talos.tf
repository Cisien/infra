resource "talos_machine_secrets" "this" {
  talos_version = var.talos_version
}

resource "talos_image_factory_schematic" "proxmox_qemu_guest_agent" {
  schematic = yamlencode({
    customization = {
      systemExtensions = {
        officialExtensions = ["siderolabs/qemu-guest-agent"]
      }
    }
  })
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
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        "$patch"   = "delete"
      }),
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        hostname   = "${var.cluster_name}-${each.key}"
      }),
      yamlencode({
        machine = {
          network = {
            nameservers = each.value.network.nameservers
            interfaces = [{
              deviceSelector = {
                hardwareAddr = lower(proxmox_virtual_environment_vm.fixed_node[each.key].network_device[0].mac_address)
              }
              addresses = ["${each.value.ipv4_address}/${split("/", each.value.network.cidr)[1]}"]
              routes = [{
                network = "0.0.0.0/0"
                gateway = each.value.network.gateway
              }]
            }]
          }
        }
      }),
    ],
    each.value.role == "controlplane" ? concat(
      [
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
      ],
      each.value.network.cidr == var.worker_network.cidr ? [
        yamlencode({
          machine = {
            nodeLabels = {
              "homelab.cisien.com/network" = "vlan-2000"
            }
          }
          cluster = {
            etcd = {
              advertisedSubnets = [each.value.network.cidr]
            }
          }
        }),
      ] : [],
      ) : contains(keys(local.game_nodes), each.key) ? [
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
      ] : [
      yamlencode({
        machine = {
          nodeLabels = {
            "homelab.cisien.com/role"   = "general-worker"
            "node.kubernetes.io/worker" = ""
          }
        }
      }),
    ],
  )
}

resource "talos_machine_configuration_apply" "control_plane" {
  for_each = {
    for name, node in proxmox_virtual_environment_vm.fixed_node : name => node
    if contains(keys(local.control_plane_nodes), name)
  }

  node                        = local.control_plane_nodes[each.key].ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.fixed_node[each.key].machine_configuration
  apply_mode                  = "auto"
}

resource "talos_machine_configuration_apply" "game_worker" {
  for_each = {
    for name, node in proxmox_virtual_environment_vm.fixed_node : name => node
    if contains(keys(local.game_nodes), name)
  }

  node                        = local.game_nodes[each.key].ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.fixed_node[each.key].machine_configuration
  apply_mode                  = "auto"

  depends_on = [talos_machine_bootstrap.this]
}

resource "talos_machine_configuration_apply" "general_worker" {
  for_each = {
    for name, node in proxmox_virtual_environment_vm.fixed_node : name => node
    if contains(keys(local.general_worker_nodes), name)
  }

  node                        = local.general_worker_nodes[each.key].ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.fixed_node[each.key].machine_configuration
  apply_mode                  = "auto"

  depends_on = [talos_machine_bootstrap.this]
}

resource "talos_machine_bootstrap" "this" {
  node                 = var.control_planes[local.bootstrap_node].ipv4_address
  endpoint             = var.control_planes[local.bootstrap_node].ipv4_address
  client_configuration = talos_machine_secrets.this.client_configuration

  lifecycle {
    ignore_changes = [node, endpoint]
  }

  depends_on = [talos_machine_configuration_apply.control_plane]
}

resource "talos_cluster_kubeconfig" "this" {
  node                 = var.control_planes[local.bootstrap_node].ipv4_address
  endpoint             = var.control_planes[local.bootstrap_node].ipv4_address
  client_configuration = talos_machine_secrets.this.client_configuration

  depends_on = [talos_machine_bootstrap.this]
}

output "kubeconfig" {
  description = "Kubeconfig for the new Talos cluster. Keep this secret."
  value       = replace(talos_cluster_kubeconfig.this.kubeconfig_raw, "/server: https:\\/\\/[^[:space:]]+:6443/", "server: ${var.cluster_endpoint}")
  sensitive   = true
}

output "talosconfig" {
  description = "Talos client configuration for the new cluster. Keep this secret."
  value       = data.talos_client_configuration.this.talos_config
  sensitive   = true
}

data "talos_client_configuration" "this" {
  cluster_name         = var.cluster_name
  client_configuration = talos_machine_secrets.this.client_configuration
  endpoints            = local.control_plane_ips
  nodes                = local.control_plane_ips
}
