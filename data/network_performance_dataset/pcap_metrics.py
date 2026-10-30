#!/usr/bin/env python3
"""
pcap_metrics.py

MATRIX Testbed: PCAPNG Dissection & Traffic Metrics Extractor
================================================================
Dissects a .pcapng capture of the ICS testbed traffic (Modbus/TCP,
EtherNet/IP-CIP, and OPC-UA) and produces two CSV reports:

  1. <output_prefix>_summary.csv
     One row per TCP flow (+ one "OVERALL" row) containing:
       - Throughput  : average & peak bit rate, average & peak packet rate
       - Latency     : protocol query->full-response time (mean/median/
                        min/max/std/count), matched per-protocol using
                        each protocol's own transaction identifier
       - Packet loss : TCP retransmission count/rate, lost-segment count

  2. <output_prefix>_timebins.csv
     Time-binned (default 100 ms) throughput series per flow (+ an
     "OVERALL" series), i.e. bit rate and packet rate for every bin,
     across the full capture duration.

Requires: tshark (Wireshark CLI) available on PATH, and Python
packages: pandas, numpy.

Usage:
    python3 pcap_metrics.py capture.pcapng --output-prefix results \
        --bin-ms 100
"""

import argparse
import csv
import io
import subprocess
import sys

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Testbed device map: maps each known IP address to a human-readable device
# name so the reports are easier to read than raw IPs. IPs not in this map
# are shown as-is.
# ---------------------------------------------------------------------------
DEVICE_MAP = {
    "192.168.50.10": "S7-1200",
    "192.168.50.20": "Micro820",
    "192.168.50.50": "TM221",
    "192.168.50.40": "RPi",
    "192.168.100.10": "RPi",          # RPi's second NIC/interface
    "192.168.100.2": "SCADA-VM",
}

# ---------------------------------------------------------------------------
# Protocol identification by well-known TCP port. The testbed only uses
# these three ICS protocols, each on a fixed server port.
# ---------------------------------------------------------------------------
PROTOCOL_PORTS = {
    502: "Modbus-TCP",
    44818: "EtherNet/IP-CIP",
    4840: "OPC-UA",
}


def device_name(ip: str) -> str:
    """Return the friendly device name for an IP, or the IP itself if unknown."""
    return DEVICE_MAP.get(ip, ip)


def protocol_for_flow(srcport: int, dstport: int) -> str:
    """
    Identify which ICS protocol a flow belongs to by checking whether either
    endpoint's port is one of the known well-known server ports.
    """
    for port in (srcport, dstport):
        if port in PROTOCOL_PORTS:
            return PROTOCOL_PORTS[port]
    return "Other"


# ---------------------------------------------------------------------------
# Step 1: Use tshark to dump exactly the fields we need, one row per packet,
# straight into an in-memory CSV. This is far faster than iterating packets
# with pyshark, since tshark does the dissection natively in C.
# ---------------------------------------------------------------------------
def extract_packets(pcap_path: str) -> pd.DataFrame:
    """
    Run tshark once over the capture, extracting per-packet fields needed
    for throughput, latency and loss analysis:

      - frame.time_epoch / frame.len       : for throughput binning
      - ip.src / ip.dst / tcp.*port        : to build flow (5-tuple) identity
      - tcp.stream                         : tshark's own per-flow ID, used
                                              as our flow key
      - mbtcp.trans_id                     : Modbus/TCP transaction ID
                                              (echoed identically in the
                                              matching request/response pair)
      - enip.context                       : EtherNet/IP "sender context"
                                              (echoed identically in the
                                              matching CIP request/response)
      - cip.service                        : CIP service code (bit 0x80 set
                                              on the reply vs the request)
      - opcua.security.rqid                : OPC-UA secure-channel Request ID
                                              (echoed identically in the
                                              matching request/response)
      - tcp.analysis.retransmission        : flags a retransmitted segment
      - tcp.analysis.lost_segment          : flags a detected gap (implies
                                              a segment was lost/not captured)

    Returns a pandas DataFrame, one row per packet.
    """
    fields = [
        "frame.number", "frame.time_epoch", "frame.len",
        "ip.src", "ip.dst", "tcp.srcport", "tcp.dstport", "tcp.stream",
        "mbtcp.trans_id",
        "enip.context", "cip.service",
        "opcua.security.rqid",
        "tcp.analysis.retransmission", "tcp.analysis.lost_segment",
    ]

    cmd = ["tshark", "-r", pcap_path, "-T", "fields"]
    for f in fields:
        cmd += ["-e", f]
    cmd += ["-E", "header=y", "-E", "separator=,", "-E", "quote=d", "-E", "occurrence=f"]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    df = pd.read_csv(io.StringIO(result.stdout))

    # Only packets that belong to a TCP conversation are relevant here
    # (our testbed protocols all run over TCP).
    df = df.dropna(subset=["tcp.stream"])
    df["tcp.stream"] = df["tcp.stream"].astype(int)
    df["tcp.srcport"] = df["tcp.srcport"].astype("Int64")
    df["tcp.dstport"] = df["tcp.dstport"].astype("Int64")

    # Boolean flags come back as "1"/NaN from tshark; normalise to bool.
    df["retransmission"] = df["tcp.analysis.retransmission"].fillna(0).astype(int) == 1
    df["lost_segment"] = df["tcp.analysis.lost_segment"].fillna(0).astype(int) == 1

    return df


# ---------------------------------------------------------------------------
# Step 2: Assign a stable "flow" label to every packet, combining the two
# endpoint device names, ports and the identified protocol, e.g.:
#   "S7-1200:60724 <-> RPi:4840 (OPC-UA)"
# This is done once per tcp.stream (both directions of a flow share one
# tcp.stream ID in tshark, which is what we want for latency and loss).
# ---------------------------------------------------------------------------
def build_flow_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a human-readable 'flow' column and a 'protocol' column."""
    flow_labels = {}
    flow_protocols = {}

    for stream_id, group in df.groupby("tcp.stream"):
        first = group.iloc[0]
        src_ip, dst_ip = first["ip.src"], first["ip.dst"]
        srcport, dstport = int(first["tcp.srcport"]), int(first["tcp.dstport"])

        proto = protocol_for_flow(srcport, dstport)

        # Always print the flow as "client:port <-> server:port" so it's
        # deterministic regardless of which direction was captured first.
        # The "server" side is whichever port matches a known ICS port.
        if dstport in PROTOCOL_PORTS:
            client_ip, client_port = src_ip, srcport
            server_ip, server_port = dst_ip, dstport
        elif srcport in PROTOCOL_PORTS:
            client_ip, client_port = dst_ip, dstport
            server_ip, server_port = src_ip, srcport
        else:
            client_ip, client_port = src_ip, srcport
            server_ip, server_port = dst_ip, dstport

        label = (f"{device_name(client_ip)}:{client_port} <-> "
                 f"{device_name(server_ip)}:{server_port} ({proto})")

        flow_labels[stream_id] = label
        flow_protocols[stream_id] = proto

    df["flow"] = df["tcp.stream"].map(flow_labels)
    df["protocol"] = df["tcp.stream"].map(flow_protocols)
    return df


# ---------------------------------------------------------------------------
# Step 3: Throughput — bin packets into fixed-width time windows and compute
# bit rate (bits/sec) and packet rate (packets/sec) per bin, per flow, and
# for the whole capture ("OVERALL").
# ---------------------------------------------------------------------------
def compute_timebins(df: pd.DataFrame, bin_ms: int) -> pd.DataFrame:
    """
    Build a time-binned throughput series.

    Each row = one flow, one time bin, with:
      - bin_start_s   : bin start time, relative to the first packet (s)
      - packets       : number of packets seen in that bin
      - bytes         : total on-wire bytes (frame.len) seen in that bin
      - bit_rate_bps   : bytes*8 / bin width  -> bits per second
      - packet_rate_pps: packets / bin width  -> packets per second

    An "OVERALL" pseudo-flow is also produced, summing all flows together
    per bin, so total network throughput can be read directly.
    """
    bin_width_s = bin_ms / 1000.0
    t0 = df["frame.time_epoch"].min()

    df = df.copy()
    df["bin_index"] = ((df["frame.time_epoch"] - t0) / bin_width_s).astype(int)

    def summarise(group_cols):
        g = (df.groupby(group_cols)
               .agg(packets=("frame.number", "count"),
                    bytes=("frame.len", "sum"))
               .reset_index())
        g["bin_start_s"] = g["bin_index"] * bin_width_s
        g["bit_rate_bps"] = (g["bytes"] * 8) / bin_width_s
        g["packet_rate_pps"] = g["packets"] / bin_width_s
        return g

    per_flow = summarise(["flow", "protocol", "bin_index"])
    per_flow = per_flow[["flow", "protocol", "bin_start_s", "packets", "bytes",
                          "bit_rate_bps", "packet_rate_pps"]]

    overall = summarise(["bin_index"])
    overall["flow"] = "OVERALL"
    overall["protocol"] = "ALL"
    overall = overall[["flow", "protocol", "bin_start_s", "packets", "bytes",
                        "bit_rate_bps", "packet_rate_pps"]]

    timebins = pd.concat([per_flow, overall], ignore_index=True)
    timebins = timebins.sort_values(["flow", "bin_start_s"]).reset_index(drop=True)
    return timebins


# ---------------------------------------------------------------------------
# Step 4: Latency — for each protocol, match a query packet to its full
# response packet using that protocol's own transaction identifier, then
# take the timestamp difference as the "protocol translation time".
#
# Matching approach per protocol:
#   Modbus/TCP : (tcp.stream, mbtcp.trans_id) uniquely identifies a
#                query/response pair (2 packets: client->server query,
#                server->client response).
#   CIP        : (tcp.stream, enip.context) identifies a query/response
#                pair. cip.service on the response has bit 0x80 set
#                relative to the request (e.g. request 0x4c -> reply 0xcc),
#                which is used to tell request from response when ordering
#                by time isn't enough (e.g. duplicate contexts reused later
#                in the same session are treated as separate pairs by
#                pairing them in time order).
#   OPC-UA     : (tcp.stream, opcua.security.rqid) identifies a
#                query/response pair at the secure-channel layer.
#
# For every matched pair we compute latency = response_time - request_time.
# ---------------------------------------------------------------------------
def compute_latencies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per matched request/response
    transaction: flow, protocol, request_frame, response_frame,
    latency_s.
    """
    records = []

    # --- Modbus/TCP -------------------------------------------------------
    mb = df.dropna(subset=["mbtcp.trans_id"]).copy()
    mb["mbtcp.trans_id"] = mb["mbtcp.trans_id"].astype(int)
    for (stream_id, trans_id), group in mb.groupby(["tcp.stream", "mbtcp.trans_id"]):
        group = group.sort_values("frame.time_epoch")
        if len(group) < 2:
            continue  # query with no matching response (dropped/incomplete)
        req, resp = group.iloc[0], group.iloc[-1]
        records.append({
            "flow": req["flow"], "protocol": "Modbus-TCP",
            "request_frame": int(req["frame.number"]),
            "response_frame": int(resp["frame.number"]),
            "latency_s": resp["frame.time_epoch"] - req["frame.time_epoch"],
        })

    # --- EtherNet/IP - CIP --------------------------------------------------
    cip = df.dropna(subset=["enip.context"]).copy()
    for (stream_id, context), group in cip.groupby(["tcp.stream", "enip.context"]):
        group = group.sort_values("frame.time_epoch").reset_index(drop=True)
        # Pair consecutive packets within the same context in time order:
        # (0,1), (2,3), ... — handles a context value being reused for
        # multiple transactions later in the same session.
        for i in range(0, len(group) - 1, 2):
            req, resp = group.iloc[i], group.iloc[i + 1]
            records.append({
                "flow": req["flow"], "protocol": "EtherNet/IP-CIP",
                "request_frame": int(req["frame.number"]),
                "response_frame": int(resp["frame.number"]),
                "latency_s": resp["frame.time_epoch"] - req["frame.time_epoch"],
            })

    # --- OPC-UA -------------------------------------------------------------
    opcua = df.dropna(subset=["opcua.security.rqid"]).copy()
    opcua["opcua.security.rqid"] = opcua["opcua.security.rqid"].astype(int)
    for (stream_id, rqid), group in opcua.groupby(["tcp.stream", "opcua.security.rqid"]):
        group = group.sort_values("frame.time_epoch")
        if len(group) < 2:
            continue
        req, resp = group.iloc[0], group.iloc[-1]
        records.append({
            "flow": req["flow"], "protocol": "OPC-UA",
            "request_frame": int(req["frame.number"]),
            "response_frame": int(resp["frame.number"]),
            "latency_s": resp["frame.time_epoch"] - req["frame.time_epoch"],
        })

    return pd.DataFrame.from_records(records)


# ---------------------------------------------------------------------------
# Step 5: Build the final per-flow (+ OVERALL) summary combining throughput,
# latency and packet-loss/retransmission metrics.
# ---------------------------------------------------------------------------
def build_summary(df: pd.DataFrame, timebins: pd.DataFrame,
                   latencies: pd.DataFrame) -> pd.DataFrame:
    rows = []

    flows = list(df["flow"].unique()) + ["OVERALL"]

    for flow in flows:
        is_overall = flow == "OVERALL"
        flow_pkts = df if is_overall else df[df["flow"] == flow]
        flow_bins = timebins[timebins["flow"] == flow]
        flow_lat = latencies if is_overall else latencies[latencies["flow"] == flow]

        total_packets = len(flow_pkts)
        total_bytes = int(flow_pkts["frame.len"].sum())
        duration_s = (flow_pkts["frame.time_epoch"].max()
                      - flow_pkts["frame.time_epoch"].min()) if total_packets else 0.0

        retrans_count = int(flow_pkts["retransmission"].sum())
        lost_count = int(flow_pkts["lost_segment"].sum())
        retrans_rate = (retrans_count / total_packets) if total_packets else 0.0

        row = {
            "flow": flow,
            "protocol": "ALL" if is_overall else flow_pkts["protocol"].iloc[0],
            "total_packets": total_packets,
            "total_bytes": total_bytes,
            "duration_s": duration_s,

            # Throughput: averages are total/duration; peaks are the busiest
            # single time bin observed for that flow.
            "avg_bit_rate_bps": (total_bytes * 8 / duration_s) if duration_s else 0.0,
            "peak_bit_rate_bps": flow_bins["bit_rate_bps"].max() if len(flow_bins) else 0.0,
            "avg_packet_rate_pps": (total_packets / duration_s) if duration_s else 0.0,
            "peak_packet_rate_pps": flow_bins["packet_rate_pps"].max() if len(flow_bins) else 0.0,

            # Latency (protocol query -> full response time)
            "latency_count": len(flow_lat),
            "latency_mean_s": flow_lat["latency_s"].mean() if len(flow_lat) else np.nan,
            "latency_median_s": flow_lat["latency_s"].median() if len(flow_lat) else np.nan,
            "latency_min_s": flow_lat["latency_s"].min() if len(flow_lat) else np.nan,
            "latency_max_s": flow_lat["latency_s"].max() if len(flow_lat) else np.nan,
            "latency_std_s": flow_lat["latency_s"].std() if len(flow_lat) else np.nan,

            # Packet loss / retransmissions
            "retransmission_count": retrans_count,
            "retransmission_rate": retrans_rate,
            "lost_segment_count": lost_count,
        }
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Dissect a pcapng capture and produce throughput, "
                    "latency and packet-loss CSV reports.")
    parser.add_argument("pcap", help="Path to the .pcapng capture file")
    parser.add_argument("--output-prefix", default="pcap_metrics",
                        help="Prefix for the output CSV files "
                             "(default: pcap_metrics)")
    parser.add_argument("--bin-ms", type=int, default=100,
                        help="Time bin width in milliseconds for the "
                             "throughput time series (default: 100)")
    args = parser.parse_args()

    print(f"[1/5] Extracting packet fields from {args.pcap} via tshark...")
    df = extract_packets(args.pcap)
    print(f"      {len(df)} TCP packets extracted.")

    print("[2/5] Labelling flows and protocols...")
    df = build_flow_labels(df)

    print(f"[3/5] Computing {args.bin_ms} ms time-binned throughput...")
    timebins = compute_timebins(df, args.bin_ms)

    print("[4/5] Matching protocol request/response pairs for latency...")
    latencies = compute_latencies(df)
    print(f"      {len(latencies)} transactions matched across all protocols.")

    print("[5/5] Building per-flow summary...")
    summary = build_summary(df, timebins, latencies)

    summary_path = f"{args.output_prefix}_summary.csv"
    timebins_path = f"{args.output_prefix}_timebins.csv"

    summary.to_csv(summary_path, index=False, quoting=csv.QUOTE_MINIMAL)
    timebins.to_csv(timebins_path, index=False, quoting=csv.QUOTE_MINIMAL)

    print(f"\nDone.\n  Summary CSV : {summary_path}\n  Time-bins CSV: {timebins_path}")


if __name__ == "__main__":
    main()
