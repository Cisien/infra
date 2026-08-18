variable "physical_ai_workers" {
  description = "Dedicated bare-metal Talos GPU workers. The management network is VLAN 2000 and the system NVMe also stores the Talos user volume."
  type = map(object({
    ipv4_address = string
    mac_address  = string
    gpu_vendor   = string
    accelerator  = string
    install_disk = string
  }))

  default = {
    ai-nvidia-01 = {
      ipv4_address = "172.16.200.105"
      mac_address  = "3c:7c:3f:21:8d:37"
      gpu_vendor   = "nvidia"
      accelerator  = "rtx-3090"
      install_disk = "/dev/nvme0n1"
    }
    ai-amd-01 = {
      ipv4_address = "172.16.200.106"
      mac_address  = "38:05:25:36:87:02"
      gpu_vendor   = "amd"
      accelerator  = "radeon-8060s"
      install_disk = "/dev/nvme0n1"
    }
    ai-nvidia-02 = {
      ipv4_address = "172.16.200.107"
      mac_address  = "30:c5:99:40:2c:8c"
      gpu_vendor   = "nvidia"
      accelerator  = "gb10"
      install_disk = "/dev/nvme0n1"
    }
  }

  validation {
    condition     = alltrue([for node in values(var.physical_ai_workers) : contains(["amd", "nvidia"], node.gpu_vendor)])
    error_message = "Each physical AI worker must use gpu_vendor amd or nvidia."
  }
}

variable "physical_ai_network" {
  description = "Layer-3 data for the untagged VLAN 2000 switch ports used by physical AI workers."
  type = object({
    cidr        = string
    gateway     = string
    nameservers = list(string)
  })

  default = {
    cidr        = "172.16.200.0/24"
    gateway     = "172.16.200.1"
    nameservers = ["192.168.1.2"]
  }
}

locals {
  physical_ai_extensions = {
    nvidia = [
      "siderolabs/nonfree-kmod-nvidia",
      "siderolabs/nvidia-container-toolkit",
    ]
    amd = [
      "siderolabs/amdgpu",
      "siderolabs/amd-ucode",
    ]
  }

  physical_ai_taint = "ai.cisien.com/gpu"
}

resource "talos_image_factory_schematic" "physical_ai_worker" {
  for_each = var.physical_ai_workers

  schematic = yamlencode({
    customization = merge(
      {
        systemExtensions = {
          officialExtensions = local.physical_ai_extensions[each.value.gpu_vendor]
        }
      },
      each.value.gpu_vendor == "amd" ? {
        extraKernelArgs = [
          "amdgpu.gttsize=131072",
          "ttm.pages_limit=33554432",
          "amd_iommu=on",
          "iommu=pt",
        ]
        } : each.value.accelerator == "gb10" ? {
        extraKernelArgs = ["arm64.nobti"]
      } : {},
    )
  })
}

data "talos_machine_configuration" "physical_ai_worker" {
  for_each = var.physical_ai_workers

  cluster_name       = var.cluster_name
  cluster_endpoint   = var.cluster_endpoint
  machine_type       = "worker"
  machine_secrets    = talos_machine_secrets.this.machine_secrets
  kubernetes_version = var.kubernetes_version
  talos_version      = var.talos_version

  config_patches = concat(
    [
      yamlencode({
        machine = {
          install = {
            disk  = each.value.install_disk
            image = "factory.talos.dev/installer/${talos_image_factory_schematic.physical_ai_worker[each.key].id}:${var.talos_version}"
            wipe  = true
          }
          network = {
            nameservers = var.physical_ai_network.nameservers
            interfaces = [{
              deviceSelector = {
                hardwareAddr = each.value.mac_address
              }
              addresses = ["${each.value.ipv4_address}/${split("/", var.physical_ai_network.cidr)[1]}"]
              routes = [{
                network = "0.0.0.0/0"
                gateway = var.physical_ai_network.gateway
              }]
            }]
          }
          nodeLabels = merge(
            {
              "ai.cisien.com/role"        = "gpu"
              "ai.cisien.com/vendor"      = each.value.gpu_vendor
              "ai.cisien.com/node"        = each.key
              "node.kubernetes.io/worker" = ""
            },
            each.value.accelerator == "gb10" ? {
              "ai.cisien.com/accelerator"       = each.value.accelerator
              "nvidia.com/device-plugin.config" = "gb10-time-slicing"
            } : {},
          )
          kubelet = {
            extraArgs = {
              "register-with-taints" = "${local.physical_ai_taint}=true:NoSchedule"
            }
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
      }),
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        "$patch"   = "delete"
      }),
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "HostnameConfig"
        hostname   = each.key
      }),
      yamlencode({
        apiVersion = "v1alpha1"
        kind       = "UserVolumeConfig"
        name       = "ai-data"
        volumeType = "directory"
      }),
    ],
    each.value.gpu_vendor == "nvidia" ? [yamlencode({
      machine = {
        kernel = {
          modules = [
            { name = "nvidia" },
            { name = "nvidia_uvm" },
            { name = "nvidia_modeset" },
            { name = "nvidia_drm" },
          ]
        }
      }
    })] : [],
  )
}

resource "talos_machine_configuration_apply" "physical_ai_worker" {
  for_each = var.physical_ai_workers

  node                        = each.value.ipv4_address
  client_configuration        = talos_machine_secrets.this.client_configuration
  machine_configuration_input = data.talos_machine_configuration.physical_ai_worker[each.key].machine_configuration
  apply_mode                  = "auto"
}

output "physical_ai_worker_machine_configurations" {
  description = "Sensitive Talos configurations for the initial insecure apply after each node is booted from its installer USB."
  value = {
    for name, config in data.talos_machine_configuration.physical_ai_worker : name => config.machine_configuration
  }
  sensitive = true
}

output "physical_ai_worker_image_factory_ids" {
  description = "Vendor-specific Talos Image Factory schematic IDs for the manual installer ISO artifacts."
  value = {
    for name, schematic in talos_image_factory_schematic.physical_ai_worker : name => schematic.id
  }
}
