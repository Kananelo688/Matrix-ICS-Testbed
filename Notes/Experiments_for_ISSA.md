# 1. Network Latency

We measured three distinct communication boundaries (Layers) simultaneously to highlight how protocol overhead and software abstraction impact responsiveness.

- **Layer 1 (Fieldbus Inter-PLC Latency):** Request-to-response time for direct peer-to-peer Modbus TCP exchanges between controllers on Subnet `192.168.50.0/24`.
    
- **Layer 2 (Middleware Acquisition Latency):** Round-Trip Time (RTT) per protocol from request departure at RPi NIC 1 (`192.168.50.40`) to response completion across:
    - **OPC UA:** S7-1200
    - **EtherNet/IP (CIP):** Micro820
    - **Modbus TCP:** TM221CE16R
- **Layer 3 (Middleware Internal Processing Delay):** Time difference between data arrival on RPi NIC 1 and the updating of the inner asyncua OPC UA Server node structure.
- **Layer 4 (Supervisory Latency):** Round-Trip Time / Subscription update delay between Ignition SCADA (`192.168.100.20`) and RPi NIC 2 (`192.168.100.10`).

## 1.2 Experimental Data Collection Methodology
To ensure high credibility for ISSA, we will rely primarily on **passive out-of-band network packet timestamps captured at your TSW212 SPAN port**, supplemented by high-resolution application log timestamps.

### Step 1: Passive Packet Timestamp Capture via TSW212 SPAN Port.

To ensure pure packet capture, the following settings were applied on the Monitoring NIC  that's connected to SPAN Port.
```
Set-NetAdapterAdvancedProperty -Name "Matrix-Monitoring-NIC" -DisplayName "IPv4 Checksum Offload" -DisplayValue "Disabled" -ErrorAction SilentlyContinue
Set-NetAdapterAdvancedProperty -Name "Matrix-Monitoring-NIC" -DisplayName "TCP Checksum Offload (IPv4)" -DisplayValue "Disabled" -ErrorAction SilentlyContinue
Set-NetAdapterAdvancedProperty -Name "Matrix-Monitoring-NIC" -DisplayName "UDP Checksum Offload (IPv4)" -DisplayValue "Disabled" -ErrorAction SilentlyContinue
```
Because your Monitoring Node receives mirrored ingress and egress frames across all switch ports via Port 8, you can log high-precision microsecond-level hardware/kernel timestamps using `tshark` or `tcpdump` without introducing measurement overhead or jitter onto the production subnets.

Run a headless capture script on your Monitoring PC:
```
# Capture baseline traffic for 1 hour (or 10,000 transactions per protocol)
sudo tshark -i eth0 -s 0 -a duration:3600 \
  -f "tcp port 502 or tcp port 44818 or tcp port 4840" \
  -w matrix_exp1_baseline.pcapng
```

Command run: 
```
tshark -i 8 -s 0 -a duration:600 -f "tcp port 502 or tcp port 44818 or tcp port 4840" -w matrix_traffic_capture.pcapng
```

