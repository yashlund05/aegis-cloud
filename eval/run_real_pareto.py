"""
Matched-headroom Pareto + seasonal-naive baseline + coverage audit on the
68-core real-trace set (Azure Functions 2019 apps selected by
datasets/load_real_trace.py with peak <= 68 cores).

Frozen simulator is called (AblationStudy._simulate_configuration), never modified.

Arms, per app:
  - aegis conformal tau in {0.5, 0.7, 0.9, 0.99} at target util 0.70. tau sets the
    level of the static conformal p90 offset (quantile of calibration residuals
    y - p90 at min(1, ceil((m+1)*tau)/m)); the p10 offset keeps the frozen fixed
    0.90 level, mirroring run_comparison.
  - cluster_autoscaler at target utilization in {90, 80, 70, 60, 50}%.
  - oracle at defaults.
  - seasonal-naive: point forecast = demand 1440 min earlier, with the SAME
    conformal path as full_aegis_conformal (static offsets from calibration
    residuals at level 0.90 applied to a constant point-quantile stream),
    simulated as the full_aegis_conformal config. No training involved.

Matched shortfall: for each CA arm, aegis energy is linearly interpolated along
the aegis (shortfall, energy) curve at the CA arm's shortfall; the difference is
marked EXTRAPOLATED when the CA shortfall lies outside the aegis curve's range
(np.interp clamps at the endpoints).

Coverage definition (printed verbatim in the output): two-sided interval coverage
on the TEST window, mean( y >= p10 AND y <= p90 ), bounds inclusive.

Usage: python eval/run_real_pareto.py
"""

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath("."))

from eval.run_real_trace import (  # noqa: E402
    prepare_streams, simulate_config, git_state, HORIZON, TAU,
)
from ml.evaluation.ablation import AblationStudy  # noqa: E402

AEGIS_TAUS = [0.5, 0.7, 0.9, 0.99]
CA_UTILS = [0.9, 0.8, 0.7, 0.6, 0.5]
NAIVE_LAG = 1440
OUTPUT_JSON = "eval/real_pareto_results.json"

COVERAGE_DEFINITION = (
    "Coverage = fraction of TEST-window minutes where the actual demand y(t) lies "
    "inside the two-sided prediction interval [p10(t), p90(t)], bounds inclusive: "
    "mean( y >= p10 AND y <= p90 ). Quantiles: p10 and p90 are the LightGBM q10/q90 "
    "streams (raw), or their conformal-adjusted versions. The conformal p90 offset "
    "is the tau-quantile of one-sided upper calibration residuals y - p90 "
    "(level tau = 0.90 unless swept); the p10 offset is the 0.90-quantile of "
    "one-sided lower residuals p10 - y (fixed level 0.90 in the frozen code, "
    "independent of tau). Rolling = same intervals with the frozen horizon-delayed "
    "rolling window (W=1440, ends at t-H). Naive = same conformal path applied to "
    "the seasonal-naive point forecast (demand 1440 min earlier)."
)


def confal_level(m: int, tau: float) -> float:
    return min(1.0, np.ceil((m + 1) * tau) / m)


def main():
    paths = sorted(glob.glob("datasets/real_*.parquet"))
    if not paths:
        sys.exit("No datasets/real_*.parquet found - run datasets/load_real_trace.py first.")

    print("=" * 112)
    print("  MATCHED-HEADROOM PARETO + SEASONAL-NAIVE BASELINE on the 68-core real-trace set")
    print(f"  aegis tau {AEGIS_TAUS} (util 0.70) | CA util {CA_UTILS} | oracle | seasonal-naive (lag {NAIVE_LAG})")
    print("=" * 112)

    results = {"apps": {}, "coverage_definition": COVERAGE_DEFINITION}
    for path in paths:
        streams = prepare_streams(path)
        app = streams["app"]
        a = streams["_arrays"]
        y_all, cpu_all = a["y_all"], a["cpu_all"]
        calib_mask, test_mask = a["calib_mask"], a["test_mask"]
        p10_raw, p50_raw, p90_raw = a["p10_raw_full"], a["p50_raw_full"], a["p90_raw_full"]
        target_pos = a["target_pos_abs"]
        m = int(calib_mask.sum())
        level90 = confal_level(m, 0.90)

        study = AblationStudy(model_dir="ml/models/artifacts_real", min_active_nodes=2, wake_up_latency_steps=3)
        y_test = a["y_test"]
        mem_test = a["mem_test"]

        def run(cfg, p90_stream, util=0.70):
            res = study._simulate_configuration(
                actual_demands=y_test, actual_mems=mem_test, p90_forecasts=p90_stream,
                config_name=cfg, hpa_target_util=util, forecast_horizon_minutes=HORIZON,
            )
            return {"energy_kwh": res["energy_kwh"],
                    "capacity_shortfall_minutes": res["capacity_shortfall_minutes"],
                    "scaling_actions": res["scaling_actions"],
                    "scaling_churn": res["scaling_churn"]}

        # --- aegis tau sweep ---
        aegis_arms = {}
        r90 = y_all[calib_mask] - p90_raw[calib_mask]
        r10 = p10_raw[calib_mask] - y_all[calib_mask]
        for tau in AEGIS_TAUS:
            q90 = float(np.quantile(r90, confal_level(m, tau)))
            q10 = float(np.quantile(r10, level90))
            p90_conf = np.maximum(p90_raw + q90, p50_raw)
            p10_conf = np.minimum(p10_raw - q10, p50_raw)
            arm = run("full_aegis_conformal", p90_conf[test_mask])
            arm["q_hat_90"] = round(q90, 4)
            cov = float(np.mean((y_all[test_mask] >= p10_conf[test_mask]) & (y_all[test_mask] <= p90_conf[test_mask])))
            arm["coverage"] = round(cov, 4)
            aegis_arms[tau] = arm

        # --- CA util sweep + oracle ---
        ca_arms = {}
        for util in CA_UTILS:
            ca_arms[util] = run("cluster_autoscaler", a["p90_static_test"], util=util)
        oracle_arm = run("oracle", a["p90_static_test"])

        # --- seasonal-naive with the same conformal path ---
        lag_pos = target_pos - NAIVE_LAG
        valid_naive = lag_pos >= 0
        naive_point_full = np.full(len(y_all), np.nan)
        naive_point_full[valid_naive] = cpu_all[lag_pos[valid_naive]]
        r90n = y_all[calib_mask & valid_naive] - naive_point_full[calib_mask & valid_naive]
        r10n = naive_point_full[calib_mask & valid_naive] - y_all[calib_mask & valid_naive]
        q90n = float(np.quantile(r90n, level90))
        q10n = float(np.quantile(r10n, level90))
        naive_p90_conf = np.maximum(naive_point_full + q90n, naive_point_full)
        naive_p10_conf = np.minimum(naive_point_full - q10n, naive_point_full)
        naive_arm = run("full_aegis_conformal", naive_p90_conf[test_mask])
        naive_cov = float(np.mean(
            (y_all[test_mask & valid_naive] >= naive_p10_conf[test_mask & valid_naive]) &
            (y_all[test_mask & valid_naive] <= naive_p90_conf[test_mask & valid_naive])))

        # --- matched shortfall: interpolate aegis energy at each CA arm's shortfall ---
        # Reduce the aegis (shortfall, energy) sweep to its Pareto frontier first:
        # at equal shortfall keep the cheapest arm, and drop dominated points
        # (higher shortfall at no less energy). Without this, np.interp over
        # duplicate zero-shortfall points would pick the tau=0.99 energy and
        # overstate aegis cost at matched shortfall.
        frontier = []
        for s, e in sorted((aegis_arms[t]["capacity_shortfall_minutes"], aegis_arms[t]["energy_kwh"])
                           for t in AEGIS_TAUS):
            if frontier and s == frontier[-1][0]:
                frontier[-1] = (s, min(frontier[-1][1], e))
            elif frontier and e >= frontier[-1][1]:
                continue  # dominated: higher shortfall, no cheaper
            else:
                frontier.append((s, e))
        ae_s = np.array([p[0] for p in frontier], float)
        ae_e = np.array([p[1] for p in frontier], float)
        matched = []
        for util in CA_UTILS:
            s_ca = ca_arms[util]["capacity_shortfall_minutes"]
            e_ca = ca_arms[util]["energy_kwh"]
            e_ae = float(np.interp(s_ca, ae_s, ae_e))
            extrapolated = bool(s_ca < ae_s.min() or s_ca > ae_s.max())
            matched.append({"ca_util": util, "ca_shortfall": s_ca, "ca_energy": e_ca,
                            "aegis_energy_interp": round(e_ae, 3),
                            "delta_aegis_minus_ca": round(e_ae - e_ca, 3),
                            "extrapolated": extrapolated})

        # --- per-app printout ---
        print(f"\n  === {app} (test demand mean {streams['test_demand_cores']['mean']} / "
              f"max {streams['test_demand_cores']['max']} cores) ===")
        print(f"  {'arm':<26} | {'energy kWh':>10} | {'shortfall min':>13} | {'events':>7}")
        print("  " + "-" * 70)
        for tau in AEGIS_TAUS:
            arm = aegis_arms[tau]
            print(f"  aegis tau={tau:<5.2f}          | {arm['energy_kwh']:>10.2f} | {arm['capacity_shortfall_minutes']:>13.1f} | "
                  f"{arm['scaling_actions']:>7.0f}")
        for util in CA_UTILS:
            arm = ca_arms[util]
            print(f"  CA util={int(util*100):<3d}%          | {arm['energy_kwh']:>10.2f} | {arm['capacity_shortfall_minutes']:>13.1f} | "
                  f"{arm['scaling_actions']:>7.0f}")
        print(f"  {'oracle':<26} | {oracle_arm['energy_kwh']:>10.2f} | {oracle_arm['capacity_shortfall_minutes']:>13.1f} | "
              f"{oracle_arm['scaling_actions']:>7.0f}")
        print(f"  {'seasonal-naive conf':<26} | {naive_arm['energy_kwh']:>10.2f} | {naive_arm['capacity_shortfall_minutes']:>13.1f} | "
              f"{naive_arm['scaling_actions']:>7.0f}")

        print(f"\n  matched shortfall (aegis energy interpolated at each CA arm's shortfall):")
        print(f"  {'CA util':>7} | {'CA shortfall':>12} | {'CA energy':>10} | {'aegis E interp':>14} | {'delta':>8} | flag")
        print("  " + "-" * 78)
        for row in matched:
            flag = "EXTRAPOLATED" if row["extrapolated"] else "interpolated"
            print(f"  {int(row['ca_util']*100):>3d}%   | {row['ca_shortfall']:>12.1f} | {row['ca_energy']:>10.2f} | "
                  f"{row['aegis_energy_interp']:>14.2f} | {row['delta_aegis_minus_ca']:>+8.2f} | {flag}")

        results["apps"][app] = {
            "aegis_tau": {str(t): aegis_arms[t] for t in AEGIS_TAUS},
            "ca_util": {str(u): ca_arms[u] for u in CA_UTILS},
            "oracle": oracle_arm,
            "seasonal_naive_conformal": {**naive_arm, "coverage": round(naive_cov, 4)},
            "matched_shortfall": matched,
            "aegis_frontier": [[float(s), float(e)] for s, e in frontier],
        }

    # --- tau=0.9 headline comparison incl. naive (from the per-app records) ---
    print("\n  TAU=0.9 COMPARISON (static conformal): energy kWh | shortfall min | action events")
    print(f"  {'workload':<14} | {'CA':>20} | {'aegis conf':>20} | {'seasonal-naive conf':>22} | {'oracle':>20}")
    print("  " + "-" * 110)
    for app, r in results["apps"].items():
        ca, ae = r["ca_util"]["0.7"], r["aegis_tau"]["0.9"]
        nv, orc = r["seasonal_naive_conformal"], r["oracle"]
        def cell(x):
            return f"{x['energy_kwh']:>7.2f}/{x['capacity_shortfall_minutes']:>5.1f}/{x['scaling_actions']:>5.0f}"
        print(f"  {app:<14} | {cell(ca):>20} | {cell(ae):>20} | {cell(nv):>22} | {cell(orc):>20}")

    # --- coverage audit ---
    print("\n  COVERAGE DEFINITION (exact):")
    print("  " + COVERAGE_DEFINITION)
    print(f"\n  Per-app coverage at tau=0.90 (two-sided, test window; raw = uncalibrated model quantiles):")
    print(f"  {'workload':<14} | {'raw':>7} | {'static':>7} | {'rolling':>7} | {'naive':>7}")
    print("  " + "-" * 54)
    for path in paths:
        streams = prepare_streams(path)
        app, fm = streams["app"], streams["forecast_metrics"]
        naive_cov = results["apps"][app]["seasonal_naive_conformal"]["coverage"]
        print(f"  {app:<14} | {fm['raw_p10_p90_coverage_test']:>7.4f} | {fm['static_conformal_coverage_test']:>7.4f} | "
              f"{fm['rolling_conformal_coverage_test']:>7.4f} | {naive_cov:>7.4f}")

    results["trace"] = "Azure Functions 2019, 68-core eligibility set (see eval/real_trace_results.json)"
    results["arms"] = {"aegis_taus": AEGIS_TAUS, "ca_utils": CA_UTILS, "naive_lag_minutes": NAIVE_LAG}
    results["git"] = git_state()
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  wrote {OUTPUT_JSON} (git: {results['git']['commit'][:8]}, tag_at_head: {results['git']['tag_at_head']})")


if __name__ == "__main__":
    main()
