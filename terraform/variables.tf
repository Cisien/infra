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
  description = "Kubernetes version embedded into the initial Talos machine configuration and Karpenter worker template. Use the documented talosctl upgrade-k8s workflow for existing nodes."
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
