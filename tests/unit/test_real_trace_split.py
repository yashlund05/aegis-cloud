"""
Split-integrity test for the real-trace protocol (eval/run_real_trace.py).

Fails if any TRAIN timestamp is later than the first CALIBRATION timestamp, or
if any CALIBRATION timestamp is later than the first TEST timestamp - i.e. the
chronological 60/15/25 split per workload must be strictly ordered and
non-overlapping. Skips if the real-trace parquets have not been produced yet.
"""

import glob
import json
import os

import pandas as pd
import pytest

SPLIT = (0.60, 0.15, 0.25)  # must match eval/run_real_trace.py


def _real_parquets():
    return sorted(glob.glob("datasets/real_*.parquet"))


def test_real_trace_split_boundaries_are_chronological():
    paths = _real_parquets()
    if not paths:
        pytest.skip(
            "real-trace parquets not present - run datasets/load_real_trace.py first"
        )

    assert len(paths) == 5, f"expected 5 selected workloads, found {len(paths)}"
    for path in paths:
        df = pd.read_parquet(path)
        n = len(df)
        ts = pd.to_datetime(df["timestamp"])
        assert ts.is_monotonic_increasing, f"{path}: timestamps not strictly increasing"

        train_end = int(n * SPLIT[0])
        calib_end = int(n * (SPLIT[0] + SPLIT[1]))

        last_train_ts = ts.iloc[train_end - 1]
        first_calib_ts = ts.iloc[train_end]
        last_calib_ts = ts.iloc[calib_end - 1]
        first_test_ts = ts.iloc[calib_end]

        # The core assertion: no train timestamp may be later than the first
        # calibration timestamp (and calibration must end before test begins).
        assert last_train_ts < first_calib_ts, (
            f"{path}: train segment overlaps calibration (last train {last_train_ts}, "
            f"first calib {first_calib_ts})"
        )
        assert last_calib_ts < first_test_ts, (
            f"{path}: calibration segment overlaps test (last calib {last_calib_ts}, "
            f"first test {first_test_ts})"
        )
        assert train_end == 12096 and calib_end == 15120 and n == 20160, (
            f"{path}: unexpected split sizes train={train_end}, calib={calib_end}, n={n}"
        )


def test_real_trace_results_json_matches_split():
    if not os.path.exists("eval/real_trace_results.json"):
        pytest.skip(
            "eval/real_trace_results.json not present - run eval/run_real_trace.py first"
        )
    with open("eval/real_trace_results.json") as f:
        results = json.load(f)

    assert results["git"]["tag_at_head"] in ("sim-frozen", "")
    for app, out in results["workloads"].items():
        b = out["split_boundaries"]
        assert b["train_minutes"][1] <= b["calibration_minutes"][0], (
            f"{app}: train/calib overlap in JSON"
        )
        assert b["calibration_minutes"][1] <= b["test_minutes"][0], (
            f"{app}: calib/test overlap in JSON"
        )
