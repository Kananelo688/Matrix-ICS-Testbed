#!/usr/bin/env python3
"""
experiment_logger.py

MATRIX Testbed — experiment logger (runs on the SCADA PC, beside the SPAN NIC).

WHAT IT DOES (one invocation == one experiment run)
    1. Allocates a run_id by auto-incrementing a prefix you give it
       (e.g. you pass "baseline" → it creates "baseline_0001", next time
       "baseline_0002"; passing "baseline_0007" is treated the same as
       "baseline" — the trailing _NNNN is stripped and re-allocated, so you can
       all its data (DB rows + results folder) — see --id help.
    2. Starts a packet capture (dumpcap) on the SPAN/monitoring NIC, writing
       results/<run_id>/<run_id>.pcap  — the logger OWNS the capture.
    3. Connects to the Pi middleware OPC-UA server as a client (exactly like
       Ignition), reads every process tag once (baseline snapshot), then
       SUBSCRIBES and writes ONE ROW PER TAG CHANGE to a single SQLite database
       (database/matrix.db), tagged with the run_id.
    4. On Ctrl-C: stops the capture cleanly, stamps the run's end time, exports
       database/runs.csv, and exits.

TWO RECORD PLANES (kept independent on purpose)
    network plane : the .pcap (authoritative wire truth, all ports, incl.
                    inter-PLC Modbus — captured by dumpcap here).
    state plane   : the SQLite tag-transition log (what the namespace believed).
    Analysis later JOINS them on timestamp. Because the logger and the SPAN
    capture run on the SAME machine, both planes share one clock — no NTP
    alignment needed between them.

RESOLUTION CAVEAT (state plane)
    The logger is a subscriber, so it inherits the server's publish cadence
    (server update ~0.5 s; the S7-1200 forces ~1 s on Turntable tags). Sub-second
    transitions on the Siemens side can be missed on the STATE plane — but the
    pcap captures them at full wire resolution, so nothing is truly lost.

OUTPUT LAYOUT
    database/
        matrix.db                 (single cumulative DB — all runs, by run_id)
        runs.csv                  (human-readable run index, auto-exported)
    results/
        baseline_0001/
            baseline_0001.pcap
            baseline_0001_dumpcap.log
        tm221_modbus_injection_0001/
            ...

USAGE
    python experiment_logger.py --id baseline --description "nominal cycle, no attack"
    python experiment_logger.py --id tm221_modbus_injection --description "A3 peer suppression"
    python experiment_logger.py --id baseline --no-capture        # test logger w/o SPAN

DB SCHEMA (quick reference for analysis)
    runs(run_id PK, prefix, seq_num, description, start_ts_utc, end_ts_utc,
         status, pcap_path, dumpcap_log, opcua_url, host)
    state_events(seq PK, run_id, ts_utc, ts_monotonic, zone, tag, value,
                 prev_value, vtype)        -- prev_value NULL == initial snapshot
    events(id PK, run_id, ts_utc, ts_monotonic, type, detail)
                 -- type in {heartbeat, disconnect, reconnect, note}

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import argparse
import asyncio
import logging
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from asyncua import Client, Node
from asyncua.common.subscription import DataChangeNotif

# ==========================================================================
# CONFIGURATION
# ==========================================================================

OPC_URL        = "opc.tcp://192.168.100.10:4840"     # Pi middleware server
NAMESPACE_URI  = "urn:MATRIX.Middleware.OPC-UA"       # must match opcua_server.py

# SPAN / monitoring NIC on the SCADA PC (from `dumpcap -D`). The device path is
# the most stable way to name it; the friendly name is here for humans.
SPAN_NIC = r"\Device\NPF_{04671A5F-66CE-4D9A-B85A-37F416583AE7}"
SPAN_NIC_NAME = "MATRIX_Monitoring_NIC"   # after you rename Ethernet 2
DUMPCAP        = "dumpcap"            # on PATH (Wireshark); or set a full path

DB_DEFAULT       = os.path.join("database", "matrix.db")
RESULTS_DEFAULT  = "results"
RUNS_CSV         = os.path.join("database", "runs.csv")

SUB_PERIOD_MS    = 200     # OPC-UA subscription publishing interval (ms)
HEARTBEAT_SEC    = 5       # write a heartbeat row this often (proves "alive")
LIVENESS_SEC     = 1       # idle-loop tick / liveness probe cadence
RECONNECT_DELAY  = 5       # seconds between reconnect attempts
CAPTURE_VERIFY_S = 1.0     # wait this long to confirm dumpcap actually started

IS_WINDOWS = os.name == "nt"

# ==========================================================================
# TAG MAP — every process tag to subscribe/log.
# internal tag : (zone folder, node display name, value type)
# Mirrors the read-only + writable nodes in opcua_server.py. Excludes the
# Benchmark object and the housekeeping nodes (middleware_uptime, last_update)
# which change every cycle and are not process state.
#
# NOTE: 'arduinoHandshakeCode' and 'transferUnitPositionCode' currently never
# change (a known server-side node/state name mismatch) — they will log one
# initial row and then stay put. The REAL inter-PLC handshake lives in the pcap
# (inter-PLC Modbus), which is the authoritative source for RQ2 anyway.
# ==========================================================================
TAG_MAP = {
    # --- System (link health) ---
    "siemens_connected":          ("System",       "Siemens Connected",          "bool"),
    "ab_connected":               ("System",       "AB Connected",               "bool"),
    "tm221_connected":            ("System",       "TM221 Connected",            "bool"),

    # --- Turntable (Siemens S7-1200) ---
    "inPosition":                 ("Turntable",    "Turntable In Position",      "bool"),
    "magazineEmpty":              ("Turntable",    "Magazine Empty",             "bool"),
    "motorTurntable":             ("Turntable",    "Motor Turntable",            "bool"),
    "drillActive":                ("Turntable",    "Drill Active",               "bool"),
    "weldActive":                 ("Turntable",    "Weld Active",                "bool"),
    "magazinePart":               ("Turntable",    "Magazine Part",              "bool"),
    "transferPart":               ("Turntable",    "Transfer Part Ready",        "bool"),
    "sliderMagazine":             ("Turntable",    "Slider Magazine",            "bool"),
    "weldingPart":                ("Turntable",    "Welding Part",               "bool"),
    "drillPart":                  ("Turntable",    "Drill Part",                 "bool"),
    "siemensStartCommand":        ("Turntable",    "Siemens Start Command",      "bool"),
    # "siemensStopCommand":         ("Turntable",    "Siemens Stop Command",       "bool"),
    # "siemensResetCommand":        ("Turntable",    "Siemens Reset Command",      "bool"),
    "workpiecesCount":            ("Turntable",    "Completed Workpieces Count", "int"),
    "siemensPeerCommunicationOk": ("Turntable",    "Siemens PeerComm OK",        "bool"),
    "controllerActive":           ("Turntable",    "Siemens Active",             "bool"),

    # --- Transfer Unit (Allen-Bradley Micro820) ---
    "rotateToConveyor":           ("TransferUnit", "Rotate To Conveyor",         "bool"),
    "rotateToTable":              ("TransferUnit", "Rotate To Table",            "bool"),
    "vacuumGripper":              ("TransferUnit", "Vacuum Gripper",             "bool"),
    "controllerActiveIndicator":  ("TransferUnit", "Controller Active Indicator","bool"),
    "transferUnitAtConveyor":     ("TransferUnit", "Transfer Unit At Conveyor",  "bool"),
    "transferUnitAtTurntable":    ("TransferUnit", "Transfer Unit At Turntable", "bool"),
    "turntableInPosition":        ("TransferUnit", "Turntable In Position (AB)", "bool"),
    "siemensHandshakeCode":       ("TransferUnit", "Siemens Handshake Code",     "int"),
    "schneiderHandshakeCode":     ("TransferUnit", "Schneider Handshake Code", "int"),
    "schneiderHandshakeACK":        ("TransferUnit", "Schneider Handshake ACK",  "int"),
    "transferUnitPositionCode":   ("TransferUnit", "Unit Position Code",         "int"),

    # --- Conveyor (Schneider TM221) ---
    "conveyorBelt":               ("Conveyor",     "Conveyor Belt Motor",        "bool"),
    "separatorValve":             ("Conveyor",     "Separator Valve",            "bool"),
    "sliderMotor":                ("Conveyor",     "Slider Motor",               "bool"),
    "tm221ActiveIndicator":       ("Conveyor",     "TM221 Active Indicator",     "bool"),
    "workpieceOnConveyor":        ("Conveyor",     "Workpiece On Conveyor",      "bool"),
    "palletReady":                ("Conveyor",     "Pallet Ready",               "bool"),
    "workpieceOnPallet":          ("Conveyor",     "Workpiece On Pallet",        "bool"),
    "sliderInPosition":           ("Conveyor",     "Slider In Position",         "bool"),
}

# ==========================================================================
# LOGGING
# ==========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("asyncua").setLevel(logging.ERROR)
log = logging.getLogger("LOGGER")


# ==========================================================================
# DATABASE
# ==========================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    prefix       TEXT NOT NULL,
    seq_num      INTEGER NOT NULL,
    description  TEXT,
    start_ts_utc TEXT,
    end_ts_utc   TEXT,
    status       TEXT,                 -- running | completed | aborted
    pcap_path    TEXT,
    dumpcap_log  TEXT,
    opcua_url    TEXT,
    host         TEXT
);
CREATE TABLE IF NOT EXISTS state_events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    ts_utc       TEXT NOT NULL,
    ts_monotonic REAL NOT NULL,
    zone         TEXT,
    tag          TEXT NOT NULL,
    value        TEXT,
    prev_value   TEXT,                 -- NULL == initial snapshot row
    vtype        TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    ts_utc       TEXT NOT NULL,
    ts_monotonic REAL NOT NULL,
    type         TEXT,                 -- heartbeat | disconnect | reconnect | note
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_state_run ON state_events(run_id);
CREATE INDEX IF NOT EXISTS idx_state_tag ON state_events(run_id, tag);
CREATE INDEX IF NOT EXISTS idx_state_ts  ON state_events(run_id, ts_utc);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
"""


def db_connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # check_same_thread=False: asyncua callbacks run in the loop thread; a single
    # connection + a short critical section is safe at our event rate.
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")      # durable + crash-friendly
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    return conn


def resolve_run_id(conn: sqlite3.Connection, raw_id: str) -> tuple[str, str, int, bool]:
    """
    Decide the run_id and whether this run OVERWRITES an existing one.

    Two intents, distinguished by whether you give a number:

      * BARE PREFIX  (e.g. "baseline")        -> allocate the NEXT sequence number
        (baseline_0001, _0002, ...). This is a brand-new run; never overwrites.

      * EXPLICIT ID  (e.g. "baseline_0003",   -> use THAT EXACT id and OVERWRITE
        or "baseline_3")                         everything already stored under
                                                 it. This is the "redo this exact
                                                 trial" case: when a trial gets
                                                 corrupted and you want to run it
                                                 again under the SAME id.

    The number is normalised to 4 digits, so "baseline_3", "baseline_003" and
    "baseline_0003" all resolve to the same canonical id "baseline_0003" — so a
    redo finds and replaces the right trial regardless of how you typed it.

    Returns:
        (run_id, prefix, seq_num, overwrite)
        overwrite == True  -> caller must purge any existing data for run_id first.
    """
    raw = raw_id.strip()
    prefix = re.sub(r"_\d+$", "", raw)
    if not prefix:
        raise ValueError("empty experiment id")

    m = re.search(r"_(\d+)$", raw)
    if m:
        # Explicit id -> exact, OVERWRITE mode (redo this specific trial).
        seq_num = int(m.group(1))
        return f"{prefix}_{seq_num:04d}", prefix, seq_num, True

    # Bare prefix -> allocate the next number (brand-new run).
    row = conn.execute("SELECT MAX(seq_num) FROM runs WHERE prefix = ?", (prefix,)).fetchone()
    seq_num = (row[0] or 0) + 1
    return f"{prefix}_{seq_num:04d}", prefix, seq_num, False


def purge_run(conn: sqlite3.Connection, run_id: str, results_dir: str) -> tuple[int, bool]:
    """
    Delete EVERY trace of run_id so it can be re-recorded cleanly.

    Removes, for this run_id:
      * all state_events rows,
      * all events rows,
      * the runs registry row,
      * the entire results/<run_id>/ folder (pcap, dumpcap log, any CSVs).

    Called from: main_async(), when resolve_run_id() returned overwrite=True (an
    explicit id) OR when the run_id already exists in the DB. This is what fixes
    the "I deleted the folder but it still skipped to the next number" problem:
    deleting the folder alone left the DB row behind; this clears BOTH.

    The DB connection is in autocommit mode (isolation_level=None), so the
    DELETEs take effect immediately.

    Args:
        conn: the SQLite connection.
        run_id: the exact run id to wipe.
        results_dir: base results directory (its <run_id> subfolder is removed).

    Returns:
        (n_state_rows_deleted, folder_removed)
    """
    import shutil
    n_state = conn.execute(
        "SELECT COUNT(*) FROM state_events WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    conn.execute("DELETE FROM state_events WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM events       WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM runs         WHERE run_id=?", (run_id,))

    folder = os.path.join(results_dir, run_id)
    removed = False
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
        removed = True
    return n_state, removed


def export_runs_csv(conn: sqlite3.Connection, path: str = RUNS_CSV):
    """Human-readable index of all runs, so you don't need SQL to see what's what."""
    import csv
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cols = ["run_id", "prefix", "description", "start_ts_utc", "end_ts_utc",
            "status", "pcap_path"]
    rows = conn.execute(
        f"SELECT {','.join(cols)} FROM runs ORDER BY prefix, seq_num"
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


# ==========================================================================
# PACKET CAPTURE (dumpcap) — the logger OWNS this.
# ==========================================================================

def start_capture(iface: str, pcap_path: str, log_path: str) -> subprocess.Popen:
    """
    Start dumpcap on `iface`, writing to `pcap_path`. Returns the Popen handle.
    Raises RuntimeError if dumpcap fails to start (so the run aborts before any
    state data is written — no half-instrumented runs).
    """
    os.makedirs(os.path.dirname(os.path.abspath(pcap_path)), exist_ok=True)
    logf = open(log_path, "w", encoding="utf-8")

    # -i interface, -w outfile, -q = less console noise. No capture filter: we
    # want ALL SPAN traffic (every port, incl. inter-PLC).
    cmd = [DUMPCAP, "-i", iface, "-w", pcap_path, "-q"]
    log.info(f"Starting capture: {' '.join(cmd)}")

    # New process group on Windows so OUR Ctrl-C does NOT kill dumpcap abruptly;
    # we stop it cleanly with CTRL_BREAK on shutdown (lets it finalize the pcap).
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                            creationflags=creationflags)

    # Confirm it actually started (bad iface / permissions → immediate exit).
    time.sleep(CAPTURE_VERIFY_S)
    if proc.poll() is not None:
        logf.close()
        tail = ""
        try:
            with open(log_path, encoding="utf-8") as f:
                tail = f.read()[-500:]
        except Exception:
            pass
        raise RuntimeError(f"dumpcap exited immediately (rc={proc.returncode}).\n{tail}")

    log.info(f"Capture running → {pcap_path}")
    return proc


def stop_capture(proc: subprocess.Popen):
    """Stop dumpcap cleanly so the pcap is finalized."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            # CTRL_BREAK to dumpcap's own process group → clean stop + flush.
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)
        log.info("Capture stopped cleanly.")
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=3)
            log.warning("Capture force-terminated.")
        except Exception as exc:
            log.error(f"Could not stop capture: {exc}")


# ==========================================================================
# OPC-UA STATE LOGGING
# ==========================================================================

class StateHandler:
    """
    asyncua data-change handler: writes one state_events row per actual change.
    `node_index` maps a NodeId string → (tag, zone, vtype). `prev` holds the
    last-seen value per tag so prev_value is correct and we never log a no-op.
    """
    def __init__(self, conn, run_id, node_index, prev, lock):
        self.conn = conn
        self.run_id = run_id
        self.node_index = node_index
        self.prev = prev
        self.lock = lock

    def datachange_notification(self, node: Node, val, data: DataChangeNotif):
        info = self.node_index.get(node.nodeid.to_string())
        if info is None:
            return
        tag, zone, vtype = info
        old = self.prev.get(tag, "__unset__")
        if old == val:
            return
        ts_utc = datetime.now(timezone.utc).isoformat()
        ts_mono = time.monotonic()
        prev_text = None if old == "__unset__" else str(old)
        with self.lock:
            self.conn.execute(
                "INSERT INTO state_events "
                "(run_id, ts_utc, ts_monotonic, zone, tag, value, prev_value, vtype) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self.run_id, ts_utc, ts_mono, zone, tag, str(val), prev_text, vtype),
            )
        self.prev[tag] = val
        log.info(f"  {tag:<28} {str(prev_text):<8} → {val}")

    def event_notification(self, event):
        pass


def write_event(conn, lock, run_id, etype, detail=""):
    ts_utc = datetime.now(timezone.utc).isoformat()
    with lock:
        conn.execute(
            "INSERT INTO events (run_id, ts_utc, ts_monotonic, type, detail) "
            "VALUES (?,?,?,?,?)",
            (run_id, ts_utc, time.monotonic(), etype, detail),
        )


async def resolve_nodes(client: Client):
    """Resolve every TAG_MAP entry to a live Node via its browse path.
    Returns (tag->Node, nodeid_str->(tag,zone,vtype))."""
    ns = await client.get_namespace_index(NAMESPACE_URI)
    log.info(f"Namespace '{NAMESPACE_URI}' → index {ns}")
    objects = client.nodes.objects
    tag_to_node, node_index = {}, {}
    missing = []
    for tag, (zone, display, vtype) in TAG_MAP.items():
        path = [f"{ns}:MATRIX", f"{ns}:{zone}", f"{ns}:{display}"]
        try:
            node = await objects.get_child(path)
            tag_to_node[tag] = node
            node_index[node.nodeid.to_string()] = (tag, zone, vtype)
        except Exception as exc:
            missing.append(tag)
            log.error(f"Could not resolve '{tag}' ({'/'.join(path)}): {exc}")
    log.info(f"Resolved {len(tag_to_node)}/{len(TAG_MAP)} tags"
             + (f"  (missing: {', '.join(missing)})" if missing else ""))
    return tag_to_node, node_index


async def snapshot_initial(tag_to_node, node_index, conn, run_id, prev, lock):
    """Read every tag once at (re)connect; write rows for new/changed values."""
    for tag, node in tag_to_node.items():
        try:
            val = await node.read_value()
        except Exception as exc:
            log.warning(f"  initial read failed {tag}: {exc}")
            continue
        _, zone, vtype = node_index[node.nodeid.to_string()]
        old = prev.get(tag, "__unset__")
        if old == val:
            continue
        ts_utc = datetime.now(timezone.utc).isoformat()
        prev_text = None if old == "__unset__" else str(old)
        with lock:
            conn.execute(
                "INSERT INTO state_events "
                "(run_id, ts_utc, ts_monotonic, zone, tag, value, prev_value, vtype) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, ts_utc, time.monotonic(), zone, tag, str(val), prev_text, vtype),
            )
        prev[tag] = val


async def logging_session(conn, run_id, lock, stop_flag):
    """
    Connect → snapshot → subscribe → idle loop (liveness probe + heartbeat).
    Reconnects on failure until stop_flag['stop'] is set. Returns on stop.
    """
    prev: dict = {}
    last_heartbeat = 0.0
    first_connect = True

    while not stop_flag["stop"]:
        client = Client(url=OPC_URL)
        try:
            await client.connect()
            log.info(f"Connected to {OPC_URL}")
            if not first_connect:
                write_event(conn, lock, run_id, "reconnect")
            first_connect = False

            tag_to_node, node_index = await resolve_nodes(client)
            if not tag_to_node:
                raise RuntimeError("no tags resolved — wrong server/namespace?")

            await snapshot_initial(tag_to_node, node_index, conn, run_id, prev, lock)

            handler = StateHandler(conn, run_id, node_index, prev, lock)
            sub = await client.create_subscription(SUB_PERIOD_MS, handler)
            await sub.subscribe_data_change(list(tag_to_node.values()))
            log.info(f"Subscribed to {len(tag_to_node)} tags — logging transitions "
                     f"(Ctrl-C to end run)")

            probe = next(iter(tag_to_node.values()))
            while not stop_flag["stop"]:
                # Liveness probe (raises on dead link → triggers reconnect).
                await asyncio.wait_for(probe.read_value(), timeout=2.0)
                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_SEC:
                    write_event(conn, lock, run_id, "heartbeat")
                    last_heartbeat = now
                await asyncio.sleep(LIVENESS_SEC)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not stop_flag["stop"]:
                log.error(f"OPC-UA session lost: {exc}")
                write_event(conn, lock, run_id, "disconnect", str(exc))
                log.info(f"Reconnecting in {RECONNECT_DELAY}s ...")
                await asyncio.sleep(RECONNECT_DELAY)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


# ==========================================================================
# MAIN
# ==========================================================================

async def main_async(args):
    conn = db_connect(args.db)
    run_id, prefix, seq_num, overwrite = resolve_run_id(conn, args.id)

    # Redo/overwrite handling: if an explicit id was given (overwrite=True) OR a
    # run with this id already exists, wipe ALL of its data first — DB rows
    # (state_events, events, runs) AND the results/<run_id>/ folder (pcap + logs)
    # — so re-running under the same id is a clean replacement, not a duplicate or
    # a silent skip to the next number.
    exists = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is not None
    if overwrite or exists:
        n_state, removed = purge_run(conn, run_id, args.results)
        log.warning(f"OVERWRITE {run_id}: purged {n_state} state rows, "
                    f"{'deleted' if removed else 'no'} results folder — re-recording clean.")

    run_dir   = os.path.join(args.results, run_id)
    pcap_path = os.path.join(run_dir, f"{run_id}.pcap")
    dumpcap_log = os.path.join(run_dir, f"{run_id}_dumpcap.log")
    os.makedirs(run_dir, exist_ok=True)

    print("=" * 72)
    print(f" MATRIX experiment logger")
    print(f"   run_id      : {run_id}")
    print(f"   description : {args.description or '(none)'}")
    print(f"   database    : {os.path.abspath(args.db)}")
    print(f"   results dir : {os.path.abspath(run_dir)}")
    print(f"   capture     : {'ON  (' + SPAN_NIC_NAME + ')' if not args.no_capture else 'OFF (--no-capture)'}")
    print(f"   opcua       : {OPC_URL}")
    print("   Ctrl-C to end the run.")
    print("=" * 72)

    # 1) Start capture FIRST — if it fails, abort before any state row exists.
    cap = None
    if not args.no_capture:
        try:
            cap = start_capture(args.iface, pcap_path, dumpcap_log)
        except Exception as exc:
            log.error(f"Capture failed to start — aborting run (no data written): {exc}")
            conn.close()
            return 2

    # 2) Register the run now that capture is confirmed up.
    conn.execute(
        "INSERT INTO runs (run_id, prefix, seq_num, description, start_ts_utc, "
        "status, pcap_path, dumpcap_log, opcua_url, host) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, prefix, seq_num, args.description,
         datetime.now(timezone.utc).isoformat(), "running",
         pcap_path if cap else None, dumpcap_log if cap else None,
         OPC_URL, os.environ.get("COMPUTERNAME") or os.uname().nodename
         if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "")),
    )
    export_runs_csv(conn)

    lock = threading.Lock()
    stop_flag = {"stop": False}

    # 3) Run the logging session until Ctrl-C (KeyboardInterrupt → CancelledError
    #    in the finally below), then clean up in a guaranteed order.
    status = "completed"
    try:
        await logging_session(conn, run_id, lock, stop_flag)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    except Exception as exc:
        log.error(f"Run error: {exc}")
        status = "aborted"
    finally:
        stop_flag["stop"] = True
        # Order matters: finalize the critical, synchronous persistence first.
        stop_capture(cap)                                   # finalize pcap
        with lock:
            conn.execute(
                "UPDATE runs SET end_ts_utc=?, status=? WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat(), status, run_id),
            )
        export_runs_csv(conn)
        n = conn.execute(
            "SELECT COUNT(*) FROM state_events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        log.info(f"Run {run_id} {status}: {n} state transitions logged.")
        print(f"\nRun '{run_id}' {status} — {n} transitions.")
        print(f"  pcap : {pcap_path if cap else '(none)'}")
        print(f"  db   : {os.path.abspath(args.db)}  (runs.csv updated)")
        conn.close()
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="MATRIX experiment logger (capture + state log).")
    # --id accepts two forms:
    #   bare prefix  "baseline"       -> next number (new run): baseline_0001, ...
    #   explicit id  "baseline_0003"  -> REDO that exact trial, OVERWRITING all its
    #                                    data (DB rows + results/<id>/). "baseline_3"
    #                                    and "baseline_003" also resolve to _0003.
    p.add_argument("--id", required=True,
                   help="experiment id / prefix, e.g. 'baseline' or "
                        "'tm221_modbus_injection'. Any trailing _NNNN is stripped "
                        "and auto-incremented, so runs never overwrite.")
    p.add_argument("--description", default="", help="free-text run description")
    p.add_argument("--url", default=OPC_URL, help="OPC-UA server URL")
    p.add_argument("--iface", default=SPAN_NIC,
                   help="capture interface (device path or name from `dumpcap -D`)")
    p.add_argument("--db", default=DB_DEFAULT, help="SQLite database path")
    p.add_argument("--results", default=RESULTS_DEFAULT, help="results directory")
    p.add_argument("--no-capture", action="store_true",
                   help="skip packet capture (FOR TESTING THE LOGGER ONLY)")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    # Allow --url override to take effect on the module-level constant.
    OPC_URL = args.url
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        rc = 0
    sys.exit(rc)