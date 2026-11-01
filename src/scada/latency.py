#!/usr/bin/env python3
"""
latency.py

MATRIX Testbed — PLC-to-SCADA latency benchmark (runs on the SCADA PC).

PURPOSE
    Quantify how much latency the Raspberry Pi middleware adds to SCADA's view of
    the plant, by comparing two paths for the SAME read on the SAME PLC tag:

      direct   : SCADA PC ── native protocol ──▶ PLC ──▶ back
                 (the "no middleware" reference — SCADA talks straight to the PLC,
                  exactly as it would if the Pi did not exist)

      indirect : SCADA PC ──OPC-UA──▶ Pi middleware ──native protocol──▶ PLC
                 ──▶ Pi ──OPC-UA──▶ SCADA PC
                 (the real production path, through the Pi's Request/Response
                  benchmark echo nodes)

    The gap (indirect − direct), per protocol, is the headline number: "the
    middleware adds X ms, which is still well within what SCADA monitoring
    needs" — the evidence that the Pi's role (segmentation + protocol translation
    + IIoT gateway + ZT policy-enforcement point) is worth its latency cost.

WHY THE DIRECT PATH DOES NOT RUN THE CLIENTS' POLL LOOP
    The middleware clients (siemens_client / ab_cip_client / tm221_client) are
    normally driven by their run() loop, which ALSO polls every 0.5 s. For the
    direct measurement we connect the client and take timed reads WITHOUT that
    background poll, for two reasons:
      1. Conservative: a clean single-connection read is the BEST case for the
         "no Pi" path, so we never understate the Pi's overhead.
      2. Safety: the AB pycomm3 driver is not safe for concurrent calls from two
         threads; the poll loop + benchmark read would collide.
    We still use the clients' own connection code and benchmark_read() functions
    (same code path as the Pi), so this is faithfully "the same client".

MEASUREMENT NOTE (the two paths are not identical stopwatches — by design)
    direct   RTT = time around one native protocol read.
    indirect RTT = write a counter to <PLC>_Request, then poll <PLC>_Response
                   until it echoes that counter. This legitimately includes the
                   Pi's echo-detection granularity (its 1 ms benchmark loop) and
                   the SCADA-side poll granularity (--poll). That is part of what
                   "SCADA visibility through the Pi" actually costs, so it belongs
                   in the number. We record enough per-sample detail that you can
                   reason about it in analysis.

OUTPUT (full per-sample dump — nothing aggregated here)
    results/latency-benchmark/latency_<label>_<YYYYmmdd_HHMMSS>.csv
    columns:
      timestamp_utc, run_label, path, protocol, plc, operation, phase,
      sample_index, rtt_ms, success, error, counter, inter_sample_delay_ms
    Compute means/medians/percentiles/jitter yourself in the notebooks.



USAGE
    python latency.py                                   # all PLCs, both paths
    python latency.py --samples 500 --warmup 10         # quicker run
    python latency.py --paths direct                    # direct only
    python latency.py --plcs siemens,tm221              # subset of PLCs
    python latency.py --label gateway_overhead_v1

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import argparse
import asyncio
import csv
import logging
import os
import statistics
import sys
import time
from datetime import datetime, timezone

# --- Make the middleware client modules importable -------------------------
# latency.py is in src/scada/; the clients are in src/middleware/. We insert the
# sibling folder on sys.path so `import siemens_client` etc. resolve to the exact
# same files that run on the Pi.
_HERE = os.path.dirname(os.path.abspath(__file__))
_MIDDLEWARE_DIR = os.path.normpath(os.path.join(_HERE, "..", "middleware"))
sys.path.insert(0, _MIDDLEWARE_DIR)

import siemens_client          # noqa: E402  (import after sys.path tweak)
import ab_cip_client           # noqa: E402
import tm221_client            # noqa: E402

# asyncua Client is used for the indirect path (OPC-UA client to the Pi server)
# and for connecting the Siemens client directly.
from asyncua import Client, ua  # noqa: E402

# ==========================================================================
# CONFIGURATION
# ==========================================================================

# Pi middleware OPC-UA server (the indirect path connects here).
PI_SERVER_URL = "opc.tcp://192.168.100.10:4840"
NAMESPACE_URI = "urn:MATRIX.Middleware.OPC-UA"      # must match opcua_server.py

# The SAME read target on each PLC for BOTH paths, so direct vs indirect is
# like-for-like. These match the tags the Pi's own echo loop reads.
SIEMENS_READ_TAG = "motorTurntable"                 # siemens_client.benchmark_read(tag)
AB_READ_TAG      = "SchneiderModbusHandshake"       # ab_cip_client.benchmark_read(ccw_name)
TM221_READ_ADDR  = 0                                # tm221_client.benchmark_read_coil(addr)

# Default sample plan (all overridable on the CLI).
DEFAULT_SAMPLES  = 1000     # measured samples per PLC per path
DEFAULT_WARMUP   = 20       # discarded-from-stats warmup samples (still logged)
DEFAULT_DELAY_MS = 50       # pacing between samples (measure latency, not throughput)
DEFAULT_TIMEOUT_MS = 2000   # per-sample timeout → counts as a failure, not dropped
DEFAULT_POLL_MS  = 1        # indirect: how often to re-read the Response node

OUTDIR_DEFAULT = os.path.join("results", "latency-benchmark")

CSV_COLUMNS = [
    "timestamp_utc", "run_label", "path", "protocol", "plc", "operation",
    "phase", "sample_index", "rtt_ms", "success", "error", "counter",
    "inter_sample_delay_ms",
]

# ==========================================================================
# LOGGING
# ==========================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(name)s]  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("asyncua").setLevel(logging.ERROR)   # silence asyncua chatter
log = logging.getLogger("LATENCY")


# ==========================================================================
# DIRECT PATH — connect each client, time native reads, disconnect.
# Each PLC exposes three coroutines (connect → read → close) plus a protocol
# label. We reuse the client modules' own connection primitives and
# benchmark_read functions so this is the same code path as the Pi.
# ==========================================================================

# ---- Siemens (OPC-UA to the PLC's own server at siemens_client.OPC_URL) ----
async def siemens_direct_connect():
    # Build the client exactly as siemens_client.run() does, but without the
    # subscription/poll loop — we only need a live session for benchmark_read().
    client = Client(url=siemens_client.OPC_URL)        # the S7-1200's OPC-UA server
    await siemens_client._apply_security(client)       # no-op unless auth configured
    await client.connect()
    siemens_client._active_client = client             # benchmark_read() reads this global
    return client

async def siemens_direct_read():
    # Fresh single-node read on the PLC; returns the value (we ignore it, we time it).
    return await siemens_client.benchmark_read(SIEMENS_READ_TAG)

async def siemens_direct_close(client):
    siemens_client._active_client = None               # clear the global we set
    try:
        await client.disconnect()
    except Exception:
        pass


# ---- Allen-Bradley (EtherNet/IP CIP, pycomm3 — blocking, run in a thread) ----
async def ab_direct_connect():
    # _blocking_connect opens a LogixDriver; run it off the event loop via a thread.
    plc = await asyncio.to_thread(ab_cip_client._blocking_connect, ab_cip_client.PLC_IP)
    ab_cip_client._plc = plc                           # benchmark_read() reads this global
    return plc

async def ab_direct_read():
    return await ab_cip_client.benchmark_read(AB_READ_TAG)

async def ab_direct_close(plc):
    ab_cip_client._plc = None
    try:
        await asyncio.to_thread(ab_cip_client._blocking_close, plc)
    except Exception:
        pass


# ---- Schneider TM221 (Modbus TCP, pymodbus async) ----
async def tm221_direct_connect():
    # Reuse the exact AsyncModbusTcpClient class and params from the client module.
    client = tm221_client.AsyncModbusTcpClient(
        host=tm221_client.PLC_IP, port=tm221_client.MODBUS_PORT, timeout=10, retries=3
    )
    await client.connect()
    if not client.connected:                            # pymodbus connects lazily; verify
        raise ConnectionError(f"could not connect to TM221 at {tm221_client.PLC_IP}")
    tm221_client._client = client                       # benchmark_read_coil() reads this global
    return client

async def tm221_direct_read():
    return await tm221_client.benchmark_read_coil(TM221_READ_ADDR)

async def tm221_direct_close(client):
    tm221_client._client = None
    try:
        client.close()                                  # pymodbus close is synchronous
    except Exception:
        pass


# Registry: plc name → (connect, read, close, protocol-label-for-direct)
DIRECT = {
    "siemens": (siemens_direct_connect, siemens_direct_read, siemens_direct_close, "opcua"),
    "ab":      (ab_direct_connect,      ab_direct_read,      ab_direct_close,      "cip"),
    "tm221":   (tm221_direct_connect,   tm221_direct_read,   tm221_direct_close,   "modbus"),
}

# Indirect path: plc name → (RequestNodeName, ResponseNodeName) under MATRIX/Benchmark.
INDIRECT_NODES = {
    "siemens": ("Siemens_Request", "Siemens_Response"),
    "ab":      ("AB_Request",      "AB_Response"),
    "tm221":   ("TM221_Request",   "TM221_Response"),
}


# ==========================================================================
# GENERIC MEASUREMENT LOOP
# Takes a `sample_once` coroutine that performs ONE timed operation and returns
# (success, rtt_ms, error, counter). Handles warmup/measure phases, pacing, CSV
# writing (flushed per row for crash-safety), and collecting measure-phase RTTs
# for the end-of-run summary.
# ==========================================================================

async def measure(sample_once, *, path, protocol, plc, operation, args, writer, fh, stats):
    total = args.warmup + args.samples
    key = (path, plc)
    stats.setdefault(key, {"rtts": [], "fail": 0})

    for i in range(total):
        # First args.warmup samples are labelled 'warmup' and excluded from stats
        # (but still written to the CSV — nothing is discarded, only labelled).
        phase = "warmup" if i < args.warmup else "measure"
        idx = i if phase == "warmup" else i - args.warmup

        ts = datetime.now(timezone.utc).isoformat()     # wall clock, for pcap correlation
        success, rtt_ms, err, counter = await sample_once()

        writer.writerow([
            ts, args.label, path, protocol, plc, operation, phase, idx,
            f"{rtt_ms:.4f}" if rtt_ms is not None else "",   # blank on failure
            1 if success else 0,
            err or "",
            counter if counter is not None else "",
            args.delay,
        ])
        fh.flush()                                       # crash-safe: keep partial data

        # Collect only measured, successful samples for the summary table.
        if phase == "measure":
            if success and rtt_ms is not None:
                stats[key]["rtts"].append(rtt_ms)
            else:
                stats[key]["fail"] += 1

        # Pace the next sample (so we measure latency, not saturation throughput).
        await asyncio.sleep(args.delay / 1000.0)


def make_direct_sampler(read_fn, timeout_s):
    """Return a `sample_once` for the direct path timing one native read."""
    async def once():
        t0 = time.perf_counter()                         # monotonic, high-res — for intervals
        try:
            # wait_for enforces the per-sample timeout; a timeout is a data point.
            await asyncio.wait_for(read_fn(), timeout=timeout_s)
            return True, (time.perf_counter() - t0) * 1000.0, None, None
        except asyncio.TimeoutError:
            return False, None, "timeout", None
        except Exception as exc:                          # link drop, protocol error, etc.
            return False, None, repr(exc), None
    return once


def make_indirect_sampler(request_node, response_node, counter_box, timeout_s, poll_s):
    """
    Return a `sample_once` for the indirect path: write an incrementing counter to
    the Request node, then poll the Response node until it echoes that counter.
    counter_box is a 1-element list used as a mutable counter shared across calls.
    """
    async def once():
        counter_box[0] += 1                              # unique value per sample
        c = counter_box[0]
        t0 = time.perf_counter()
        try:
            # Write the request counter (Int64 to match the echo node type).
            await request_node.write_value(ua.Variant(c, ua.VariantType.Int64))
            deadline = t0 + timeout_s
            # Poll the response until it equals our counter, or we time out.
            while True:
                resp = await response_node.read_value()
                if resp == c:                            # the Pi echoed our counter back
                    return True, (time.perf_counter() - t0) * 1000.0, None, c
                if time.perf_counter() >= deadline:
                    return False, None, "echo-timeout", c
                await asyncio.sleep(poll_s)              # re-read cadence (adds to measured RTT)
        except Exception as exc:
            return False, None, repr(exc), c
    return once


# ==========================================================================
# SUMMARY (printed to console only; the CSV is the source of truth)
# ==========================================================================

def _percentile(sorted_vals, p):
    """Linear-interpolated percentile (p in 0..1) of an already-sorted list."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p                       # fractional rank
    f = int(k)                                           # lower index
    c = min(f + 1, len(sorted_vals) - 1)                 # upper index (clamped)
    if f == c:
        return sorted_vals[f]
    # interpolate between the two neighbouring samples
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def print_summary(stats):
    print("\n" + "=" * 86)
    print(f"{'path':<9}{'plc':<9}{'n':>6}{'fail':>6}{'median':>10}{'p95':>10}"
          f"{'p99':>10}{'max':>10}   (ms)")
    print("-" * 86)
    for (path, plc), d in sorted(stats.items()):
        rtts = sorted(d["rtts"])
        n = len(rtts)
        if n == 0:
            print(f"{path:<9}{plc:<9}{0:>6}{d['fail']:>6}{'—':>10}{'—':>10}{'—':>10}{'—':>10}")
            continue
        med = statistics.median(rtts)
        p95 = _percentile(rtts, 0.95)
        p99 = _percentile(rtts, 0.99)
        mx  = rtts[-1]
        print(f"{path:<9}{plc:<9}{n:>6}{d['fail']:>6}"
              f"{med:>10.3f}{p95:>10.3f}{p99:>10.3f}{mx:>10.3f}")
    print("=" * 86)
    print("Full per-sample data is in the CSV — compute any statistic you need there.\n")


# ==========================================================================
# CSV OPENING — one file per --label, shared across separate path runs.
# ==========================================================================
# This is the ONLY change from the single-invocation version: so that you can
# run the two paths in SEPARATE invocations (e.g. direct with the middleware
# stopped, then indirect with it running) and have both land in ONE file that
# the analysis notebook reads as a single run.
#
# Behaviour:
#   * File named latency_<label>.csv (no timestamp) — stable per label.
#   * First run creates it with the header.
#   * A later run APPENDS (header written only once).
#   * If a path you are about to write ALREADY has rows in the file (you re-ran
#     the same path), those stale rows are REMOVED first, so you never get
#     silent duplicates — the re-run cleanly replaces that path's data while
#     keeping the other path's data.
#   * New rows are still streamed+flushed per sample, so a crash mid-run keeps
#     whatever was written up to that point.
# The 'path' value lives in CSV column index 2 (see CSV_COLUMNS).
_PATH_COL = CSV_COLUMNS.index("path")   # == 2


def prepare_csv(out_path, paths_to_write):
    """Create or append-prepare the per-label CSV; return (file_handle, writer)
    opened in append mode. Removes any existing rows whose path is in
    paths_to_write so a re-run of a path replaces (not duplicates) its data."""
    paths_to_write = set(paths_to_write)

    if os.path.exists(out_path):
        # Read what's already there and keep only the OTHER path's rows.
        with open(out_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if rows:
            header, body = rows[0], rows[1:]
            kept = [r for r in body if len(r) > _PATH_COL and r[_PATH_COL] not in paths_to_write]
            removed = len(body) - len(kept)
            # Rewrite header + kept rows (drops stale same-path rows, if any).
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(kept)
            if removed:
                log.warning(f"replaced {removed} existing row(s) for path(s) "
                            f"{sorted(paths_to_write)} in {os.path.basename(out_path)}")
            log.info(f"appending to existing {os.path.basename(out_path)} "
                     f"({len(kept)} row(s) from other path(s) preserved)")
        else:
            # File exists but is empty → (re)write the header.
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(CSV_COLUMNS)
    else:
        # Fresh file → write the header once.
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_COLUMNS)
        log.info(f"created new {os.path.basename(out_path)}")

    fh = open(out_path, "a", newline="", encoding="utf-8")   # append from here on
    return fh, csv.writer(fh)


# ==========================================================================
# MAIN
# ==========================================================================

async def run_direct(plcs, args, writer, fh, stats):
    for plc in plcs:
        if plc not in DIRECT:
            log.warning(f"unknown plc '{plc}' — skipping")
            continue
        connect, read_fn, close, protocol = DIRECT[plc]
        log.info(f"[direct]   {plc}: connecting ...")
        try:
            handle = await connect()
        except Exception as exc:
            log.error(f"[direct]   {plc}: connect FAILED ({exc}) — skipping this PLC")
            continue
        log.info(f"[direct]   {plc}: connected via {protocol}; "
                 f"{args.warmup} warmup + {args.samples} samples")
        try:
            sampler = make_direct_sampler(read_fn, args.timeout / 1000.0)
            await measure(sampler, path="direct", protocol=protocol, plc=plc,
                          operation="read", args=args, writer=writer, fh=fh, stats=stats)
        finally:
            await close(handle)                          # always release the connection


async def run_indirect(plcs, args, writer, fh, stats):
    log.info(f"[indirect] connecting to Pi server {args.url} ...")
    client = Client(url=args.url)
    try:
        await client.connect()
    except Exception as exc:
        log.error(f"[indirect] connect to Pi FAILED ({exc}) — skipping indirect path")
        return
    try:
        # Resolve the benchmark echo nodes under Objects/MATRIX/Benchmark/.
        ns = await client.get_namespace_index(NAMESPACE_URI)
        objects = client.nodes.objects
        for plc in plcs:
            if plc not in INDIRECT_NODES:
                log.warning(f"unknown plc '{plc}' — skipping")
                continue
            req_name, resp_name = INDIRECT_NODES[plc]
            try:
                req_node = await objects.get_child([f"{ns}:MATRIX", f"{ns}:Benchmark", f"{ns}:{req_name}"])
                resp_node = await objects.get_child([f"{ns}:MATRIX", f"{ns}:Benchmark", f"{ns}:{resp_name}"])
            except Exception as exc:
                log.error(f"[indirect] {plc}: could not resolve echo nodes ({exc}) — skipping")
                continue
            # Seed the counter ABOVE the current Response value so a stale echo
            # from a previous run can never be mistaken for a fresh match.
            base = await resp_node.read_value()
            counter_box = [int(base)]
            log.info(f"[indirect] {plc}: {args.warmup} warmup + {args.samples} samples "
                     f"(echo from counter {base + 1})")
            sampler = make_indirect_sampler(
                req_node, resp_node, counter_box,
                timeout_s=args.timeout / 1000.0, poll_s=args.poll / 1000.0,
            )
            await measure(sampler, path="indirect", protocol="opcua-echo", plc=plc,
                          operation="read", args=args, writer=writer, fh=fh, stats=stats)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main_async(args):
    # Only read-path latency is implemented here. Write-path timing needs the
    # per-PLC benchmark scratch tags configured (and writes aren't idempotent),
    # so it's a separate future mode.
    if args.operation != "read":
        log.error("Only --operation read is implemented (write-path needs scratch "
                  "tags; use read for now).")
        return 2

    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    plcs  = [p.strip() for p in args.plcs.split(",") if p.strip()]

    os.makedirs(args.outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(args.outdir, f"latency_{args.label}.csv")

    print("=" * 72)
    print(" MATRIX latency benchmark")
    print(f"   label    : {args.label}")
    print(f"   paths    : {', '.join(paths)}")
    print(f"   plcs     : {', '.join(plcs)}")
    print(f"   plan     : {args.warmup} warmup + {args.samples} measured, "
          f"{args.delay} ms pacing, {args.timeout} ms timeout")
    print(f"   output   : {os.path.abspath(out_path)}")
    print("=" * 72)

    stats = {}
    # Open the per-label file in combine/append mode (header written once, stale
    # same-path rows replaced). This is what lets a separate direct run and a
    # separate indirect run share ONE latency_<label>.csv.
    fh, writer = prepare_csv(out_path, paths)
    try:
        if "direct" in paths:
            await run_direct(plcs, args, writer, fh, stats)
        if "indirect" in paths:
            await run_indirect(plcs, args, writer, fh, stats)
    finally:
        fh.close()

    print_summary(stats)
    log.info(f"Done. Raw samples: {os.path.abspath(out_path)}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="MATRIX PLC→SCADA latency benchmark "
                                            "(direct vs indirect-through-Pi).")
    p.add_argument("--samples", type=int, default=DEFAULT_SAMPLES,
                   help=f"measured samples per PLC per path (default {DEFAULT_SAMPLES})")
    p.add_argument("--warmup", type=int, default=DEFAULT_WARMUP,
                   help=f"warmup samples (logged, excluded from stats; default {DEFAULT_WARMUP})")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY_MS,
                   help=f"inter-sample pacing in ms (default {DEFAULT_DELAY_MS})")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_MS,
                   help=f"per-sample timeout in ms (default {DEFAULT_TIMEOUT_MS})")
    p.add_argument("--poll", type=float, default=DEFAULT_POLL_MS,
                   help=f"indirect: Response re-read cadence in ms (default {DEFAULT_POLL_MS})")
    p.add_argument("--paths", default="direct,indirect",
                   help="comma list: direct,indirect (default both)")
    p.add_argument("--plcs", default="siemens,ab,tm221",
                   help="comma list of PLCs (default all three)")
    p.add_argument("--operation", default="read", choices=["read", "write"],
                   help="read (default). write needs scratch tags (not yet implemented)")
    p.add_argument("--url", default=PI_SERVER_URL,
                   help="Pi middleware OPC-UA server URL (indirect path)")
    p.add_argument("--outdir", default=OUTDIR_DEFAULT, help="output directory for CSV")
    p.add_argument("--label", default="run", help="label embedded in filename + rows")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.info("Interrupted — partial CSV kept.")
        rc = 0
    sys.exit(rc)