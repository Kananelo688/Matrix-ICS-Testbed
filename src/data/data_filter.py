#!/usr/bin/env python3
"""
data_filter.py

MATRIX Testbed

Decription:
    For a baseline experiment (N trials of the SAME 30-workpiece program), it
    reconstructs, PER SIGNAL, the ordered sequence of states (HIGH, LOW, HIGH, ...)
    and the AVERAGE DURATION of each state at each step position, pooled across the
    trials that pass validation. That is: "the 1st HIGH of sliderMagazine lasts
    1.50 s on average, the following LOW lasts 3.42 s, the 2nd HIGH lasts ...",
    all the way through the full 30-piece run. The result is written as a tidy CSV
    that a separate plotter lays out end-to-end into 30-piece timing diagrams.


THE PIPELINE (order matters)
    1. LOAD each signal per trial from the SQLite state log.
    2. CANONICALISE: drop the duplicate AB-tracked position sensor and rename the
       Siemens 'inPosition' -> 'turntableInPosition' (one position sensor only).
    3. DEBOUNCE each signal: any state held < --t_min seconds is a glitch and is
       ABSORBED INTO THE PREVIOUS STATE (e.g. the light-barrier blip when the
       pusher retracts before the workpiece re-blocks it). Debounce runs BEFORE
       counting, so glitches cannot inflate the transition count.
    4. GATE on ACTUATORS: after debounce, every ACTUATOR must have the same number
       of transitions as the modal count across trials. A trial that deviates on
       ANY actuator is SKIPPED ENTIRELY (actuation anomalies are not tolerated).
       Sensors are reported but do NOT gate (they are noise-prone).
    5. AVERAGE by STEP ORDINAL: for each signal, align trials by step index (the
       k-th HIGH / k-th LOW), and average each step's duration across kept trials.
       (Alignment is by ordinal, never by wall-clock time.)


OUTPUTS
    results/<experiment-id>/process_states.csv   — one row per
        (signal, role, step_index, state, mean_dur_s, std_s, n_trials, cum_start_s)
    results/<experiment-id>/extraction_report.txt — t_min used, before/after count
        tables, trials KEPT vs SKIPPED and the exact actuator(s) that caused each
        skip (so you know what to fix before re-running).

USAGE
    python3 src/data/data_filter.py --experiment-id baseline30wps --t_min 0.5
    # tune the glitch threshold after reading the report's short-pulse histogram.

Author : MATRIX / Intelligent Connectivity Group — UCT
"""

import argparse
import os
import shutil
import sqlite3
import tempfile
from collections import Counter

import numpy as np
import pandas as pd

# 
# SIGNAL TAXONOMY
# 
# ACTUATORS are the KEY, GATING signals: a trial inconsistent on any of these
# (after debounce) is skipped entirely. All nine are empirically reproducible
# (identical debounced step-count across trials).
ACTUATORS = [
    "sliderMagazine", "motorTurntable", "drillActive", "weldActive",     # Turntable
    "rotateToConveyor", "vacuumGripper",                                 # Transfer
    "conveyorBelt", "separatorValve", "sliderMotor",                     # Conveyor
]
# REPORTED actuators: physical actuators that we extract and draw, but DO NOT gate
# on, because their edge count is not reproducible across trials.
#   rotateToTable: the AB ST code drives this motor flag in TWO controller states
#   per piece (State 1 = table approach, State 5 = an 800 ms retreat), and the
#   arm hunts near the limit switch, so the number of >0.5 s pulses varies
#   run-to-run. Its reproducible counterpart is the LIMIT-SWITCH
#   sensor transferUnitAtTurntable (consistent), which stays in SENSORS below. We
#   therefore report rotateToTable but gate the transfer stage on rotateToConveyor
#   (reproducible) + the limit-switch sensors.
REPORTED = [
    "rotateToTable",
]
# SENSORS are included in the diagram and reported, but do NOT gate (noise-prone).
SENSORS = [
    "turntableInPosition",            # <- Siemens 'inPosition', renamed (see below)
    "magazineEmpty", "workpieceOnConveyor", "workpieceOnPallet", "palletReady",
    "sliderInPosition", "transferUnitAtTurntable", "transferUnitAtConveyor",
]
SIGNALS = ACTUATORS + REPORTED + SENSORS
ROLE = {**{s: "actuator" for s in ACTUATORS},
        **{s: "actuator(reported)" for s in REPORTED},
        **{s: "sensor" for s in SENSORS}}

# (No per-signal gate-min-width rule is needed now that rotateToTable is reported
# rather than gated.)
GATE_MIN_WIDTH = {}

# Canonicalisation: inPosition and the AB-tracked turntableInPosition are the SAME
# physical sensor. Keep ONLY the Siemens-tracked one and rename it. The AB copy is
# dropped so we never double-count it.
RENAME       = {"inPosition": "turntableInPosition"}   # source tag -> canonical name
DROP_RAW_TAGS = {"turntableInPosition"}                # the AB copy, by its raw name



# DB LOAD

def load_db(db_path, prefix):
    """Load all state_events for runs matching '<prefix>_%' as a DataFrame.

    Called from: main(). Opens read-only (copying first if the DB is on a
    read-only mount). Coerces 'value' to numeric using 'vtype' (bool->0/1).

    Args:
        db_path (str): path to the logger's matrix.db.
        prefix (str): experiment id; runs matched are run_id LIKE '<prefix>_%'.

    Returns:
        pandas.DataFrame with columns run_id, ts_monotonic, tag, num (float).

    Raises:
        FileNotFoundError: if db_path does not exist.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    try:
        con = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        tmp = os.path.join(tempfile.gettempdir(), "matrix_extract_ro.db")
        shutil.copy(db_path, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    df = pd.read_sql_query(
        "SELECT run_id, ts_monotonic, tag, value, vtype "
        "FROM state_events WHERE run_id LIKE ? ORDER BY run_id, seq",
        con, params=(prefix + "_%",))
    con.close()
    df["num"] = np.where(df["vtype"] == "bool",
                         df["value"].map(lambda v: 1.0 if str(v) == "True" else 0.0),
                         pd.to_numeric(df["value"], errors="coerce"))
    return df


#
# SIGNAL RECONSTRUCTION + DEBOUNCE
# 
def signal_segments(times, vals):
    """Collapse a transition list into contiguous (value, start, end) segments.

    Called from: debounce() and extract_steps(). Consecutive equal values are
    merged, so the result is strictly alternating in value.

    Args:
        times (np.ndarray): transition timestamps (monotonic), sorted.
        vals  (np.ndarray): value at/after each transition (0/1).

    Returns:
        list[tuple]: [(value, t_start, t_end), ...] covering [times[0], times[-1]].
    """
    segs = []
    for i in range(len(times) - 1):
        v, t0, t1 = vals[i], times[i], times[i + 1]
        if segs and segs[-1][0] == v:              # merge equal-valued neighbours
            segs[-1] = (v, segs[-1][1], t1)
        else:
            segs.append((v, t0, t1))
    return segs


def debounce(segs, t_min):
    """Remove glitches: absorb any segment shorter than t_min into the PREVIOUS
    state, then re-merge.

    Called from: extract_steps(), once per (trial, signal), BEFORE counting
    transitions. "Absorb into the previous state" means a too-short segment's
    duration is handed back to the segment before it (its value is discarded), so
    a brief spike in the middle of a long HIGH simply disappears and the HIGH is
    continuous. A leading too-short segment (no previous) is merged into the next.

    Args:
        segs (list[tuple]): (value, t0, t1) segments from signal_segments().
        t_min (float): minimum valid state duration in seconds.

    Returns:
        list[tuple]: debounced, strictly-alternating segments.
    """
    if not segs:
        return segs
    out = []
    for v, t0, t1 in segs:
        dur = t1 - t0
        if dur < t_min and out:
            # absorb into previous: extend previous segment's end, drop this value
            pv, pt0, _ = out[-1]
            out[-1] = (pv, pt0, t1)
        elif dur < t_min and not out:
            # leading glitch with no previous -> fold forward into the next by just
            # starting the record at this t0 but deferring the value decision
            out.append((v, t0, t1))            # will be merged below if next==v
        else:
            if out and out[-1][0] == v:
                out[-1] = (out[-1][0], out[-1][1], t1)
            else:
                out.append((v, t0, t1))
    # final re-merge of any equal neighbours created by absorption
    merged = []
    for s in out:
        if merged and merged[-1][0] == s[0]:
            merged[-1] = (s[0], merged[-1][1], s[2])
        else:
            merged.append(s)
    return merged


def extract_steps(df_run, tag, t_min):
    """Return the debounced step sequence for one signal in one trial.

    Called from: per-trial processing in run(). Produces the ordered list of
    (state, duration) steps used for positional averaging and for counting.

    Args:
        df_run (DataFrame): rows for a single run_id.
        tag (str): the signal tag (already canonicalised).
        t_min (float): debounce threshold (s).

    Returns:
        list[tuple]: [(state(int 0/1), duration(float s)), ...] in time order.
    """
    g = df_run[df_run["tag"] == tag].sort_values("ts_monotonic")
    if len(g) < 2:
        return []
    segs = signal_segments(g["ts_monotonic"].to_numpy(), g["num"].to_numpy())
    segs = debounce(segs, t_min)

    # Per-signal gate-min-width: drop HIGH pulses shorter than the signal's
    # threshold (they are not a gated/averaged actuation), absorbing them into the
    # surrounding LOW. This is how rotateToTable's sub-second RETREAT is excluded
    # while its ~1 s APPROACH is kept (see GATE_MIN_WIDTH note above).
    gmin = GATE_MIN_WIDTH.get(tag)
    if gmin is not None:
        kept = []
        for (v, t0, t1) in segs:
            if int(v) == 1 and (t1 - t0) < gmin:
                continue                                   # drop the short HIGH
            if kept and kept[-1][0] == v:                  # re-merge neighbours
                kept[-1] = (kept[-1][0], kept[-1][1], t1)
            else:
                kept.append((v, t0, t1))
        # merge any adjacent LOWs left where a HIGH was removed
        merged = []
        for s in kept:
            if merged and merged[-1][0] == s[0]:
                merged[-1] = (s[0], merged[-1][1], s[2])
            else:
                merged.append(s)
        segs = merged

    return [(int(v), t1 - t0) for (v, t0, t1) in segs]


# 
# MAIN EXTRACTION
# 
def run(args):
    df = load_db(args.db, args.experiment_id)
    runs = sorted(df["run_id"].unique())
    report = []   # lines for the extraction report

    def rpt(line=""):
        report.append(line); print(line)

    rpt(f"MATRIX timing extraction — experiment '{args.experiment_id}'")
    rpt(f"t_min (debounce) = {args.t_min}s   trials found = {len(runs)}")
    rpt("")

    # Canonicalise: drop AB position copy, rename Siemens inPosition 
    df = df[~df["tag"].isin(DROP_RAW_TAGS)].copy()
    df["tag"] = df["tag"].replace(RENAME)

    # Per-trial debounced step sequences for every signal 
    # steps[run][tag] = [(state, dur), ...]
    steps = {r: {} for r in runs}
    for r in runs:
        gr = df[df["run_id"] == r]
        for tag in SIGNALS:
            steps[r][tag] = extract_steps(gr, tag, args.t_min)

    # Transition-count tables BEFORE vs AFTER debounce (for the report)
    def raw_count(r, tag):
        return int((df[(df.run_id == r) & (df.tag == tag)]).shape[0])

    rpt("Transition counts per ACTUATOR (raw -> debounced), per trial:")
    rpt(f"  {'signal':<20}" + "".join(f"{r[-4:]:>14}" for r in runs))
    for tag in ACTUATORS:
        cells = []
        for r in runs:
            raw = raw_count(r, tag)
            deb = len(steps[r][tag])
            cells.append(f"{raw}->{deb}")
        rpt(f"  {tag:<20}" + "".join(f"{c:>14}" for c in cells))
    rpt("")

    # Modal actuator step-count across trials; gate each trial
    modal = {}
    for tag in ACTUATORS:
        counts = [len(steps[r][tag]) for r in runs]
        modal[tag] = Counter(counts).most_common(1)[0][0]

    kept, skipped = [], {}
    for r in runs:
        bad = [tag for tag in ACTUATORS if len(steps[r][tag]) != modal[tag]]
        if bad:
            skipped[r] = bad
        else:
            kept.append(r)

    rpt("Trial validation (gate = actuators match modal step-count after debounce):")
    rpt(f"  modal actuator step-counts: "
        + ", ".join(f"{t}={modal[t]}" for t in ACTUATORS))
    for r in runs:
        if r in skipped:
            detail = ", ".join(f"{t}({len(steps[r][t])}!={modal[t]})" for t in skipped[r])
            rpt(f"  SKIP  {r}  — inconsistent actuator(s): {detail}")
        else:
            rpt(f"  KEEP  {r}")
    rpt(f"\n  kept {len(kept)}/{len(runs)} trials.")
    if not kept:
        rpt("  No consistent trials — nothing to average. "
            "Fix the flagged actuator(s) or raise --t_min, then re-run.")
    rpt("")

    # --- Sensor consistency (reported only, does NOT gate) ---
    rpt("Sensor step-counts across KEPT trials (reported; sensors do not gate):")
    for tag in SENSORS:
        counts = [len(steps[r][tag]) for r in kept] if kept else []
        note = "consistent" if len(set(counts)) <= 1 else "VARIES"
        rpt(f"  {tag:<24} {counts}  {note}")
    rpt("")

    # --- Positional (step-ordinal) averaging over KEPT trials ---
    # For each signal, align by step index; average duration of step k across the
    # kept trials that have a step k. Also carry the modal STATE of step k.
    rows = []
    for tag in SIGNALS:
        # number of steps to average = min across kept trials (so step k exists
        # in every averaged trial). For actuators this equals modal by construction.
        if not kept:
            continue
        lengths = [len(steps[r][tag]) for r in kept]
        nsteps = min(lengths) if lengths else 0
        cum = 0.0
        for k in range(nsteps):
            durs = [steps[r][tag][k][1] for r in kept]
            states = [steps[r][tag][k][0] for r in kept]
            state = Counter(states).most_common(1)[0][0]   # modal state at step k
            mean = float(np.mean(durs)); std = float(np.std(durs))
            rows.append({
                "signal": tag, "role": ROLE[tag], "step_index": k,
                "state": state, "mean_dur_s": round(mean, 4),
                "std_s": round(std, 4), "n_trials": len(durs),
                "cum_start_s": round(cum, 4),
            })
            cum += mean

    out_df = pd.DataFrame(rows)
    out_dir = os.path.join(args.results, args.experiment_id)
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "process_states.csv")
    out_df.to_csv(csv_path, index=False)
    rpt(f"wrote {csv_path}  ({len(out_df)} rows: "
        f"{out_df.signal.nunique() if len(out_df) else 0} signals)")

    # --- Short-pulse histogram (helps you choose --t_min next time) ---
    rpt("")
    rpt("Short-pulse histogram (RAW, pre-debounce) — pick --t_min above the glitch "
        "band but below real actuations:")
    rpt(f"  {'signal':<20}{'<0.2s':>7}{'<0.3s':>7}{'<0.5s':>7}{'<0.7s':>7}{'min_s':>9}")
    for tag in SIGNALS:
        d = []
        for r in runs:
            g = df[(df.run_id == r) & (df.tag == tag)].sort_values("ts_monotonic")
            if len(g) < 2:
                continue
            d.extend(np.diff(g["ts_monotonic"].to_numpy()).tolist())
        d = np.array(d)
        if d.size == 0:
            continue
        rpt(f"  {tag:<20}{(d<0.2).sum():>7}{(d<0.3).sum():>7}{(d<0.5).sum():>7}"
            f"{(d<0.7).sum():>7}{d.min():>9.3f}")

    # --- Write the report sidecar ---
    rep_path = os.path.join(out_dir, "extraction_report.txt")
    with open(rep_path, "w") as f:
        f.write("\n".join(report) + "\n")
    print(f"\nwrote {rep_path}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="MATRIX process-state timing extractor.")
    p.add_argument("--experiment-id", required=True,
                   help="experiment prefix; pools runs run_id LIKE '<id>_%%'")
    p.add_argument("--t_min", type=float, default=0.5,
                   help="debounce threshold in seconds: states shorter than this "
                        "are absorbed into the PREVIOUS state (default 0.5)")
    p.add_argument("--db", default=os.path.join("database", "matrix.db"),
                   help="path to the logger SQLite DB (default database/matrix.db)")
    p.add_argument("--results", default="results",
                   help="base results directory (default results/)")
    return p


if __name__ == "__main__":
    import sys
    sys.exit(run(build_parser().parse_args()))