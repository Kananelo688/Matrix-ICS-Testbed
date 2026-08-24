# Introduction
This documents all network configuration steps for all systems and layers of the testbed.

## SCADA Network Configuration.

The SCADA Network is Configured as Virtual Machine on PC. It is managed and configured with vagrant. The network interface card (private network), has been configured to be on `192.168.100.20`.

### Understanding How the Routing Actually Works (Host & VM)

When the VM is in Bridge Mode(`public_network`), VirtualBox places a software hook onto the host's physical network adapter. The VM gets its own MAC Address and acts like a second physical computer plugged into the same network as the host.

By default, Linux routes all  internet traffic out of eth0 (Vagrant's NAT interface). If control devicees are on `192.168.100.x`, but VM's `eth1`(bridge card) is configured with DHCP address or a wrong subnet mask, Linux will route traffic blindly to PLCs through `eth0`(Which is supposed to be NAT to the internet)

### Setting Up Network config on Ubuntu VM
1. **Find the exact interface names inside VM:** `ip -br link`. This command shows two interface cards: `enp0s3`(Vagrant Default NAT, for Internet connection), and `enp0s8` (VirtualBox Bridge control layer).
2. **Update the Netplan Configure**: One needs to configure static subnet binding. `sudo nano /etc/netplan/50-vagrant.yaml`. Ensure that the configuration explictly binds the Control Subnet (192.168.100.0/24)
3. Apply Netplan & Check The routing table: `sudo netplan apply` `ip route`. The will be explict route entry like `192.168.100.0/24 dev enp0s8 proto kernel scope link src 192.168.100.20`. This tell Linux "if any packet is bound for 192.168.100.x, bypass default routing and sent it directly out of the physical switch via eth1"
4. Test Communication with Raspberry Pi: `ping -I enp0s8 192.168.100.10`.

### Host Side CheckLink
If the ping fails, check the following host-level issues.
1. Host Unmanaged Network Adapter / Firewall: Windows Defender Firewall sometimes blocks traffic passing through host physical adapters. Temporarily disable Windows Domain/Private firewall to test.
2. VirtualBox Promiscuous Mode: In vagrant, allow promiscuous mode for the Interface 2. add `vb.customize ["modifyvm", id: "--nicpromisc2", "allow-all]`
