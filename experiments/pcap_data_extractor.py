
"""
pcap_data_extractor.py
-----------------------
Reads a PCAP file and extracts network metrics relevant to the MATRIX ICS testbed.
Metrics extracted:  
1. Throughput (bytes/sec and packets/sec) per boundary, binned by time intervals.
2. Protocol overhead (frame size vs TCP payload size) per payload-carrying packet.
3. Packet size distribution (raw frame length) for all packets, including bare ACKs.
4. Inter-PLC computed here (was originally in pcap_parser_v1.py) for consistency with the latency analysis notebook.

Author: Kananelo V C
"""

import sys
import asyncio

# Fix for Python 3.10+ / 3.14+ event loop in PyShark
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import pyshark
import pandas as pd
from collections import defaultdict

# CONFIGURATION & SUBNET DEFINITIONS

PCAP_FILE = r"C:\Users\chabz\Matrix-ICS-Testbed\data\matrix_traffic_capture.pcapng"

IP_S7_1200   = "192.168.50.10"
IP_MICRO820  = "192.168.50.20"
IP_TM221     = "192.168.50.50"
IP_RPI_NIC1  = "192.168.50.40"
IP_RPI_NIC2  = "192.168.100.10"
IP_IGNITION  = "192.168.100.2"

# Throughput time-bin width, in seconds
BIN_SECONDS = 1.0

OUT_THROUGHPUT     = r"C:\Users\chabz\Matrix-ICS-Testbed\data\throughput.csv"
OUT_OVERHEAD       = r"C:\Users\chabz\Matrix-ICS-Testbed\data\protocol_overhead.csv"
OUT_PACKET_SIZES   = r"C:\Users\chabz\Matrix-ICS-Testbed\data\packet_size_distribution.csv"
OUT_INTER_PLC_LATENCY       = r"C:\Users\chabz\Matrix-ICS-Testbed\data\inter_plc_latency.csv"

def categorize_boundary(src_ip, dst_ip, src_port, dst_port):
    """
    Maps packet IP and port characteristics to MATRIX architectural boundaries.
    Identical logic to pcap_parser_v1.py — kept here so this script is
    self-contained and produces boundary labels consistent with the latency
    analysis notebook.
    
    Args:
        src_ip (str): Source IP address of the packet.
        dst_ip (str): Destination IP address of the packet.
        src_port (int): Source TCP port of the packet.
        dst_port (int): Destination TCP port of the packet.
    """
    ip_pair = {src_ip, dst_ip}

    if ip_pair == {IP_S7_1200, IP_MICRO820}:
        return "S7-1200 <-> Micro820 (Modbus TCP)", "Modbus TCP"

    if ip_pair == {IP_TM221, IP_MICRO820}:
        return "TM221 <-> Micro820 (Modbus TCP)", "Modbus TCP"

    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_TM221) or (src_ip == IP_TM221 and dst_ip == IP_RPI_NIC1):
        if src_port == 502 or dst_port == 502:
            return "Middleware <-> TM221 (Modbus TCP)", "Modbus TCP"

    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_MICRO820) or (src_ip == IP_MICRO820 and dst_ip == IP_RPI_NIC1):
        if src_port == 44818 or dst_port == 44818:
            return "Middleware <-> Micro820 (EtherNet/IP)", "EtherNet/IP"

    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_S7_1200) or (src_ip == IP_S7_1200 and dst_ip == IP_RPI_NIC1):
        if src_port == 4840 or dst_port == 4840:
            return "Middleware <-> S7-1200 (OPC UA)", "OPC UA"

    if (src_ip == IP_IGNITION or dst_ip == IP_IGNITION) and (src_port == 4840 or dst_port == 4840):
        return "Ignition SCADA <-> Middleware (OPC UA)", "OPC UA"

    if (IP_RPI_NIC2 in [src_ip, dst_ip]) and (src_port == 4840 or dst_port == 4840):
        return "Ignition SCADA <-> Middleware (OPC UA)", "OPC UA"

    return None, None


def extract_network_metrics(pcap_path):
    """
    Single pass over the pcap. For every packet matching a known MATRIX
    boundary, collects:
      1. Throughput   — bytes/packets per BIN_SECONDS-wide time bucket, per boundary
      2. Overhead     — frame size vs TCP payload size, per payload-carrying packet
      3. Packet sizes — raw frame length per packet (ALL packets, incl. bare ACKs —
                         an IDS sees the full traffic shape, not just data-carrying frames)
      4. Inter-PLC latency — time between request and response for Modbus TCP at control-layer 
      boundaries (S7-1200 <-> Micro820, TM221 <-> Micro820)
      
      Args:
            pcap_path (str): Path to the PCAP file to analyze.
    """
    print(f"[*] Opening PCAP file: {pcap_path}")

    display_filter = "tcp.port == 502 || tcp.port == 44818 || tcp.port == 4840"
    cap = pyshark.FileCapture(pcap_path, display_filter=display_filter, keep_packets=False)

    throughput_bins = defaultdict(lambda: {"bytes": 0, "packets": 0})
    overhead_records = []
    packet_size_records = []
    inter_plc_latency_records = []
    start_ts = None
    packet_count = 0
    pending_requests = {}
    

    for pkt in cap:
        packet_count += 1
        if packet_count % 10000 == 0:
            print(f"    Processed {packet_count} packets...")

        try:
            ip_src = pkt.ip.src
            ip_dst = pkt.ip.dst
            tcp_srcport = int(pkt.tcp.srcport)
            tcp_dstport = int(pkt.tcp.dstport)
            ts = float(pkt.sniff_timestamp)
            frame_len = int(pkt.length)
            payload_len = int(pkt.tcp.len)
            stream_id = pkt.tcp.stream
            tcp_ack = int(pkt.tcp.ack)
            tcp_seq = int(pkt.tcp.seq)
        
            boundary, protocol = categorize_boundary(ip_src, ip_dst, tcp_srcport, tcp_dstport)
            if not boundary:
                continue

            if start_ts is None:
                start_ts = ts

            # --- 1. Throughput: every matched packet counts, bare ACKs included ---
            bin_index = int((ts - start_ts) // BIN_SECONDS)
            key = (boundary, protocol, bin_index)
            throughput_bins[key]["bytes"] += frame_len
            throughput_bins[key]["packets"] += 1

            # --- 2. Protocol overhead: only meaningful for payload-carrying packets ---
            if payload_len > 0:
                overhead_bytes = frame_len - payload_len
                overhead_records.append({
                    "Boundary": boundary,
                    "Protocol": protocol,
                    "Frame_Bytes": frame_len,
                    "TCP_Payload_Bytes": payload_len,
                    "Overhead_Bytes": overhead_bytes,
                    "Overhead_Ratio": overhead_bytes / frame_len,
                })

            # --- 3. Packet size distribution: every matched packet, for IDS-style fingerprinting ---
            packet_size_records.append({
                "Boundary": boundary,
                "Protocol": protocol,
                "Timestamp": ts,
                "Frame_Bytes": frame_len,
                "TCP_Payload_Bytes": payload_len,
            })
            
            # --- 4. Inter-PLC latency: only for Modbus TCP at control-layer boundaries ---
            if protocol == "Modbus TCP" and boundary in ["S7-1200 <-> Micro820 (Modbus TCP)", "TM221 <-> Micro820 (Modbus TCP)"]:
                response_key = (stream_id, tcp_ack)
                if payload_len > 0 and response_key in pending_requests:
                    # This is a request packet; store its timestamp
                    req_ts, req_boundary, req_proto = pending_requests.pop(response_key)
                    rtt_ms = (ts - req_ts) * 1000.0
                    
                    if 0.1 <= rtt_ms < 5000.0:
                        inter_plc_latency_records.append({
                            'Boundary': req_boundary,
                            'Protocol': req_proto,
                            'Src_IP': ip_src,
                            'Dst_IP': ip_dst,
                            'RTT_ms': rtt_ms
                        })
                if payload_len > 0:
                    expected_ack = tcp_seq + payload_len
                    request_key = (stream_id, expected_ack)
                    pending_requests[request_key] = (ts, boundary, protocol)


        except AttributeError:
            continue

    cap.close()
    print(f"[*] Completed parsing {packet_count} packets.")

    # --- Build throughput DataFrame ---
    throughput_rows = []
    for (boundary, protocol, bin_index), agg in throughput_bins.items():
        throughput_rows.append({
            "Boundary": boundary,
            "Protocol": protocol,
            "Time_Bin_Start_Sec": bin_index * BIN_SECONDS,
            "Bytes": agg["bytes"],
            "Packets": agg["packets"],
            "Bytes_per_Sec": agg["bytes"] / BIN_SECONDS,
            "Packets_per_Sec": agg["packets"] / BIN_SECONDS,
        })
    throughput_df = pd.DataFrame(throughput_rows).sort_values(["Boundary", "Time_Bin_Start_Sec"])

    overhead_df = pd.DataFrame(overhead_records)
    packet_size_df = pd.DataFrame(packet_size_records)
    inter_plc_latency_df = pd.DataFrame(inter_plc_latency_records)
    return throughput_df, overhead_df, packet_size_df, inter_plc_latency_df


if __name__ == "__main__":
    throughput_df, overhead_df, packet_size_df, inter_plc_latency_df = extract_network_metrics(PCAP_FILE)

    throughput_df.to_csv(OUT_THROUGHPUT, index=False)
    overhead_df.to_csv(OUT_OVERHEAD, index=False)
    packet_size_df.to_csv(OUT_PACKET_SIZES, index=False)
    inter_plc_latency_df.to_csv(OUT_INTER_PLC_LATENCY, index=False)

    print(f"\n[*] Saved throughput time series ({len(throughput_df)} rows)   -> {OUT_THROUGHPUT}")
    print(f"[*] Saved protocol overhead data ({len(overhead_df)} rows)     -> {OUT_OVERHEAD}")
    print(f"[*] Saved packet size distribution ({len(packet_size_df)} rows) -> {OUT_PACKET_SIZES}")
    print(f"[*] Saved inter-PLC latency data ({len(inter_plc_latency_df)} rows) -> {OUT_INTER_PLC_LATENCY}")
    if not throughput_df.empty:
        print("\n--- Mean throughput per boundary ---")
        print(throughput_df.groupby(["Boundary", "Protocol"])[["Bytes_per_Sec", "Packets_per_Sec"]]
              .mean().to_string())

    if not overhead_df.empty:
        print("\n--- Mean overhead ratio per protocol ---")
        print(overhead_df.groupby(["Boundary", "Protocol"])["Overhead_Ratio"].mean().to_string())
    
    if not inter_plc_latency_df.empty:
        print("\n--- Inter-PLC latency statistics ---")
        print(inter_plc_latency_df.groupby(["Boundary", "Protocol"])["RTT_ms"].describe().to_string())