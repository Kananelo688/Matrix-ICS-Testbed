# 1. Introduction

This document details the procedure to set up network monitoring Node. It explains sep-by-step procedure on how to configure the switch, and configure everything.

To set up  **Network Monitoring & Attack Node** on the **Teltonika TSW212 L2 Managed Switch**, We need to solve two distinct operational problems:

1. **Configuring Port Mirroring (SPAN) in TSWOS (Teltonika WebUI)** so our dedicated NIC passively captures multi-subnet traffic without interfering with production streams.

2. **Structuring our Monitoring/Attack Node’s IP Configuration** so it can simultaneously capture SPAN traffic and execute attacks across both `192.168.50.0/24` (Control Subnet) and `192.168.100.0/24` (SCADA Subnet).

# 2. Phase 1: Cable Topology on the TSW212

 The netwrok devices are plugged into explicit physical ports on the TSW212 as folows:

- **Port 1:** Siemens S7-1200 (`192.168.50.10`).
- **Port 2:** Rockwell Micro820 (`192.168.50.0`).
- **Port 3:** Schneider TM221 (`192.168.50.30`).
- **Port 4:** Raspberry Pi - Controller NIC (`192.168.50.40`).
- **Port 5:** Raspberry Pi - SCADA NIC (`192.168.100.10`).
- **Port 6:** Ignition SCADA Server (`192.168.100.2`).
- **Port 7 (SPAN / Target Port):** Dedicated NIC of your *Attack/Monitoring* PC.

# 3. Phase 2: Configure SPAN / Port Mirroring in Teltonika TSWOS

The Teltonika TSW212 runs **TSWOS** (WebUI). Port Mirroring allows you to mirror ingress/egress frames from multiple **Source Ports** to one **Monitoring Port** (Port 7).

SPARN Port Setup Steps:
1. Open your browser and navigate to the switch WebUI (e.g., `[http://192.168.1.2]
2. In the top navigation menu, go to **Network** $\rightarrow$ **Ports**.
3. Scroll down to the **Port Mirroring** section.
4. Configure the SPAN rule:
	- **Enable:** Toggle **`ON`**.
	- **Monitoring Port (Destination):** Select **`Port 8`** (The port connected to your Attack PC).
	- **Ingress Ports (Source Input):** Select **`Port 1, 2, 3, 4, 5, 6`** (Captures incoming traffic across all PLCs, RPi NICs, and SCADA).
	- **Egress Ports (Source Output):** Select **`Port 1, 2, 3, 4, 5, 6`** (Captures outgoing traffic across all endpoints)

**Note on SPAN Port Behavior:** Port 7 will now receive a direct copy of all frames traversing Ports 1–6 (Modbus TCP peer-to-peer, RPi-to-PLC polling, RPi-to-SCADA OPC UA streams.

Watch the Packet Captured on Mod
## 4. Phase 3: Configure the Monitoring / Attack PC NIC Setup
