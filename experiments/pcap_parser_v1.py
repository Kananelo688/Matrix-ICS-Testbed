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
import numpy as np

# ==============================================================================
# CONFIGURATION & SUBNET DEFINITIONS
# ==============================================================================
PCAP_FILE = r"C:\Users\chabz\Matrix-ICS-Testbed\data\matrix_traffic_capture.pcapng"

# IP Definitions for MATRIX Architecture
IP_S7_1200   = "192.168.50.10"
IP_MICRO820  = "192.168.50.20"
IP_TM221     = "192.168.50.50"
IP_RPI_NIC1  = "192.168.50.40"
IP_RPI_NIC2  = "192.168.100.10"
IP_IGNITION  = "192.168.100.2"

def categorize_boundary(src_ip, dst_ip, src_port, dst_port):
    """
    Maps packet IP and Port characteristics to MATRIX architectural boundaries.
    
    Args:
        src_ip (str): Source IP address of the packet.
        dst_ip (str): Destination IP address of the packet.
        src_port (int): Source TCP port of the packet.
        dst_port (int): Destination TCP port of the packet.
    Returns:
        tuple: (boundary_description, protocol_name) if matched, else (None, None)
    """
    
    ip_pair = {src_ip, dst_ip}

    # 1. Inter-PLC Traffic (Modbus TCP) - Separated by specific pairs
    if ip_pair == {IP_S7_1200, IP_MICRO820}:
        return "S7-1200 <-> Micro820 (Modbus TCP)", "Modbus TCP"
        
    if ip_pair == {IP_TM221, IP_MICRO820}:
        return "TM221 <-> Micro820 (Modbus TCP)", "Modbus TCP"

    # 2. Middleware -> TM221 (Modbus TCP)
    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_TM221) or (src_ip == IP_TM221 and dst_ip == IP_RPI_NIC1):
        if src_port == 502 or dst_port == 502:
            return "Middleware <-> TM221 (Modbus TCP)", "Modbus TCP"

    # 3. Middleware -> Micro820 (EtherNet/IP)
    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_MICRO820) or (src_ip == IP_MICRO820 and dst_ip == IP_RPI_NIC1):
        if src_port == 44818 or dst_port == 44818:
            return "Middleware <-> Micro820 (EtherNet/IP)", "EtherNet/IP"

    # 4. Middleware -> S7-1200 (OPC UA)
    if (src_ip == IP_RPI_NIC1 and dst_ip == IP_S7_1200) or (src_ip == IP_S7_1200 and dst_ip == IP_RPI_NIC1):
        if src_port == 4840 or dst_port == 4840:
            return "Middleware <-> S7-1200 (OPC UA)", "OPC UA"

    # 5. Ignition SCADA -> Middleware (OPC UA)
    if (src_ip == IP_IGNITION or dst_ip == IP_IGNITION) and (src_port == 4840 or dst_port == 4840):
        return "Ignition SCADA <-> Middleware (OPC UA)", "OPC UA"

    # Catch-all for other SCADA/Middleware traffic on 192.168.100.x
    if (IP_RPI_NIC2 in [src_ip, dst_ip]) and (src_port == 4840 or dst_port == 4840):
        return "Ignition SCADA <-> Middleware (OPC UA)", "OPC UA"

    return None, None


def parse_pcap_latency(pcap_path):
    """
    Parses a PCAP file to extract request-response pairs and compute round-trip times (RTT) for specific protocols.
    
    Args:
        pcap_path (str): Path to the PCAP file to be analyzed.
    Returns:
        pd.DataFrame: DataFrame containing extracted RTT records with columns:
            - Boundary
            - Protocol
            - Src_IP
            - Dst_IP
            - RTT_ms
    """
    
    print(f"[*] Opening PCAP file: {pcap_path}")
    
    display_filter = "tcp.port == 502 || tcp.port == 44818 || tcp.port == 4840"
    cap = pyshark.FileCapture(pcap_path, display_filter=display_filter, keep_packets=False)

    records = []
    pending_requests = {}
    packet_count = 0

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
            
            boundary, protocol = categorize_boundary(ip_src, ip_dst, tcp_srcport, tcp_dstport)
            if not boundary:
                continue

            stream_id = pkt.tcp.stream
            tcp_seq = int(pkt.tcp.seq)
            tcp_ack = int(pkt.tcp.ack)
            payload_len = int(pkt.tcp.len)

            # Response Packet: Matches an expected ACK for a previously sent request payload.
            # CRITICAL: only accept this as a genuine application-layer response if the
            # matching packet itself carries payload. A bare TCP ACK (payload_len == 0)
            # will often have the identical tcp.ack value and arrive first (pure TCP
            # stack turnaround), silently stealing the match and producing artificially
            # tiny "RTTs" that measure nothing but local ACK latency.
            response_key = (stream_id, tcp_ack)
            if payload_len > 0 and response_key in pending_requests:
                req_ts, req_boundary, req_proto = pending_requests.pop(response_key)
                rtt_ms = (ts - req_ts) * 1000.0
                
                # Sanity filter: Ignore instant local ACKs (< 0.1ms) and dropped frame timeouts (> 5000ms)
                if 0.1 <= rtt_ms < 5000.0:
                    records.append({
                        'Boundary': req_boundary,
                        'Protocol': req_proto,
                        'Src_IP': ip_src,
                        'Dst_IP': ip_dst,
                        'RTT_ms': rtt_ms
                    })

            # Request Packet: Must carry payload (len > 0) to represent an actual application command
            if payload_len > 0:
                expected_ack = tcp_seq + payload_len
                request_key = (stream_id, expected_ack)
                pending_requests[request_key] = (ts, boundary, protocol)

        except AttributeError:
            continue

    cap.close()
    print(f"[*] Completed parsing {packet_count} packets.")
    return pd.DataFrame(records)


def compute_statistics(df):
    if df.empty:
        print("[-] No valid transactions extracted from PCAP.")
        return None

    stats_list = []
    grouped = df.groupby(['Boundary', 'Protocol'])

    for (boundary, protocol), group in grouped:
        rtt = group['RTT_ms']
        stats_list.append({
            'Communication Boundary': boundary,
            'Protocol': protocol,
            'Sample Size (N)': len(rtt),
            'Mean (ms)': np.mean(rtt),
            'Std Dev (ms)': np.std(rtt),
            'Min (ms)': np.min(rtt),
            'Max (ms)': np.max(rtt),
            'P95 (ms)': np.percentile(rtt, 95),
            'P99 (ms)': np.percentile(rtt, 99)
        })

    return pd.DataFrame(stats_list)


if __name__ == "__main__":
    df_results = parse_pcap_latency(PCAP_FILE)
    
    if not df_results.empty:
        summary_table = compute_statistics(df_results)
        
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        pd.set_option('display.float_format', lambda x: '%.3f' % x)

        print("\n===================================================================================")
        print("                     REVISED LATENCY SUMMARY                 ")
        print("===================================================================================")
        print(summary_table.to_string(index=False)) #type: ignore
        print("===================================================================================\n") #type: ignore
        
        summary_table.to_csv(r"C:\Users\chabz\Matrix-ICS-Testbed\data\exp1_summary_metrics.csv", index=False) #type: ignore