# 1. Network Analysis

## 1.1 General Data Collection Methodology
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


## 1.2 Network Latency Data Collection and Results Analysis
### 1.2.1 Background on ECDF
We performed a thorough network latency analysis of the across network links and presented the results with table, and **Empirical Cumulative Distribution Function**

Brief Background on ECDF: (This is purely for my understanding, I hope experienced examiners know how to interpret these, so may I won't need to get in great depth!)
To understand how ECDF works. Suppose you perform 1,000 communication measurements and obtain:
$x_1​,x_2​,…,x_{1000}$ where each $x_i$ is a measured round-trip communication latency.

The ECDF answers the question:

"For a given latency $x$, what fraction of my measurements were less than or equal to $x$?"

For example: F(5ms) = 0.6, means `that 60% of the measured communication transaction completed in 5ms or less."`

How to Read an ECDF Function?:
- **X-axis:** Round-trip time latency in milliseconds.
- **Y-axis:** Empirical cumulative probability.
- **X-axis:** logarithmic scale.
Why is logarithmic x-axis important?
$0\rightarrow1\rightarrow10\rightarrow100ms$ represents an equal interval on the graph, even though each presents a 10x increase.

The Y-axis represents the proportion of the observations that have occurred below a particular latency( e.g $F(X) = 0,5$) means $P(X \leq x) = 0.5$., which gives $50^{th}$ percentile or **median** latency (not mean!)

an ECDF curve that rise very sharply means that most observations occur within a relatively narrow latency range.


An S-shaped curve indicates a much broader distribution (high jitter).
### 1.2.2 Detailed Methodology of how Data was Collected for this Specific Results


### 1.2.3 Results and brief intepretation


![[fig_matrix_latency_ecdf.png]]
**Latency Ranking & Distribution Profile**
- **Middleware $\leftrightarrow$ TM221 (Modbus TCP):** Demonstrates the lowest latency, clustering tightly around **1.8 ms to 2.2 ms** with a steep vertical slope that indicates highly predictable execution and sub-3 ms tail latency at $P_{99}$.
- **SCADA $\leftrightarrow$ Middleware:** Features a sharp jump at approximately **4.5 ms to 5.0 ms**, reaching $P_{95}$ near **6.0 ms** before trailing out to around **22 ms** at $P_{99}$.
- **Middleware $\leftrightarrow$ Micro820 (EtherNet/IP):** Shows tight step-function response centered tightly around **5.5 ms to 6.2 ms**, with a brief lower plateau ($<5\%$) at **3.0 ms** and maximum latency well under **12 ms**.
- **S7-1200 $\leftrightarrow$ Micro820 (Modbus TCP):** Exhibits a bimodal distribution with a inflection point around **50% at ~5.5 ms**, a secondary steep incline between **7.0 ms and 10.0 ms**, and a long tail extending up to **100 ms**.
- **TM221 $\leftrightarrow$ Micro820 (Modbus TCP):** Standard traffic steadily climbs from **1.0 ms to 6.0 ms** where it plateaus at **0.75 cumulative probability**, followed by a distinct horizontal shelf that jumps directly to **>200 ms** for the remaining top quartile ($P_{75}-P_{100}$).
- **Middleware $\leftrightarrow$ S7-1200 (OPC UA):** Incurs the highest baseline latency, starting near **45 ms** and rising sharply between **50 ms and 100 ms**, with tail latencies crossing $P_{95}$ and $P_{99}$ above **100 ms to 160 ms**.

**Key Analytical Findings**
- **Protocol Overhead Impact:** Lightweight industrial communication (Modbus TCP over dedicated paths and EtherNet/IP) consistently outperforms complex application-layer protocol stacks like OPC UA, which carries heavy processing and session framing overhead on embedded microcontrollers like the S7-1200.
- **Direct vs. Middleware Multi-Hop Delays:** Direct PLC-to-PLC polling (e.g., TM221 to Micro820) experiences severe long-tail tail latency and timeout plateaus up to 200 ms, whereas routing/handling communication through dedicated middleware bounds maximum round-trip variance more consistently.
- **SLA & Threshold Compliance:** Only Modbus TCP and EtherNet/IP middleware paths reliably satisfy strict deterministic real-time sub-10 ms thresholds ($P_{95}$ / $P_{99}$ red reference lines), while OPC UA and unbuffered peer-to-peer PLC communication regularly exceed them.

| Communication Boundary                | Count | Min (ms)  | Median / P50 (ms) | P95 Threshold (ms) | P99 Threshold (ms) | Max (ms)   | Std Dev   |
| ------------------------------------- | ----- | --------- | ----------------- | ------------------ | ------------------ | ---------- | --------- |
| Middleware <-> TM221 (Modbus TCP)     | 500   | 1.642239  | 1.988333          | 2.297421           | 2.710796           | 3.611406   | 0.193346  |
| TM221 <-> Micro820 (Modbus TCP)       | 11996 | 0.200987  | 3.892303          | 191.068470         | 192.781782         | 219.950438 | 80.739226 |
| SCADA <--> Middleware                 | 500   | 4.643600  | 4.965150          | 6.084140           | 13.804695          | 24.747400  | 1.907018  |
| Middleware <-> Micro820 (EtherNet/IP) | 500   | 2.985469  | 5.934323          | 6.433073           | 6.810497           | 12.986615  | 0.634262  |
| S7-1200 <-> Micro820 (Modbus TCP)     | 78285 | 0.108242  | 6.320477          | 11.486673          | 40.011101          | 138.602495 | 7.226272  |
| Middleware <-> S7-1200 (OPC UA)       | 500   | 46.797917 | 59.938906         | 104.847401         | 122.130375         | 164.119844 | 18.529690 |

## 1.3 Network Throughput

Usefulness of Throughput Metrics in the Testbed

**Protocol Framing Overhead:** Comparing `Bytes_per_Sec` against `Packets_per_Sec` quantifies the encapsulation overhead of different industrial protocols. Compact binary protocols (Modbus TCP) generate high packet rates with small payload sizes, whereas feature-rich protocols (OPC UA) carry significant header overhead for session handling and structured metadata serialization.

**Middleware Proxy Bottleneck Identification:** In a micro-segmented architecture where middleware acts as an edge gateway, throughput metrics reveal processing, routing, and queuing limits. Comparing throughput across direct PLC-to-PLC paths against middleware-mediated paths highlights network bottlenecks introduced by proxying.

**Security & Anomaly Detection Baseline:** Industrial Control System (ICS) networks typically exhibit stable, cyclic traffic patterns. Establishing normal byte and packet rate baselines provides a deterministic threshold to detect security anomalies such as Denial-of-Service (DoS) flooding, unauthorized network scanning, or rogue PLC command injection.

### 1.3.1 Results
Tabular summary of the dataset:

| Communication Boundary                 | Protocol    | Mean (B/s)  | Peak (B/s) | Mean (p/s) | Peak (p/s) | Avg Packet Size (B/pkt) |
| -------------------------------------- | ----------- | ----------- | ---------- | ---------- | ---------- | ----------------------- |
| S7-1200 <-> Micro820 (Modbus TCP)      | Modbus TCP  | 8707.303905 | 9825.0     | 132.933786 | 150.0      | 65.500793               |
| Middleware <-> Micro820 (EtherNet/IP)  | EtherNet/IP | 4249.305000 | 4806.0     | 38.903333  | 44.0       | 109.114212              |
| TM221 <-> Micro820 (Modbus TCP)        | Modbus TCP  | 1335.000000 | 1335.0     | 20.000000  | 20.0       | 66.750000               |
| Middleware <-> TM221 (Modbus TCP)      | Modbus TCP  | 943.190000  | 1028.0     | 14.680000  | 16.0       | 64.227044               |
| Ignition SCADA <-> Middleware (OPC UA) | OPC UA      | 906.028333  | 1592.0     | 5.778333   | 10.0       | 157.403349              |
| Middleware <-> S7-1200 (OPC UA)        | OPC UA      | 849.778333  | 1913.0     | 7.275000   | 16.0       | 116.288447              |

Wisker and Box Plot
![[throughput_bytes_per_sec_boxplot.png]]


Plotting Bytes/packet to quantify the Packet Overhead of each individual protocol and different boundaries
![[avg_packet_size_comparison.png]]

**Throughput Rate & Payload Efficiency Analysis**

- **Direct Peer-to-Peer Polling Burden:** **S7-1200 $\leftrightarrow$ Micro820 (Modbus TCP)** dominates raw throughput with a mean of **8,707.3 B/s** (peaking near **9,825 B/s**). This high bandwidth consumption stems from unbuffered high-frequency polling loops directly exchanged between the two microcontrollers without intermediate throttling.
- **Middleware Rate-Limiting & Buffering:** Routing communications through the dual-homed middleware significantly reduces network utilization. **Middleware $\leftrightarrow$ TM221 (Modbus TCP)** maintains a tightly clustered throughput around **943.2 B/s**, absorbing continuous fieldbus traffic and preventing field-level broadcast saturation toward upper-tier SCADA nodes.
- **Encapsulation & Protocol Overhead Metrics:**
	- **Modbus TCP:** Exhibits the highest payload-to-header efficiency, averaging **64.2 B/pkt to 66.8 B/pkt** across all boundaries. The minimalistic 7-byte Modbus Application Protocol (MBAP) header keeps frame sizes compact.
    - **EtherNet/IP:** Generates intermediate encapsulation overhead on **Middleware $\leftrightarrow$ Micro820** with **109.1 B/pkt** and a sustained bandwidth box plot grouping between **3,800 B/s and 4,800 B/s**.
    - **OPC UA Heavy Weighting:** Incurs the largest frame size overhead. **Middleware $\leftrightarrow$ S7-1200** averages **116.3 B/pkt**, while **Ignition SCADA $\leftrightarrow$ Middleware** reaches **157.4 B/pkt** due to security token headers, XML/binary node metadata encoding, and keep-alive session framing.
**Key Architectural Insights for Paper**
- **Bandwidth Isolation:** The dual-homed middleware proxy effectively acts as a traffic-shaping boundary, bounding field-device throughput and shielding upper-level industrial networks from high-rate PLC polling loops.
- **Framing Efficiency Trade-Off:** While OPC UA provides rich object modeling and security features, its transmission cost is roughly **2.4 times greater per packet** than raw Modbus TCP (157.4 B/pkt vs. 64.2 B/pkt). This tradeoff must be factored in when designing bandwidth-constrained or low-power wireless ICS links.