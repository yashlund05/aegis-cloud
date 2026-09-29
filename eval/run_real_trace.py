"""
Real-trace evaluation on the frozen simulator (tag sim-frozen).

Uses ONLY the Azure Functions 2019 workload parquets produced by
datasets/load_real_trace.py (real measured data; see that file for the
cores conversion and selection rule). No synthetic data.

Protocol (fixed):
  - Per workload chronological split: first 60% train, next 15% conformal
    calibration, last 25% test (on 20160 one-minute rows: 12096 / 3024 / 5040).
  - LightGBM q10/q50/q90 trained on TRAIN targets only, horizon 10 min,
    saved to ml/models/artifacts_real (production artifacts untouched).
  - Two conformal variants on the TEST window:
      * static: single offset from CALIBRATION residuals (tau=0.90)
      * rolling: the frozen rolling_conformal_adjustment - window W=1440,
        residuals horizon-delayed (window ends at t-H), so only outcomes
        observable at decision time are used.
  - Frozen simulator configs stock_hpa, cluster_autoscaler,
    full_aegis_conformal, oracle replay the TEST window via
    AblationStudy._simulate_configuration (called, not modified).
  - Seeds 42/101/202: the frozen simulator is deterministic given a fixed
    trace, so the three runs are identical by construction (std = 0).
  - Uncertainty: because seeds carry no information, paired Aegis-vs-CA
    differences get a day-BLOCK BOOTSTRAP (95% percentile CI) pooled across
    apps: the test window yields 3 full-day blocks per app (each replayed
    independently, 60-min warm start excluded per block; the trailing
    half-day is dropped), blocks resampled with replacement, B=10000.

Usage: python eval/run_real_trace.py
"""

import glob
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, os.path.abspath("."))

from ml.evaluation.ablation import AblationStudy, rolling_conformal_adjustment  # noqa: E402
from ml.features.feature_engineering import build_features  # noqa: E402
from ml.training.train_lightgbm import train_quantile_model  # noqa: E402
from ml.evaluation.evaluate import pinball_loss  # noqa: E402

HORIZON = 10
SPLIT = (0.60, 0.15, 0.25)  # train / calibration / test
SEEDS = [42, 101, 202]
CONFIGS = ["stock_hpa", "cluster_autoscaler", "full_aegis_conformal", "oracle"]
ARTIFACTS_DIR = "ml/models/artifacts_real"
OUTPUT_JSON = "eval/real_trace_results.json"
TAU = 0.90
ROLLING_WINDOW = 1440
BOOTSTRAP_B = 10000
BOOTSTRAP_SEED = 12345
BLOCK_MINUTES = 1440  # one day per block


def wmape(y, yhat):
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return float(np.sum(np.abs(y - yhat)) / np.sum(np.abs(y)))


def git_state():
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout
        dirty = sorted({ln[3:].strip() for ln in status.splitlines() if ln.strip()})
        tag = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True, timeout=10).stdout.strip()
        return {"commit": commit, "tag_at_head": tag, "dirty_files": dirty}
    except Exception:
        return {"commit": "unknown", "tag_at_head": "unknown", "dirty_files": []}


def train_and_save(X_t, y_t, X_v, y_v, quantile):
    wrapper = train_quantile_model(X_t, y_t, X_v, y_v, quantile=quantile)
    name = f"aegis_h{HORIZON}m_q{int(quantile * 100)}"
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    path = os.path.join(ARTIFACTS_DIR, f"{name}.txt" if wrapper.backend == "lightgbm" else f"{name}.joblib")
    wrapper.save(path)
    diff = y_v.values - wrapper.predict(X_v)
    meta = {
        "model_name": name,
        "horizon_minutes": HORIZON,
        "quantile": quantile,
        "backend": wrapper.backend,
        "features": list(wrapper.feature_names),
        "model_path": path,
        "metrics": {
            "wmape": round(float(np.sum(np.abs(diff)) / max(np.sum(np.abs(y_v.values)), 1e-9)), 4),
            "pinball_loss": round(float(np.mean(np.maximum(quantile * diff, (quantile - 1) * diff))), 4),
        },
        "status": "active",
        "trained_on": "Azure Functions 2019 real-trace TRAIN segment only (see eval/real_trace_results.json)",
    }
    with open(os.path.join(ARTIFACTS_DIR, f"{name}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return wrapper


def prepare_streams(path: str) -> dict:
    """Split, train on TRAIN only, predict, build static + rolling conformal streams."""
    app = os.path.basename(path).replace("real_", "").replace(".parquet", "")
    df = pd.read_parquet(path)
    n = len(df)
    train_end = int(n * SPLIT[0])
    calib_end = int(n * (SPLIT[0] + SPLIT[1]))

    feat = build_features(df)  # trailing windows only -> causal
    start_pos = n - len(feat)  # leading minutes dropped by feature warmup
    feat_pos_abs = np.arange(start_pos, n)
    target_pos_abs = feat_pos_abs + HORIZON
    valid = target_pos_abs < n  # last HORIZON rows have no in-trace target
    feat_pos_abs, target_pos_abs = feat_pos_abs[valid], target_pos_abs[valid]
    y_all = df["cpu_usage"].to_numpy()[target_pos_abs]

    train_mask = target_pos_abs < train_end
    calib_mask = (target_pos_abs >= train_end) & (target_pos_abs < calib_end)
    test_mask = target_pos_abs >= calib_end

    feat_df = feat.reset_index(drop=True)
    feature_cols = [c for c in feat_df.columns
                    if c not in ("cpu_usage", "timestamp", "workload_id", "status")
                    and pd.api.types.is_numeric_dtype(feat_df[c])]
    X_all = feat_df[feature_cols][valid]

    X_tr, y_tr = X_all[train_mask], y_all[train_mask]
    cut = int(len(X_tr) * 0.8)  # chronological inner validation for early stopping
    wrappers = {}
    for q in (0.1, 0.5, 0.9):
        wrappers[q] = train_and_save(X_tr.iloc[:cut], pd.Series(y_tr[:cut]),
                                     X_tr.iloc[cut:], pd.Series(y_tr[cut:]), q)

    p10_raw = wrappers[0.1].predict(X_all)
    p50_raw = np.maximum(wrappers[0.5].predict(X_all), 0.0)
    p90_raw = wrappers[0.9].predict(X_all)
    p10_raw = np.minimum(p10_raw, p50_raw)
    p90_raw = np.maximum(p90_raw, p50_raw)

    # static conformal: one offset from CALIBRATION residuals
    r90 = y_all[calib_mask] - p90_raw[calib_mask]
    r10 = p10_raw[calib_mask] - y_all[calib_mask]
    m = int(calib_mask.sum())
    level = min(1.0, np.ceil((m + 1) * TAU) / m)
    q_hat_90 = float(np.quantile(r90, level))
    q_hat_10 = float(np.quantile(r10, level))
    p90_static = np.maximum(p90_raw + q_hat_90, p50_raw)
    p10_static = np.minimum(p10_raw - q_hat_10, p50_raw)

    # rolling conformal (frozen code): window W=1440 ending at t-H
    test_start_arr = int(np.argmax(test_mask))  # first array index of the test window
    p90_roll_full, p10_roll_full = rolling_conformal_adjustment(
        full_y=y_all, full_p90=p90_raw, full_p10=p10_raw,
        n_cal=test_start_arr, horizon_minutes=HORIZON,
        window_steps=ROLLING_WINDOW, quantile_tau=TAU,
    )
    p90_rolling = p90_roll_full
    p10_rolling = p10_roll_full

    y_test = y_all[test_mask]
    mem_test = df["memory_usage"].to_numpy()[target_pos_abs[test_mask]]
    test_slice = np.flatnonzero(test_mask)

    raw_cov = float(np.mean((y_all[test_mask] >= p10_raw[test_mask]) & (y_all[test_mask] <= p90_raw[test_mask])))
    static_cov = float(np.mean((y_test >= p10_static[test_slice]) & (y_test <= p90_static[test_slice])))
    roll_cov = float(np.mean((y_test >= p10_rolling) & (y_test <= p90_rolling)))

    return {
        "app": app,
        "file": path,
        "n_minutes": int(n),
        "split_boundaries": {
            "train_minutes": [0, train_end],
            "calibration_minutes": [train_end, calib_end],
            "test_minutes": [calib_end, n],
            "train_end_timestamp": str(df["timestamp"].iloc[train_end - 1]),
            "calibration_start_timestamp": str(df["timestamp"].iloc[train_end]),
            "calibration_end_timestamp": str(df["timestamp"].iloc[calib_end - 1]),
            "test_start_timestamp": str(df["timestamp"].iloc[calib_end]),
        },
        "test_demand_cores": {"mean": round(float(y_test.mean()), 3), "max": round(float(y_test.max()), 3)},
        "forecast_metrics": {
            "wmape_p50": round(wmape(y_test, p50_raw[test_mask]) * 100.0, 2),
            "mae_cores": round(float(mean_absolute_error(y_test, p50_raw[test_mask])), 4),
            "pinball_p10": round(float(pinball_loss(y_test, p10_raw[test_mask], 0.1)), 4),
            "pinball_p50": round(float(pinball_loss(y_test, p50_raw[test_mask], 0.5)), 4),
            "pinball_p90": round(float(pinball_loss(y_test, p90_raw[test_mask], 0.9)), 4),
            "raw_p10_p90_coverage_test": round(raw_cov, 4),
            "static_conformal_coverage_test": round(static_cov, 4),
            "rolling_conformal_coverage_test": round(roll_cov, 4),
            "q_hat_90_static": round(q_hat_90, 4),
            "q_hat_10_static": round(q_hat_10, 4),
        },
        "_arrays": {
            "y_test": y_test, "mem_test": mem_test,
            "p90_static_test": p90_static[test_slice],
            "p90_rolling_test": p90_rolling,
            # raw streams and masks for downstream studies (Pareto tau sweep,
            # seasonal-naive baseline): kept out of the JSON dump
            "p10_raw_full": p10_raw, "p50_raw_full": p50_raw, "p90_raw_full": p90_raw,
            "y_all": y_all,
            "calib_mask": calib_mask, "test_mask": test_mask,
            "target_pos_abs": target_pos_abs, "cpu_all": df["cpu_usage"].to_numpy(),
        },
    }


def simulate_config(study: AblationStudy, streams: dict, cfg: str, p90_stream: np.ndarray,
                    return_series: bool = False) -> dict:
    runs = {"energy_kwh": [], "capacity_shortfall_minutes": [],
            "scaling_actions": [], "scaling_churn": []}
    series = None
    for seed in SEEDS:
        res = study._simulate_configuration(
            actual_demands=streams["_arrays"]["y_test"],
            actual_mems=streams["_arrays"]["mem_test"],
            p90_forecasts=p90_stream,
            config_name=cfg,
            forecast_horizon_minutes=HORIZON,
            return_series=return_series,
        )
        for k in runs:
            runs[k].append(res[k])
        series = res.get("series")
    out = {k: {"mean": round(float(np.mean(v)), 3), "std": round(float(np.std(v)), 3), "raw": v}
           for k, v in runs.items()}
    if return_series:
        out["series"] = series
    return out


def day_block_metrics(study: AblationStudy, streams: dict, cfg: str, p90_stream: np.ndarray) -> list:
    """Replay each full test-day block independently (fresh state, warm start
    excluded per block by the frozen code); returns per-block metrics."""
    y = streams["_arrays"]["y_test"]
    mem = streams["_arrays"]["mem_test"]
    blocks = []
    for b_start in range(0, len(y) - BLOCK_MINUTES + 1, BLOCK_MINUTES):
        b_end = b_start + BLOCK_MINUTES
        res = study._simulate_configuration(
            actual_demands=y[b_start:b_end],
            actual_mems=mem[b_start:b_end],
            p90_forecasts=p90_stream[b_start:b_end],
            config_name=cfg,
            forecast_horizon_minutes=HORIZON,
        )
        blocks.append({"energy_kwh": res["energy_kwh"],
                       "capacity_shortfall_minutes": res["capacity_shortfall_minutes"]})
    return blocks


def block_bootstrap_paired(blocks_by_app: dict, n_boot: int = BOOTSTRAP_B, seed: int = BOOTSTRAP_SEED) -> dict:
    """Pooled day-block bootstrap for the paired Aegis - CA difference.
    blocks_by_app: {app: {"aegis": [3 blocks], "ca": [3 blocks]}}; the 15 pooled
    (app, day) blocks are resampled with replacement; statistic = mean paired
    difference over the resampled blocks; CI = 2.5/97.5 percentiles."""
    rng = np.random.default_rng(seed)
    diffs_e, diffs_s = [], []
    for app, blk in blocks_by_app.items():
        for ba, bc in zip(blk["aegis"], blk["ca"]):
            diffs_e.append(ba["energy_kwh"] - bc["energy_kwh"])
            diffs_s.append(ba["capacity_shortfall_minutes"] - bc["capacity_shortfall_minutes"])
    diffs_e, diffs_s = np.array(diffs_e), np.array(diffs_s)
    n = len(diffs_e)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_e = diffs_e[idx].mean(axis=1)
    boot_s = diffs_s[idx].mean(axis=1)
    return {
        "n_blocks": int(n),
        "blocks_per_app": int(n // len(blocks_by_app)),
        "n_bootstrap": n_boot,
        "rng_seed": seed,
        "energy_diff_kwh": {"mean": round(float(diffs_e.mean()), 3),
                            "ci95_low": round(float(np.percentile(boot_e, 2.5)), 3),
                            "ci95_high": round(float(np.percentile(boot_e, 97.5)), 3)},
        "shortfall_diff_min": {"mean": round(float(diffs_s.mean()), 3),
                               "ci95_low": round(float(np.percentile(boot_s, 2.5)), 3),
                               "ci95_high": round(float(np.percentile(boot_s, 97.5)), 3)},
        "per_app_block_diffs": {app: {"energy": [round(ba["energy_kwh"] - bc["energy_kwh"], 3)
                                                  for ba, bc in zip(blk["aegis"], blk["ca"])],
                                      "shortfall": [round(ba["capacity_shortfall_minutes"] - bc["capacity_shortfall_minutes"], 1)
                                                    for ba, bc in zip(blk["aegis"], blk["ca"])]}
                                for app, blk in blocks_by_app.items()},
    }


def main():
    paths = sorted(glob.glob("datasets/real_*.parquet"))
    if not paths:
        sys.exit("No datasets/real_*.parquet found - run datasets/load_real_trace.py first.")
    print("=" * 112)
    print("  REAL-TRACE EVALUATION: Azure Functions 2019 on the frozen simulator")
    print(f"  Workloads: {[os.path.basename(p) for p in paths]}")
    print(f"  Split 60/15/25 per workload; models trained on TRAIN only -> {ARTIFACTS_DIR}")
    print(f"  Conformal tau={TAU}: static (calibration offset) AND rolling (W={ROLLING_WINDOW}, horizon-delayed)")
    print(f"  Uncertainty: day-block bootstrap (B={BOOTSTRAP_B}), pooled across apps, for paired Aegis-CA diffs")
    print("=" * 112)

    results = {"workloads": {}}
    blocks_by_app = {}
    for path in paths:
        streams = prepare_streams(path)
        app = streams["app"]
        study = AblationStudy(model_dir=ARTIFACTS_DIR, min_active_nodes=2, wake_up_latency_steps=3)

        fm = streams["forecast_metrics"]
        print(f"\n  === {app} (test window {streams['split_boundaries']['test_minutes'][0]}..{streams['split_boundaries']['test_minutes'][1]}, "
              f"demand mean {streams['test_demand_cores']['mean']} / max {streams['test_demand_cores']['max']} cores) ===")
        print(f"  forecast on TEST: WMAPE {fm['wmape_p50']}% | pinball(p10,p50,p90) "
              f"{fm['pinball_p10']},{fm['pinball_p50']},{fm['pinball_p90']}")
        print(f"  p10-p90 coverage on TEST: raw {fm['raw_p10_p90_coverage_test']:.4f} | "
              f"static conformal {fm['static_conformal_coverage_test']:.4f} | "
              f"rolling conformal {fm['rolling_conformal_coverage_test']:.4f}")

        configs_out = {}
        for cfg in CONFIGS:
            configs_out[cfg] = simulate_config(study, streams, cfg, streams["_arrays"]["p90_static_test"])
        # full_aegis_conformal under the rolling stream
        configs_out["full_aegis_conformal_rolling"] = simulate_config(
            study, streams, "full_aegis_conformal", streams["_arrays"]["p90_rolling_test"])

        blocks_by_app[app] = {
            "aegis": day_block_metrics(study, streams, "full_aegis_conformal", streams["_arrays"]["p90_static_test"]),
            "ca": day_block_metrics(study, streams, "cluster_autoscaler", streams["_arrays"]["p90_static_test"]),
        }

        results["workloads"][app] = {k: v for k, v in streams.items() if k != "_arrays"}
        results["workloads"][app]["configs"] = configs_out
        del streams["_arrays"]

    print("\n  CONFORMAL COVERAGE ON TEST (per app, 4 decimals): static offset vs rolling (W=1440, horizon-delayed)")
    print(f"  {'workload':<14} | {'raw':>7} | {'static':>7} | {'rolling':>7}")
    print("  " + "-" * 46)
    for app, out in results["workloads"].items():
        fm = out["forecast_metrics"]
        print(f"  {app:<14} | {fm['raw_p10_p90_coverage_test']:>7.4f} | {fm['static_conformal_coverage_test']:>7.4f} | "
              f"{fm['rolling_conformal_coverage_test']:>7.4f}")

    print("\n  SIMULATION ON TEST WINDOW (static conformal stream; mean over seeds 42,101,202 - "
          "deterministic, std = 0 by construction)")
    hdr = (f"  {'workload':<14} | {'config':<30} | {'energy kWh':<12} | {'shortfall min':<14} | "
           f"{'action events':<14} | {'replica delta':<13}")
    print(hdr)
    print("  " + "-" * 108)
    for app, out in results["workloads"].items():
        for cfg in CONFIGS + ["full_aegis_conformal_rolling"]:
            c = out["configs"][cfg]
            print(f"  {app:<14} | {cfg:<30} | {c['energy_kwh']['mean']:>7.2f}    | "
                  f"{c['capacity_shortfall_minutes']['mean']:>7.1f}    | "
                  f"{c['scaling_actions']['mean']:>7.1f}    | {c['scaling_churn']['mean']:>7.1f}")

    boot = block_bootstrap_paired(blocks_by_app)
    print("\n  PAIRED DIFFERENCE, full_aegis_conformal - cluster_autoscaler (static stream), pooled day-block bootstrap")
    print(f"  blocks: {boot['n_blocks']} (3 full test days x {len(blocks_by_app)} apps; trailing half-day dropped; "
          f"each block replayed independently with 60-min warm start excluded)")
    d = boot["energy_diff_kwh"]
    print(f"  energy   (kWh): {d['mean']:+.2f}  95% block-bootstrap CI [{d['ci95_low']:+.2f}, {d['ci95_high']:+.2f}]")
    s = boot["shortfall_diff_min"]
    print(f"  shortfall (min): {s['mean']:+.2f}  95% block-bootstrap CI [{s['ci95_low']:+.2f}, {s['ci95_high']:+.2f}]")

    results["trace"] = {
        "name": "Azure Functions 2019 (AzurePublicDataset, 'Serverless in the Wild' USENIX ATC 2020)",
        "source_url": "https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/"
                      "azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz",
        "raw_files": "datasets/raw/azurefunctions2019/ (invocations + durations d01-d14, app memory d01-d12)",
        "demand_conversion": "cores(t) = sum_f invocations(f,t) * exec_time_ms(f,day)/1000/60; "
                             "1 vCPU per concurrent execution is the only normalization; "
                             "invocation counts and durations are measured trace values",
        "selection_rule": "apps with <5% missing minutes and peak <= cluster capacity, top-5 by mean load "
                          "(see datasets/load_real_trace.py for the binding threshold)",
        "loader": "datasets/load_real_trace.py",
    }
    results["protocol"] = {
        "split_fractions": SPLIT,
        "horizon_minutes": HORIZON,
        "seeds": SEEDS,
        "configs": CONFIGS,
        "models_dir": ARTIFACTS_DIR,
        "conformal": {"static": f"single offset from calibration residuals, tau={TAU}",
                      "rolling": f"frozen rolling_conformal_adjustment, W={ROLLING_WINDOW}, residuals end at t-H"},
        "determinism_note": "the frozen simulator has no stochasticity given a fixed trace; the three seeds "
                            "produce identical runs (std = 0) and are reported for provenance",
        "bootstrap": {"blocks": "3 full test days per app (trailing half-day dropped), each replayed independently",
                      "B": BOOTSTRAP_B, "rng_seed": BOOTSTRAP_SEED, "statistic": "mean paired difference over pooled blocks"},
    }
    results["git"] = git_state()
    results["bootstrap_paired_aegis_vs_ca"] = boot
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  wrote {OUTPUT_JSON} (git: {results['git']['commit'][:8]}, tag_at_head: {results['git']['tag_at_head']})")


if __name__ == "__main__":
    main()
