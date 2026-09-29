"""
Item-1 diagnostic for app 8e5d601c74a3 (full_aegis_conformal run, static conformal stream).

Prints replica target and active nodes at 20 evenly spaced test minutes plus
min/max/std of the p90 stream the controller sees, and explains the event count.

NOTE: run before changing the loader eligibility filter - 8e5d601c74a3 (peak
74.0 cores) is only present in the peak<=80-core app set.
"""

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath("."))

from eval.run_real_trace import prepare_streams, simulate_config, SEEDS  # noqa: E402
from ml.evaluation.ablation import AblationStudy  # noqa: E402

TARGET_APP = "8e5d601c74a3"
OUT_JSON = "eval/diag_item1_8e5d601c74a3.json"


def main():
    path = os.path.join("datasets", f"real_{TARGET_APP}.parquet")
    if not os.path.exists(path):
        sys.exit(f"{path} not found (app excluded by the current eligibility filter?)")

    streams = prepare_streams(path)
    study = AblationStudy(model_dir="ml/models/artifacts_real", min_active_nodes=2, wake_up_latency_steps=3)
    out = simulate_config(study, streams, "full_aegis_conformal",
                          streams["_arrays"]["p90_static_test"], return_series=True)

    series = out["series"]
    reps = np.array(series["replicas"])
    nodes = np.array(series["active_nodes"])
    p90 = np.asarray(streams["_arrays"]["p90_static_test"], dtype=float)

    n = len(reps)
    idx20 = np.linspace(0, n - 1, 20).astype(int)
    print("=" * 88)
    print(f"  APP {TARGET_APP} - full_aegis_conformal on the test window (static conformal p90)")
    print(f"  test window: {streams['split_boundaries']['test_minutes']}, warm start 60 min excluded -> "
          f"{n} scored minutes; demand mean {streams['test_demand_cores']['mean']} / max {streams['test_demand_cores']['max']} cores")
    print(f"  p90 stream (conformal, as consumed by the controller): min {p90.min():.3f} | max {p90.max():.3f} | "
          f"std {p90.std():.3f} cores")
    print("=" * 88)
    print(f"  {'test minute':>11} | {'demand cores':>12} | {'replica target':>14} | {'active nodes':>12}")
    print("  " + "-" * 62)
    rows = []
    for i in idx20:
        minute = int(series["minute"][i])
        rows.append({"test_minute": minute, "demand_cores": series["actual_demand"][i],
                     "replica_target": int(series["replicas"][i]), "active_nodes": int(series["active_nodes"][i])})
        print(f"  {minute:>11} | {series['actual_demand'][i]:>12.2f} | {int(series['replicas'][i]):>14} | "
              f"{int(series['active_nodes'][i]):>12}")

    print(f"\n  scaling action events: {out['scaling_actions']['raw'][0]} | replica delta: {out['scaling_churn']['raw'][0]} "
          f"| energy: {out['energy_kwh']['raw'][0]} kWh | shortfall: {out['capacity_shortfall_minutes']['raw'][0]} min")
    print("  Why only 7 events: the p90 stream is a smooth LightGBM curve plus one constant conformal "
          "offset, so its day-level ramps cross the 10% dead zone only at the sustained night/day "
          "transitions, and the 5-step downscale window plus the HPA rate limit absorb every small wiggle "
          "in between.")

    payload = {
        "app": TARGET_APP,
        "p90_stream": {"min": round(float(p90.min()), 4), "max": round(float(p90.max()), 4),
                       "std": round(float(p90.std()), 4)},
        "sample_points": rows,
        "metrics": {"action_events": out["scaling_actions"]["raw"][0],
                    "replica_delta": out["scaling_churn"]["raw"][0],
                    "energy_kwh": out["energy_kwh"]["raw"][0],
                    "shortfall_min": out["capacity_shortfall_minutes"]["raw"][0]},
        "seeds": SEEDS,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
