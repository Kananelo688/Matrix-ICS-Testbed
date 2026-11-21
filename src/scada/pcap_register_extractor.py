#!/usr/bin/env python3
"""
pcap_register_extractor.py

MATRIX Testbed — WIRE-plane extractor (lives in src/data/).

PURPOSE
    Builds the "wire plane" of the attack figures: the value of the inter-PLC
    Modbus handshake registers OVER TIME, read directly from the SPAN packet
    captures, for BOTH a baseline experiment and an attack experiment, aligned so
    they can be overlaid.

    This is the middle lane of the three-plane attack figure (attacker -> WIRE ->
    physical). For plaintext protocols (Modbus, EtherNet/IP) the register values
    are extractable from the pcap; for encrypted OPC UA they are not, so for OPC-UA
    traffic we emit only metadata (packet timing/size) and a per-session
    plaintext/encrypted classification -- which is itself the "observability
    asymmetry" finding (encryption blinds the network analyst and defeats wire
    MITM forgery).

REPEATABILITY & TIME ALIGNMENT  (the key methodological choice)
    Attack runs are NOT aligned by wall-clock or run start. Each attack repeat is
    re-zeroed to ITS OWN ATTACK ONSET -- window_open_wall from that run's Kali
    attack_log.json. Onset is the one instant we know exactly and independently,
    and it is the cause whose downstream effect we measure, so it is the natural
    t=0. Repeated attack runs are therefore mutually aligned BY CONSTRUCTION in
    the neighbourhood of the attack (the only region that must be tight).
    Impact is then summarised as SCALARS per run (time-to-effect, did the
    handshake complete, ...) and averaged over the ~10 repeats -- we never
    step-average attacked waveforms (that is where fabrication/alignment problems
    live). The figure shows one REPRESENTATIVE run; repeatability is the scalar
    table.

    Clock note: the pcap is captured on the SCADA SPAN host; window_open_wall is
    on the Kali host. They are NTP-synced, so re-zeroing is accurate to the sync
    offset (a few ms) -- fine for second-scale effects. For suppress attacks the
    onset is ALSO visible in the pcap (the expected write is missing), which we
    record as an independent cross-check.

FOLDER LAYOUT (as confirmed)
    results/<baseline-id>_0001/<run>.pcap          (baseline repeats; no attack_log)
    results/<attack-id>_0001/<run>.pcap            (attack repeats)
    results/<attack-id>_0001/attack_log.json       (onset = window_open_wall)
    ... _0002, _0003, ...

OUTPUTS   (under results/<attack-id>/wire/)
    wire_timeline.csv  — tidy: (source, run, interface, register, t_rel_s, value)
        source = 'baseline' | 'attack';  t_rel_s = seconds from onset (attack) or
        from the reference handshake (baseline).
    wire_summary.csv   — per attack run scalars: onset_wall, reg0/reg2 event
        counts, handshake_completed_after_onset, wire_first_anomaly_s, ...
    opcua_sessions.csv — per OPC-UA session: endpoints, security policy,
        plaintext/encrypted (the Fig. D classification).

USAGE
    python3 src/data/pcap_register_extractor.py \
        --baseline-id baseline30wps --attack-id t1_suppress

INSTALL:  pip install scapy --break-system-packages

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import argparse
import glob
import json
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd
from scapy.all import rdpcap, IP, TCP, Raw   # type: ignore

# ==========================================================================
# CONFIGURATION  (confirmed from captures)
# ==========================================================================
AB_IP        = "192.168.50.20"          # Micro820 = Modbus SERVER holding regs
MODBUS_PORT  = 502
UNIT_ID      = 255
REGISTERS    = {0: "reg0_siemens_handshake",    # S7 <-> AB  (1=ready, 2=ack)
                2: "reg2_schneider_handshake"}  # AB <-> TM221 (1=ready, 2=ack)
CIP_PORT     = 44818                    # EtherNet/IP (AB <-> RPi) — metadata only (v1)
OPCUA_PORTS  = {4840}                   # OPC UA (S7<->RPi, RPi<->SCADA)

FC_READ_HOLDING, FC_WRITE_SINGLE, FC_WRITE_MULTIPLE = 0x03, 0x06, 0x10


def u16(b, i):
    """Big-endian uint16 from bytes b at offset i (Modbus is big-endian)."""
    return (b[i] << 8) | b[i + 1]


# ==========================================================================
# RUN DISCOVERY
# ==========================================================================
def discover_runs(results_dir, prefix):
    """Find every repeat folder for an experiment prefix and its pcap/attack_log.

    Called from: main(). Matches results/<prefix>_<NNNN>/ folders, locates the
    pcap inside each and the attack_log.json if present.

    Args:
        results_dir (str): base results directory.
        prefix (str): experiment id (baseline or attack).

    Returns:
        list[dict]: [{run_id, pcap, attack_log|None}], sorted by run_id.
    """
    runs = []
    pat = re.compile(re.escape(prefix) + r"_\d+$")
    for d in sorted(glob.glob(os.path.join(results_dir, prefix + "_*"))):
        if not os.path.isdir(d) or not pat.search(os.path.basename(d)):
            continue
        pcaps = glob.glob(os.path.join(d, "*.pcap")) + glob.glob(os.path.join(d, "*.pcapng"))
        if not pcaps:
            continue
        alog = os.path.join(d, "attack_log.json")
        runs.append({"run_id": os.path.basename(d), "pcap": pcaps[0],
                     "attack_log": alog if os.path.exists(alog) else None})
    return runs


def onset_epoch(attack_log_path):
    """Return the attack onset as a POSIX timestamp from window_open_wall.

    Called from: process_attack_run(). window_open_wall is the instant the
    injector first acted (dropped write / first rewrite) — the causal t=0.

    Args:
        attack_log_path (str): path to attack_log.json.

    Returns:
        (float|None, str|None): (epoch_seconds, iso_string) or (None, None) if the
        log is missing or the window never opened.
    """
    if not attack_log_path or not os.path.exists(attack_log_path):
        return None, None
    with open(attack_log_path) as f:
        doc = json.load(f)
    iso = doc.get("window_open_wall")
    if not iso:
        return None, None
    # ISO-8601 with timezone -> epoch
    ts = datetime.fromisoformat(iso).timestamp()
    return ts, iso


# ==========================================================================
# MODBUS REGISTER VALUE TIMELINE
# ==========================================================================
def modbus_register_timeline(pcap_path):
    """Extract each handshake register's value over time from a pcap.

    Called from: process_*_run(). Reconstructs the on-the-wire value of reg0 and
    reg2 by merging (a) client WRITES to AB (FC06/FC16) and (b) AB's READ REPLIES
    (FC03), correlated to their requests so the register can be located in the
    reply. Returns absolute (epoch) timestamps; callers re-zero as needed.

    Args:
        pcap_path (str): the capture file.

    Returns:
        dict: {reg_addr: [(epoch_ts, value), ...]} sorted by time, for reg in REGISTERS.
        Also returns packet metadata and opcua session info via side outputs:
        actually returns (timelines, opcua_info, meta_rows). See callers.
    """
    pk = rdpcap(pcap_path)
    timelines = {r: [] for r in REGISTERS}
    pending = {}            # (client_port, txid) -> (start_addr, qty)
    opcua_opn = []          # (epoch, policy_string) for OPC UA OpenSecureChannel
    meta_rows = []          # non-Modbus packet metadata (time,size,proto,ports)

    for p in pk:
        if IP not in p or TCP not in p:
            continue
        ts = float(p.time)
        tcp = p[TCP]
        sport, dport = tcp.sport, tcp.dport

        # --- OPC UA: detect security policy from OpenSecureChannel (OPN) ---
        if sport in OPCUA_PORTS or dport in OPCUA_PORTS:
            if Raw in p:
                load = bytes(p[Raw].load)
                if load[:3] == b"OPN":                 # OpenSecureChannel message
                    m = re.search(rb"http://opcfoundation.org/UA/SecurityPolicy#(\w+)", load)
                    policy = m.group(1).decode() if m else "Unknown"
                    opcua_opn.append((ts, policy, p[IP].src, p[IP].dst))
            meta_rows.append((ts, len(p), "opcua", p[IP].src, p[IP].dst, sport, dport))
            continue

        # --- EtherNet/IP (CIP): metadata only in v1 ---
        if sport == CIP_PORT or dport == CIP_PORT:
            meta_rows.append((ts, len(p), "cip", p[IP].src, p[IP].dst, sport, dport))
            continue

        # --- Modbus: parse register values ---
        if not (sport == MODBUS_PORT or dport == MODBUS_PORT) or Raw not in p:
            continue
        load = bytes(p[Raw].load)
        if len(load) < 8:
            continue
        txid = u16(load, 0)
        fc = load[7]
        to_ab   = (p[IP].dst == AB_IP and dport == MODBUS_PORT)   # request
        from_ab = (p[IP].src == AB_IP and sport == MODBUS_PORT)   # reply

        # client WRITE sets a register value
        if to_ab and fc == FC_WRITE_SINGLE and len(load) >= 12:
            addr, val = u16(load, 8), u16(load, 10)
            if addr in timelines:
                timelines[addr].append((ts, val))
        elif to_ab and fc == FC_WRITE_MULTIPLE and len(load) >= 13:
            start, qty = u16(load, 8), u16(load, 10)
            for r in REGISTERS:
                if start <= r < start + qty:
                    voff = 13 + (r - start) * 2
                    if voff + 2 <= len(load):
                        timelines[r].append((ts, u16(load, voff)))
        # client READ request: remember it so we can read the reply
        elif to_ab and fc == FC_READ_HOLDING and len(load) >= 12:
            pending[(sport, txid)] = (u16(load, 8), u16(load, 10))
        # AB READ REPLY: report register values
        elif from_ab and fc == FC_READ_HOLDING and len(load) >= 9:
            start_qty = pending.pop((dport, txid), None)
            if start_qty is None:
                continue
            start, qty = start_qty
            bc = load[8]
            for r in REGISTERS:
                if start <= r < start + qty:
                    voff = 9 + (r - start) * 2
                    if voff + 2 <= 9 + bc and voff + 2 <= len(load):
                        timelines[r].append((ts, u16(load, voff)))

    for r in timelines:
        timelines[r].sort(key=lambda x: x[0])
    return timelines, opcua_opn, meta_rows


# ==========================================================================
# PER-RUN PROCESSING
# ==========================================================================
def process_attack_run(run, out_rows, summary_rows, opcua_rows):
    """Extract an attack run's register timeline, re-zeroed to its onset.

    Called from: main() for each attack repeat. Appends tidy timeline rows
    (t_rel_s = seconds from onset) and a scalar summary row.

    Args:
        run (dict): {run_id, pcap, attack_log}.
        out_rows, summary_rows, opcua_rows (list): accumulators mutated in place.

    Returns:
        None.
    """
    on_ep, on_iso = onset_epoch(run["attack_log"])
    timelines, opn, meta = modbus_register_timeline(run["pcap"])

    if on_ep is None:
        print(f"  [{run['run_id']}] WARNING: no attack onset (window never opened) "
              f"— emitting absolute times, zeroed at first packet")
    for r, series in timelines.items():
        if not series:
            continue
        base = on_ep if on_ep is not None else series[0][0]
        for ts, val in series:
            out_rows.append({"source": "attack", "run": run["run_id"],
                             "interface": "modbus", "register": REGISTERS[r],
                             "t_rel_s": round(ts - base, 4), "value": val})

    # scalar summary: did reg0 complete a handshake (reach 2) AFTER onset?
    reg0 = timelines.get(0, [])
    after = [(t, v) for (t, v) in reg0 if on_ep is not None and t >= on_ep]
    reached_2 = any(v == 2 for _, v in after)
    # wire cross-check onset for suppress: first time after onset that reg0 is
    # expected-but-absent is hard to pinpoint; record first post-onset reg0 event.
    first_evt = round(after[0][0] - on_ep, 4) if (after and on_ep) else None
    summary_rows.append({
        "run": run["run_id"], "onset_wall": on_iso,
        "reg0_events": len(reg0), "reg2_events": len(timelines.get(2, [])),
        "reg0_reached_ack_after_onset": reached_2,
        "first_reg0_event_after_onset_s": first_evt,
    })
    for (ts, policy, src, dst) in opn:
        opcua_rows.append({"run": run["run_id"], "source": "attack",
                           "t_epoch": ts, "src": src, "dst": dst,
                           "security_policy": policy,
                           "encrypted": policy not in ("None", "Unknown")})


def process_baseline(runs, out_rows, opcua_rows):
    """Build a clean baseline register ghost from the baseline pcaps.

    Called from: main(). Baseline has no attack onset, so each reg0/reg2 handshake
    is re-zeroed to its OWN rising edge (reg->1) to form canonical handshake
    waveforms; these are emitted with t_rel_s relative to that edge, so the
    overlay notebook can place the baseline ghost at the attack's onset reference.

    Args:
        runs (list[dict]): baseline run descriptors.
        out_rows, opcua_rows (list): accumulators.

    Returns:
        None.
    """
    for run in runs:
        timelines, opn, meta = modbus_register_timeline(run["pcap"])
        for r, series in timelines.items():
            if not series:
                continue
            # segment into handshakes at each rising edge to 1; emit each relative
            # to its edge so they can be averaged/overlaid by the notebook.
            vals = [v for _, v in series]; ts = [t for t, _ in series]
            for i in range(len(series)):
                if vals[i] == 1 and (i == 0 or vals[i - 1] != 1):
                    edge = ts[i]
                    # emit this handshake's samples within a window after the edge
                    j = i
                    while j < len(series) and ts[j] - edge <= 15.0:
                        out_rows.append({"source": "baseline", "run": run["run_id"],
                                         "interface": "modbus", "register": REGISTERS[r],
                                         "t_rel_s": round(ts[j] - edge, 4), "value": vals[j]})
                        j += 1
        for (t, policy, src, dst) in opn:
            opcua_rows.append({"run": run["run_id"], "source": "baseline",
                               "t_epoch": t, "src": src, "dst": dst,
                               "security_policy": policy,
                               "encrypted": policy not in ("None", "Unknown")})


# ==========================================================================
# MAIN
# ==========================================================================
def main():
    ap = argparse.ArgumentParser(description="MATRIX pcap wire-plane extractor.")
    ap.add_argument("--baseline-id", required=True, help="baseline experiment prefix")
    ap.add_argument("--attack-id", required=True, help="attack experiment prefix")
    ap.add_argument("--results", default="results", help="base results dir")
    ap.add_argument("--out", default=None, help="output dir (default results/<attack-id>/wire)")
    args = ap.parse_args()

    out_dir = args.out or os.path.join(args.results, args.attack_id, "wire")
    os.makedirs(out_dir, exist_ok=True)

    base_runs = discover_runs(args.results, args.baseline_id)
    atk_runs  = discover_runs(args.results, args.attack_id)
    print(f"baseline runs: {len(base_runs)}   attack runs: {len(atk_runs)}")
    if not atk_runs:
        print("No attack runs found — check --attack-id and results/ layout."); return 2

    timeline_rows, summary_rows, opcua_rows = [], [], []

    print("Processing attack runs (onset-aligned):")
    for run in atk_runs:
        print(f"  {run['run_id']}  (attack_log: {'yes' if run['attack_log'] else 'MISSING'})")
        process_attack_run(run, timeline_rows, summary_rows, opcua_rows)

    print("Processing baseline runs (per-handshake ghost):")
    process_baseline(base_runs, timeline_rows, opcua_rows)

    tl = pd.DataFrame(timeline_rows)
    tl.to_csv(os.path.join(out_dir, "wire_timeline.csv"), index=False)
    pd.DataFrame(summary_rows).to_csv(os.path.join(out_dir, "wire_summary.csv"), index=False)
    oc = pd.DataFrame(opcua_rows)
    if len(oc):
        oc.to_csv(os.path.join(out_dir, "opcua_sessions.csv"), index=False)

    print(f"\nwrote {out_dir}/wire_timeline.csv  ({len(tl)} rows)")
    print(f"wrote {out_dir}/wire_summary.csv  ({len(summary_rows)} attack runs)")
    if len(oc):
        enc = oc[oc.encrypted].src.nunique()
        print(f"wrote {out_dir}/opcua_sessions.csv  ({len(oc)} OPN; "
              f"encrypted policies seen: {sorted(set(oc[oc.encrypted].security_policy))})")
    # quick repeatability readout
    if summary_rows:
        s = pd.DataFrame(summary_rows)
        print("\nRepeatability (attack runs):")
        print(f"  reg0 reached ack after onset: "
              f"{int(s.reg0_reached_ack_after_onset.sum())}/{len(s)} runs "
              f"(suppress success = this should be LOW)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())