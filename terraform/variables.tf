variable "cluster_name" {
  description = "DNS-safe Talos cluster name."
  type        = string
  default     = "homelab"
}

variable "proxmox_endpoint" {
  description = "Proxmox API endpoint, including port 8006."
  type        = string
  default     = "https://pve.local.cisien.com:8006/"
}

variable "proxmox_api_token" {
  description = "Dedicated Proxmox API token in user@realm!token=secret format. Never commit it."
  type        = string
  sensitive   = true
}

variable "proxmox_insecure" {
  description = "Allow the Proxmox endpoint's current self-signed TLS certificate."
  type        = bool
  default     = true
}

variable "talos_version" {
  description = "Talos release used for generated machine configuration and OS upgrades."
  type        = string
  default     = "v1.13.8"
}

variable "kubernetes_version" {
  description = "Kubernetes version embedded into the initial Talos machine configuration. Use the documented talosctl upgrade-k8s workflow for existing nodes."
  type        = string
  default     = "v1.36.3"
}

variable "talos_image_url" {
  description = "Talos nocloud amd64 raw image URL from Talos Image Factory. Use the Factory raw.xz URL form shown in terraform.tfvars.example; it must match talos_version."
  type        = string
}

variable "talos_installer_image" {
  description = "Talos installer image used for the initial install and later in-place OS upgrades."
  type        = string
  default     = "ghcr.io/siderolabs/installer:v1.13.8"
}

variable "cluster_endpoint" {
  description = "Stable Kubernetes API endpoint. Use a LAN DNS name or a virtual IP, not a control-plane node address."
  type        = string
}

variable "network" {
  description = "IPv4 network data shared by Talos control-plane and bootstrap-worker machine configurations."
  type = object({
    gateway     = string
    nameservers = list(string)
    cidr        = string
    bridge      = string
    vlan_id     = optional(number)
  })
}

variable "control_plane_network" {
  description = "Network data for fixed Talos control-plane VMs. Keep the current LAN values until the staged VLAN control-plane migration is complete."
  type = object({
    gateway     = string
    nameservers = list(string)
    cidr        = string
    bridge      = string
    vlan_id     = optional(number)
  })
  default = {
    gateway     = "172.16.0.1"
    nameservers = ["192.168.1.2"]
    cidr        = "172.16.0.0/24"
    bridge      = "vmbr0"
  }
}

variable "control_planes" {
  description = "Exactly three fixed Talos control-plane VMs. Spread these across the usable PVE VM hosts."
  type = map(object({
    proxmox_node = string
    storage_pool = string
    ipv4_address = string
    vm_id        = number
  }))

  validation {
    condition     = length(var.control_planes) == 3
    error_message = "Define exactly three control-plane VMs for etcd quorum."
  }
}

variable "temporary_control_planes" {
  description = "Temporary VLAN control-plane replacements. Use only during a staged migration, then move these entries into control_planes and remove the old control planes."
  type = map(object({
    proxmox_node = string
    storage_pool = string
    ipv4_address = string
    vm_id        = number
  }))
  default = {}
}

variable "control_plane_resources" {
  description = "Resource allocation for each fixed control-plane VM."
  type = object({
    cpu_cores = number
    memory_mb = number
    disk_gb   = number
  })
  default = {
    cpu_cores = 4
    memory_mb = 8192
    disk_gb   = 80
  }
}

variable "game_worker" {
  description = "Fixed Talos worker for the Palworld server. Its local SSD-backed disk stores non-HA game state."
  type = object({
    proxmox_node = string
    storage_pool = string
    ipv4_address = string
    vm_id        = number
    cpu_cores    = number
    memory_mb    = number
    disk_gb      = number
  })
  default = {
    proxmox_node = "pve-04"
    storage_pool = "ssd-pool"
    ipv4_address = "172.16.0.233"
    vm_id        = 2401
    cpu_cores    = 8
    memory_mb    = 32768
    disk_gb      = 200
  }
}

variable "game_worker_network" {
  description = "Network data for the fixed Palworld worker."
  type = object({
    gateway     = string
    nameservers = list(string)
    cidr        = string
    bridge      = string
    vlan_id     = optional(number)
  })

  default = {
    gateway     = "172.16.200.1"
    nameservers = ["192.168.1.2"]
    cidr        = "172.16.200.0/24"
    bridge      = "workvnet"
  }
}

variable "general_workers" {
  description = "Two fixed Talos workers for ordinary Kubernetes workloads, with one VM on pve-02 and one VM on pve-03."
  type = map(object({
    proxmox_node = string
    storage_pool = string
    ipv4_address = string
    vm_id        = number
    cpu_cores    = number
    memory_mb    = number
    disk_gb      = number
  }))

  default = {
    worker-01 = {
      proxmox_node = "pve-02"
      storage_pool = "local-storage-pool"
      ipv4_address = "172.16.200.195"
      vm_id        = 2201
      cpu_cores    = 4
      memory_mb    = 8192
      disk_gb      = 80
    }
    worker-02 = {
      proxmox_node = "pve-03"
      storage_pool = "local-storage-pool"
      ipv4_address = "172.16.200.196"
      vm_id        = 2202
      cpu_cores    = 4
      memory_mb    = 8192
      disk_gb      = 80
    }
  }

  validation {
    condition     = length(var.general_workers) == 2 && toset([for worker in values(var.general_workers) : worker.proxmox_node]) == toset(["pve-02", "pve-03"])
    error_message = "Define exactly two general workers, one on pve-02 and one on pve-03."
  }
}

variable "worker_network" {
  description = "Network data for fixed general workers on the routed VLAN 2000 worker network."
  type = object({
    gateway     = string
    nameservers = list(string)
    cidr        = string
    bridge      = string
  })

  default = {
    gateway     = "172.16.200.1"
    nameservers = ["192.168.1.2"]
    cidr        = "172.16.200.0/24"
    bridge      = "workvnet"
  }
}
