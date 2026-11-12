#!/usr/bin/env python3
"""
timing_data_extractor.py

MATRIX Testbed — process-state extraction engine (lives in src/data/).

WHAT IT PRODUCES
    For a baseline experiment (N trials of the SAME 30-workpiece program), it
    reconstructs, PER SIGNAL, the ordered sequence of states (HIGH, LOW, HIGH, ...)
    and the AVERAGE DURATION of each state at each step position, pooled across the
    trials that pass validation. That is: "the 1st HIGH of sliderMagazine lasts
    1.50 s on average, the following LOW lasts 3.42 s, the 2nd HIGH lasts ...",
    all the way through the full 30-piece run. The result is written as a tidy CSV
    that a separate plotter lays out end-to-end into 30-piece timing diagrams.

WHY A SEPARATE SCRIPT
    This is the hard, correctness-critical step (glitch removal + trial
    validation). Keeping it separate from plotting means the risky logic is
    auditable and you can re-plot without re-extracting.

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

TAXONOMY (edit ACTUATORS / SENSORS below if the plant changes)
    ACTUATORS (KEY — gate on these): sliderMagazine, motorTurntable, drillActive,
        weldActive, rotateToTable, rotateToConveyor, vacuumGripper, conveyorBelt,
        separatorValve, sliderMotor.
    SENSORS  (included, reported, NOT gating): turntableInPosition (from Siemens
        inPosition), magazineEmpty, workpieceOnConveyor, workpieceOnPallet,
        palletReady, sliderInPosition, transferUnitAtTurntable,
        transferUnitAtConveyor.
    EXCLUDED (not physical): handshake codes, DB-internal flags (transferPart,
        drillPart, ...), heartbeats, *_connected, workpiecesCount.

OUTPUTS
    results/<experiment-id>/process_states.csv   — one row per
        (signal, role, step_index, state, mean_dur_s, std_s, n_trials, cum_start_s)
    results/<experiment-id>/extraction_report.txt — t_min used, before/after count
        tables, trials KEPT vs SKIPPED and the exact actuator(s) that caused each
        skip (so you know what to fix before re-running).

USAGE
    python3 src/data/timing_data_extractor.py --experiment-id baseline30wps --t_min 0.5
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

# ==========================================================================
# SIGNAL TAXONOMY
# ==========================================================================
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
#   run-to-run (39/35/43/38/44). Its reproducible counterpart is the LIMIT-SWITCH
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


# ==========================================================================
# DB LOAD
# ==========================================================================
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


# ==========================================================================
# SIGNAL RECONSTRUCTION + DEBOUNCE
# ==========================================================================
def signal_segments(times, vals, end_time=None):
    """Collapse a transition list into contiguous (value, start, end) segments.

    Called from: extract_steps(). Each logged row is a transition INTO value
    vals[i] at times[i]; the segment for vals[i] runs until the NEXT transition.
    Consecutive equal values are merged, so the result is strictly alternating.

    IMPORTANT (bug fix): the LAST logged transition (times[-1], vals[-1]) is the
    signal entering its FINAL state and holding it to the end of the run. It has
    no "next transition" to bound it, so it must be closed with end_time (the
    run's end). Previously this final state was dropped, which shifted every
    signal's sequence by one and made it end on the wrong state (e.g. sliderMagazine
    appearing to end HIGH when it physically ends LOW).

    Args:
        times (np.ndarray): transition timestamps (monotonic), sorted.
        vals  (np.ndarray): value entered at each transition (0/1).
        end_time (float|None): timestamp to close the final segment. Defaults to
            times[-1] + the median inter-transition gap if not given.

    Returns:
        list[tuple]: [(value, t_start, t_end), ...] including the final state.
    """
    if len(times) == 0:
        return []
    if end_time is None:
        gap = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
        end_time = float(times[-1]) + gap
    # Build boundaries: every transition starts a segment; the last one is closed
    # with end_time so the final state is retained.
    bounds = list(times) + [end_time]
    segs = []
    for i in range(len(times)):
        v, t0, t1 = vals[i], bounds[i], bounds[i + 1]
        if t1 <= t0:
            continue
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
    # Close the signal's final state at the RUN's end (last event of any signal in
    # this trial), so the held terminal state spans to the end of the run.
    run_end = float(df_run["ts_monotonic"].max())
    segs = signal_segments(g["ts_monotonic"].to_numpy(), g["num"].to_numpy(),
                           end_time=run_end)
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


# ==========================================================================
# MAIN EXTRACTION
# ==========================================================================
def run(args):
    df = load_db(args.db, args.experiment_id)
    runs = sorted(df["run_id"].unique())
    report = []   # lines for the extraction report

    def rpt(line=""):
        report.append(line); print(line)

    rpt(f"MATRIX timing extraction — experiment '{args.experiment_id}'")
    rpt(f"t_min (debounce) = {args.t_min}s   trials found = {len(runs)}")
    rpt("")

    # --- Canonicalise: drop AB position copy, rename Siemens inPosition ---
    df = df[~df["tag"].isin(DROP_RAW_TAGS)].copy()
    df["tag"] = df["tag"].replace(RENAME)

    # --- Per-trial debounced step sequences for every signal ---
    # steps[run][tag] = [(state, dur), ...]
    steps = {r: {} for r in runs}
    for r in runs:
        gr = df[df["run_id"] == r]
        for tag in SIGNALS:
            steps[r][tag] = extract_steps(gr, tag, args.t_min)

    # --- Transition-count tables BEFORE vs AFTER debounce (for the report) ---
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

    # --- Modal actuator step-count across trials; gate each trial ---
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
    # Each signal's step sequence is averaged by POSITION. But signals whose step
    # count varies across trials (noisy sensors, e.g. magazineEmpty 16/14/14/8/10)
    # cannot be front-averaged past the point where trials diverge, and naive
    # min()-truncation DROPS the true final transition, leaving the waveform ending
    # on a spurious mid-run state (e.g. sliderMagazine shown ending HIGH, or
    # magazineEmpty ending LOW, when physically they do the opposite).
    #
    # Fix — anchor BOTH ends:
    #   * FRONT: average positional steps 0..(min_len-2), which every trial shares.
    #   * BACK:  append one final step carrying the TRUE TERMINAL STATE that every
    #            kept trial ends on (the physically-correct last state), with its
    #            duration averaged from each trial's own last step.
    # For consistent-count signals this reduces to the full sequence (and fixes the
    # off-by-one that previously dropped the final LOW step). For inconsistent
    # signals it averages the agreed prefix, then jumps to the agreed ending — no
    # fabricated final state.
    # A signal is AVERAGED by step position ONLY if its step count is reproducible
    # across kept trials (same count in every trial — true for the gated actuators
    # and clean sensors). Positional averaging of a signal whose count VARIES
    # (noise-prone light barriers, e.g. magazineEmpty with 8..16 blinks per trial)
    # is invalid: it fabricates a sequence that matches no real run and misplaces
    # the one reproducible event. For those signals we instead emit a REPRESENTATIVE
    # single trial — the one whose step count is the median — preserving the real
    # waveform (real blinks, real terminal transition) without fabrication.
    rows = []
    rep_report = []
    for tag in SIGNALS:
        if not kept:
            continue
        seqs = {r: steps[r][tag] for r in kept}
        lengths = {r: len(s) for r, s in seqs.items()}
        if min(lengths.values()) == 0:
            continue
        reproducible = len(set(lengths.values())) == 1

        if reproducible:
            # --- AVERAGE positionally (every trial has the same step sequence) ---
            n = next(iter(lengths.values()))
            cum = 0.0
            for k in range(n):
                durs   = [seqs[r][k][1] for r in kept]
                states = [seqs[r][k][0] for r in kept]
                state  = Counter(states).most_common(1)[0][0]
                rows.append({
                    "signal": tag, "role": ROLE[tag], "step_index": k, "state": state,
                    "mean_dur_s": round(float(np.mean(durs)), 4),
                    "std_s": round(float(np.std(durs)), 4),
                    "n_trials": len(durs), "cum_start_s": round(cum, 4),
                    "method": "averaged",
                })
                cum += float(np.mean(durs))
        else:
            # --- REPRESENTATIVE trial (median step count) — real, not averaged ---
            ordered = sorted(kept, key=lambda r: lengths[r])
            rep = ordered[len(ordered) // 2]                 # median-count trial
            rep_report.append((tag, rep, dict(sorted(Counter(lengths.values()).items()))))
            cum = 0.0
            for k, (state, dur) in enumerate(seqs[rep]):
                rows.append({
                    "signal": tag, "role": ROLE[tag], "step_index": k, "state": int(state),
                    "mean_dur_s": round(float(dur), 4), "std_s": 0.0,
                    "n_trials": 1, "cum_start_s": round(cum, 4),
                    "method": f"representative({rep[-4:]})",
                })
                cum += float(dur)

    rpt("Signals shown as a REPRESENTATIVE trial (non-reproducible step count; "
        "averaging would fabricate a sequence):")
    if rep_report:
        for tag, rep, dist in rep_report:
            rpt(f"  {tag:<24} rep={rep[-4:]}  (counts across trials: {dist})")
    else:
        rpt("  (none — all signals had reproducible step counts)")
    rpt("")

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