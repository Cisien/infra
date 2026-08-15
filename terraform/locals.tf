locals {
  control_plane_nodes = {
    for name, node in var.control_planes : name => merge(node, var.control_plane_resources, { role = "controlplane" })
  }

  game_nodes = {
    game-01 = merge(var.game_worker, { role = "worker" })
  }

  fixed_nodes = merge(local.control_plane_nodes, local.game_nodes)

  # Talos images download to the shared file-based Proxmox storage with import
  # content enabled. The VM boot disks remain on each node's zfspool storage.
  proxmox_image_storage = {
    for proxmox_node in toset([for node in values(local.fixed_nodes) : node.proxmox_node]) : proxmox_node => "share"
  }

  control_plane_ips = [for node in values(var.control_planes) : node.ipv4_address]
  bootstrap_node    = sort(keys(var.control_planes))[0]

  talos_network_patch = {
    machine = {
      install = {
        disk  = "/dev/sda"
        image = var.talos_installer_image
      }
      network = {
        nameservers = var.network.nameservers
      }
    }
    cluster = {
      network = {
        cni = {
          name = "none"
        }
      }
      proxy = {
        disabled = true
      }
    }
  }
}
