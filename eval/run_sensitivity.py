"""
Part 1 - Power-parameter sensitivity on the frozen simulator (tag sim-frozen).

Grid: alpha in {1.0, 1.25, 1.5, 2.0} x P_idle/P_max in {0.3, 0.5, 0.7}.

Overrides WITHOUT editing frozen code:
  - power parameters enter through get_default_nodes(scale, idle_power_fraction,
    alpha) passed to AblationStudy(nodes=...) - the simulator reads p_idle,
    p_max and alpha from the node dicts;
  - component switches are config_name + forecast-stream selection at
    _simulate_configuration call time.

Datasets:
  - synthetic diurnal, seeds {42, 101, 202} (frozen generator; production
    artifacts; frozen stream construction: conformal tau=0.90 on the first
    1440 target minutes, test = rest, warm start 60 min excluded inside the sim);
  - the 68-core real Azure Functions 2019 set (streams from
    eval/run_real_trace.prepare_streams: 60/15/25 split, static conformal tau=0.90).

Configs per cell: cluster_autoscaler (util 0.70), full_aegis_conformal (tau 0.9;
this is also the placement-ON arm), forecast_plus_power_no_placement fed the SAME
conformal stream (placement-OFF arm; both arms power-down), oracle.

Printed per grid cell (mean over traces of each dataset):
  - Aegis - CA energy
  - placement ON - OFF energy
  - sign-flip list vs the default cell (alpha=1.5, ratio=0.5)

Usage: python eval/run_sensitivity.py
"""

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from datasets.workload_patterns import generate_pattern_trace  # noqa: E402
from ml.evaluation.ablation import AblationStudy, get_default_nodes  # noqa: E402
from ml.features.feature_engineering import build_features  # noqa: E402
from ml.inference.predict import AegisPredictor  # noqa: E402
from eval.run_real_trace import prepare_streams, git_state  # noqa: E402

ALPHAS = [1.0, 1.25, 1.5, 2.0]
IDLE_FRACS = [0.3, 0.5, 0.7]
SEEDS = [42, 101, 202]
TAU = 0.90
HORIZON = 10
DEFAULT_CELL = (1.5, 0.5)
OUTPUT_JSON = "eval/sensitivity_results.json"


def sign(x: float) -> str:
    return "+" if x > 0 else ("-" if x < 0 else "0")


def synthetic_streams(trace: pd.DataFrame) -> dict:
    """Frozen stream construction for synthetic traces (mirrors run_comparison):
    predict with production artifacts, conformal tau on the first 1440 targets,
    test = targets from 1440 on. Power parameters do not affect the stream."""
    df = trace.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values(by="timestamp", inplace=True)
    feat = build_features(df)
    ti = df.set_index("timestamp")
    tgt = feat.index + pd.Timedelta(minutes=HORIZON)
    tgt = tgt[tgt.isin(ti.index)]
    y_all = ti.loc[tgt, "cpu_usage"].values
    mem_all = ti.loc[tgt, "memory_usage"].values
    fx = feat.loc[tgt]

    pred = AegisPredictor(model_dir="ml/models/artifacts")
    pred.load_models()
    p10 = pred.models[HORIZON][0.1].predict(fx[pred.feature_lists[HORIZON][0.1]])
    p50 = np.maximum(pred.models[HORIZON][0.5].predict(fx[pred.feature_lists[HORIZON][0.5]]), 0.0)
    p90 = pred.models[HORIZON][0.9].predict(fx[pred.feature_lists[HORIZON][0.9]])
    p10, p90 = np.minimum(p10, p50), np.maximum(p90, p50)

    n_total = len(y_all)
    n_cal = min(1440, n_total // 2) if n_total > 1440 else 0
    level = min(1.0, np.ceil((n_cal + 1) * TAU) / n_cal)
    q90 = float(np.quantile(y_all[:n_cal] - p90[:n_cal], level))
    p90_conf = np.maximum(p90 + q90, p50)

    return {"y_test": y_all[n_cal:], "mem_test": mem_all[n_cal:], "p90_stream": p90_conf[n_cal:]}


def build_traces():
    """traces[dataset] = list of stream dicts."""
    traces = {"synthetic_diurnal": [], "real_68core": []}
    for seed in SEEDS:
        trace = generate_pattern_trace(f"sens-{seed}", pattern="diurnal", duration_days=5, seed=seed)
        traces["synthetic_diurnal"].append({"name": f"seed-{seed}", **synthetic_streams(trace)})
    for path in sorted(glob.glob("datasets/real_*.parquet")):
        s = prepare_streams(path)
        traces["real_68core"].append({
            "name": s["app"], "y_test": s["_arrays"]["y_test"], "mem_test": s["_arrays"]["mem_test"],
            "p90_stream": s["_arrays"]["p90_static_test"],
        })
    return traces


def simulate_cell(study: AblationStudy, streams: list) -> dict:
    """Mean energy per config over the dataset's traces for one grid cell."""
    energies = {"cluster_autoscaler": [], "full_aegis_conformal": [],
                "forecast_plus_power_no_placement": [], "oracle": []}
    shortfalls = {k: [] for k in energies}
    for tr in streams:
        for cfg in energies:
            res = study._simulate_configuration(
                actual_demands=tr["y_test"], actual_mems=tr["mem_test"],
                p90_forecasts=tr["p90_stream"], config_name=cfg,
                hpa_target_util=0.70, forecast_horizon_minutes=HORIZON,
            )
            energies[cfg].append(res["energy_kwh"])
            shortfalls[cfg].append(res["capacity_shortfall_minutes"])
    return {"energy_mean": {k: float(np.mean(v)) for k, v in energies.items()},
            "energy_per_trace": energies,
            "shortfall_mean": {k: float(np.mean(v)) for k, v in shortfalls.items()},
            "shortfall_per_trace": shortfalls}


def main():
    print("=" * 112)
    print("  POWER-PARAMETER SENSITIVITY on the frozen simulator")
    print(f"  grid: alpha {ALPHAS} x P_idle/P_max {IDLE_FRACS} | seeds {SEEDS} (synthetic diurnal) + 5 real apps (68-core set)")
    print("  configs: CA (util 0.70) | full_aegis_conformal tau 0.9 = placement ON | "
          "forecast_plus_power_no_placement + same conformal stream = placement OFF | oracle")
    print("  overrides: get_default_nodes(idle_power_fraction, alpha) -> AblationStudy(nodes=...); "
          "no frozen file touched")
    print("=" * 112)

    traces = build_traces()
    grid = {}
    for alpha in ALPHAS:
        for frac in IDLE_FRACS:
            study = AblationStudy(
                nodes=get_default_nodes("large", idle_power_fraction=frac, alpha=alpha),
                min_active_nodes=2, wake_up_latency_steps=3,
            )
            cell = {}
            for ds, streams in traces.items():
                cell[ds] = simulate_cell(study, streams)
                cell[ds]["aegis_minus_ca"] = round(
                    cell[ds]["energy_mean"]["full_aegis_conformal"] - cell[ds]["energy_mean"]["cluster_autoscaler"], 3)
                cell[ds]["placement_on_minus_off"] = round(
                    cell[ds]["energy_mean"]["full_aegis_conformal"] - cell[ds]["energy_mean"]["forecast_plus_power_no_placement"], 3)
            grid[f"alpha={alpha}_ratio={frac}"] = cell
            print(f"  cell alpha={alpha:<4} ratio={frac:<4}: "
                  f"synthetic dE(aegis-CA)={cell['synthetic_diurnal']['aegis_minus_ca']:>+8.2f}  "
                  f"dE(place on-off)={cell['synthetic_diurnal']['placement_on_minus_off']:>+8.2f}  | "
                  f"real dE(aegis-CA)={cell['real_68core']['aegis_minus_ca']:>+8.2f}  "
                  f"dE(place on-off)={cell['real_68core']['placement_on_minus_off']:>+8.2f}")

    # --- printable grids with signs ---
    flips = []
    for ds in ("synthetic_diurnal", "real_68core"):
        for metric, label in (("aegis_minus_ca", "Aegis - CA energy"),
                              ("placement_on_minus_off", "Placement ON - OFF energy")):
            print(f"\n  GRID [{ds}] {label} (kWh, mean over traces; sign in brackets)")
            axis_hdr = "alpha \\ ratio"
            print(f"  {axis_hdr:<14} | " + " | ".join(f"{f:>10}" for f in IDLE_FRACS) + "   (value [sign])")
            print("  " + "-" * 80)
            default_sign = sign(grid[f"alpha={DEFAULT_CELL[0]}_ratio={DEFAULT_CELL[1]}"][ds][metric])
            for alpha in ALPHAS:
                row = []
                for frac in IDLE_FRACS:
                    v = grid[f"alpha={alpha}_ratio={frac}"][ds][metric]
                    s = sign(v)
                    mark = " *" if (s != default_sign) else ""
                    row.append(f"{v:>9.2f}{mark}")
                    if s != default_sign:
                        flips.append({"dataset": ds, "metric": label, "alpha": alpha,
                                      "idle_ratio": frac, "value": v,
                                      "default_cell_sign": default_sign})
                print(f"  alpha={alpha:<6} | " + " | ".join(f"{r:>10}" for r in row) +
                      f"   (default sign: {default_sign})")

    print("\n  SIGN FLIPS vs default cell (alpha=1.5, ratio=0.5):")
    if not flips:
        print("    none - the sign is stable across the whole grid on both datasets")
    for f in flips:
        print(f"    {f['dataset']:<18} {f['metric']:<28} alpha={f['alpha']:<5} ratio={f['idle_ratio']:<5} "
              f"value={f['value']:+.2f} (default sign {f['default_cell_sign']})")

    payload = {
        "grid": grid,
        "sign_flips": flips,
        "grid_axes": {"alpha": ALPHAS, "idle_ratio": IDLE_FRACS, "default_cell": list(DEFAULT_CELL)},
        "datasets": {"synthetic_diurnal_seeds": SEEDS,
                     "real_68core_apps": [t["name"] for t in traces["real_68core"]]},
        "protocol": {
            "configs": {"cluster_autoscaler": "util 0.70",
                        "full_aegis_conformal": "tau 0.9, placement ON (also the placement-ON arm)",
                        "forecast_plus_power_no_placement": "placement OFF, fed the SAME static conformal stream",
                        "oracle": "defaults"},
            "power_override": "get_default_nodes(idle_power_fraction=frac, alpha=alpha) -> AblationStudy(nodes=...)",
            "synthetic_streams": "production artifacts; conformal tau=0.90 on first 1440 target minutes; "
                                 "test = targets from 1440 on; warm start 60 min excluded inside the simulator",
            "real_streams": "eval/run_real_trace.prepare_streams (60/15/25 split, static conformal tau=0.90)",
        },
    }
    study_ref = AblationStudy()
    payload["simulator_config_hash"] = study_ref.compute_config_hash(payload["grid_axes"])
    payload["git"] = git_state()
    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  wrote {OUTPUT_JSON} (git: {payload['git']['commit'][:8]}, tag: {payload['git']['tag_at_head']}, "
          f"config hash: {payload['simulator_config_hash'][:16]}...)")


if __name__ == "__main__":
    main()
