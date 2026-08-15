resource "proxmox_download_file" "talos_nocloud" {
  for_each = local.proxmox_image_storage

  node_name    = each.key
  datastore_id = each.value
  content_type = "import"
  file_name    = "${var.cluster_name}-${replace(var.talos_version, ".", "-")}-nocloud-amd64.raw"
  url          = replace(var.talos_image_url, ".raw.xz", ".raw")
  overwrite    = false
}

resource "proxmox_virtual_environment_vm" "fixed_node" {
  for_each = local.fixed_nodes

  name        = "${var.cluster_name}-${each.key}"
  description = "Talos ${each.value.role}; managed by Terraform"
  tags        = ["kubernetes", "talos", each.value.role, "terraform"]
  node_name   = each.value.proxmox_node
  vm_id       = each.value.vm_id
  on_boot     = true

  agent {
    enabled = false
  }

  cpu {
    cores = each.value.cpu_cores
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = each.value.memory_mb
  }

  scsi_hardware = "virtio-scsi-single"

  disk {
    datastore_id = each.value.storage_pool
    import_from  = proxmox_download_file.talos_nocloud[each.value.proxmox_node].id
    interface    = "scsi0"
    file_format  = "raw"
    iothread     = true
    ssd          = true
    size         = each.value.disk_gb
  }

  initialization {
    datastore_id = each.value.storage_pool

    ip_config {
      ipv4 {
        address = "${each.value.ipv4_address}/${split("/", var.network.cidr)[1]}"
        gateway = var.network.gateway
      }
    }

    dns {
      servers = var.network.nameservers
    }
  }

  network_device {
    bridge  = var.network.bridge
    model   = "virtio"
    vlan_id = try(var.network.vlan_id, null)
  }

  operating_system {
    type = "l26"
  }

  serial_device {}

  vga {
    type = "serial0"
  }
}
