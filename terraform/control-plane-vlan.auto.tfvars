# Fixed control-plane layout after the VLAN migration.
# This file contains no credentials and overrides the legacy control-plane values
# from terraform.tfvars.

cluster_endpoint = "https://172.16.200.230:6443"

control_planes = {
  cp-04 = {
    proxmox_node = "pve-02"
    storage_pool = "local-storage-pool"
    ipv4_address = "172.16.200.230"
    vm_id        = 2304
  }
  cp-05 = {
    proxmox_node = "pve-03"
    storage_pool = "local-storage-pool"
    ipv4_address = "172.16.200.231"
    vm_id        = 2305
  }
  cp-06 = {
    proxmox_node = "pve-04"
    storage_pool = "ssd-pool"
    ipv4_address = "172.16.200.232"
    vm_id        = 2306
  }
}

control_plane_network = {
  gateway     = "172.16.200.1"
  nameservers = ["192.168.1.2"]
  cidr        = "172.16.200.0/24"
  bridge      = "workvnet"
}
