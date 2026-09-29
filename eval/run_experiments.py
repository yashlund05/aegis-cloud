"""
Multi-seed ablation experiment runner for Aegis (Phase 9 & Research Paper Evaluation).
Executes across configurations over N seeds, regenerating the workload trace per seed.
Reports mean, std, and t-distribution 95% confidence intervals for:
- Cluster energy (kWh)
- Capacity shortfall minutes
- Scaling actions
- Forecaster metrics (WMAPE, pinball loss with 4 decimals, empirical p10-p90 coverage, and calibration rates)
- Paired differences (full_aegis vs reactive_hpa_plus_consolidation)
"""

import os
import sys
import json
import argparse
from datetime import datetime
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.abspath("."))

from datasets.generate_sample_traces import generate_workload_trace
from ml.evaluation.ablation import AblationStudy, get_default_nodes


def compute_ci95(data: list) -> tuple:
    """
    Computes (mean, std, ci95_half_width) for a sample list using Student's t-distribution.
    """
    arr = np.array(data, dtype=float)
    n = len(arr)
    mean = float(np.mean(arr))
    if n <= 1:
        return mean, 0.0, 0.0
    std = float(np.std(arr, ddof=1))
    sem = std / np.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    ci95 = float(t_crit * sem)
    return round(mean, 2), round(std, 2), round(ci95, 2)


def compute_paired_diff(a_vals: list, b_vals: list) -> tuple:
    """
    Computes paired difference statistics (A - B) across seeds with t-distribution 95% CI.
    """
    diffs = np.array(a_vals, dtype=float) - np.array(b_vals, dtype=float)
    n = len(diffs)
    mean = float(np.mean(diffs))
    if n <= 1:
        return mean, 0.0, 0.0
    std = float(np.std(diffs, ddof=1))
    sem = std / np.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    ci95 = float(t_crit * sem)
    return round(mean, 2), round(std, 2), round(ci95, 2)


def run_multi_seed_experiments(
    seeds: list,
    duration_days: int = 4,
    output_dir: str = "eval",
    horizon: int = 10,
    topology: str = "large",
    scale_workload: float = 15.0,
):
    nodes = get_default_nodes(topology)
    total_cpu = sum(n["cpu_capacity"] for n in nodes)

    print("=" * 96)
    print(f"      AEGIS RIGOROUS ABLATION EXPERIMENTS ({topology.upper()} TOPOLOGY: {len(nodes)} NODES, {total_cpu:.1f} CORES)")
    print(f"      Seeds: {seeds} | Duration per seed: {duration_days} days | Workload Scale: {scale_workload}x | Horizon: {horizon} min")
    print("=" * 96)

    study = AblationStudy(nodes=nodes, min_active_nodes=2)

    configs_list = [
        "stock_hpa",
        "reactive_hpa_plus_consolidation",
        "forecast_only",
        "forecast_placement",
        "forecast_plus_power_no_placement",
        "full_aegis",
        "full_aegis_conformal",
        "oracle",
    ]

    metric_records = {
        cfg: {
            "energy_kwh": [],
            "capacity_shortfall_minutes": [],
            "scaling_actions": [],
            "scaling_churn": [],
            "mean_allocated_replicas": [],
            "mean_active_nodes": [],
        }
        for cfg in configs_list
    }

    forecast_records = {
        "wmape_p50": [],
        "pinball_loss_p10": [],
        "pinball_loss_p50": [],
        "pinball_loss_p90": [],
        "interval_coverage_p10_p90_pct": [],
        "calibration_fraction_below_p10": [],
        "calibration_fraction_below_p50": [],
        "calibration_fraction_below_p90_uncalibrated": [],
        "calibration_fraction_below_p90_conformal": [],
    }

    raw_seed_runs = []

    for seed_idx, seed in enumerate(seeds):
        print(f"\n[Seed {seed_idx + 1}/{len(seeds)} (seed={seed})] Generating independent workload trace ({duration_days} days)...")
        trace = generate_workload_trace(
            workload_id="prod-service",
            start_time=pd.Timestamp("2026-01-01"),
            duration_days=duration_days,
            freq="1min",
            base_cpu=0.45,
            base_mem=0.50,
            spike_probability=0.03,
            seed=seed,
        )

        # First 1440 steps (day 1) used for split-conformal calibration, subsequent days for test
        run_result = study.run_comparison(
            trace_data=trace,
            output_dir=output_dir,
            forecast_horizon_minutes=horizon,
            calibration_window_steps=1440,
            scale_workload=scale_workload,
        )
        raw_seed_runs.append({"seed": seed, "run_result": run_result})

        fm = run_result["forecaster_metrics"]
        for k in forecast_records:
            forecast_records[k].append(fm[k])

        cfgs = run_result["configurations"]
        for cfg in configs_list:
            res = cfgs[cfg]
            metric_records[cfg]["energy_kwh"].append(res["energy_kwh"])
            metric_records[cfg]["capacity_shortfall_minutes"].append(res["capacity_shortfall_minutes"])
            metric_records[cfg]["scaling_actions"].append(res["scaling_actions"])
            metric_records[cfg]["scaling_churn"].append(res["scaling_churn"])
            metric_records[cfg]["mean_allocated_replicas"].append(res["mean_allocated_replicas"])
            metric_records[cfg]["mean_active_nodes"].append(res["mean_active_nodes"])

    # Aggregate Statistics
    summary_stats = {}
    for cfg in configs_list:
        summary_stats[cfg] = {}
        for m_name, vals in metric_records[cfg].items():
            mean, std, ci95 = compute_ci95(vals)
            summary_stats[cfg][m_name] = {
                "mean": mean,
                "std": std,
                "ci95": ci95,
                "raw": vals,
            }

    aggregated_forecaster = {}
    for f_name, vals in forecast_records.items():
        arr = np.array(vals, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        t_crit = float(stats.t.ppf(0.975, df=len(arr) - 1)) if len(arr) > 1 else 0.0
        ci95 = float(t_crit * (std / np.sqrt(len(arr)))) if len(arr) > 1 else 0.0
        aggregated_forecaster[f_name] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "ci95": round(ci95, 4),
            "raw": vals,
        }

    # Print Formatted Results
    print("\n" + "=" * 96)
    print("                     FORECASTING & CONFORMAL CALIBRATION BENCHMARK")
    print("=" * 96)
    print(f"  WMAPE (p50)                              : {aggregated_forecaster['wmape_p50']['mean']:.2f}% +/- {aggregated_forecaster['wmape_p50']['ci95']:.2f}%")
    print(f"  Pinball Loss (q=0.10)                    : {aggregated_forecaster['pinball_loss_p10']['mean']:.4f} +/- {aggregated_forecaster['pinball_loss_p10']['ci95']:.4f}")
    print(f"  Pinball Loss (q=0.50)                    : {aggregated_forecaster['pinball_loss_p50']['mean']:.4f} +/- {aggregated_forecaster['pinball_loss_p50']['ci95']:.4f}")
    print(f"  Pinball Loss (q=0.90)                    : {aggregated_forecaster['pinball_loss_p90']['mean']:.4f} +/- {aggregated_forecaster['pinball_loss_p90']['ci95']:.4f}")
    print(f"  Fraction actuals < p10 (target 0.10)     : {aggregated_forecaster['calibration_fraction_below_p10']['mean']:.4f}")
    print(f"  Fraction actuals < p50 (target 0.50)     : {aggregated_forecaster['calibration_fraction_below_p50']['mean']:.4f}")
    print(f"  Fraction actuals < p90 (uncalibrated)    : {aggregated_forecaster['calibration_fraction_below_p90_uncalibrated']['mean']:.4f} (target 0.9000)")
    print(f"  Fraction actuals < p90 (conformal calib) : {aggregated_forecaster['calibration_fraction_below_p90_conformal']['mean']:.4f} (target 0.9000)")
    print(f"  Interval Coverage (p10-p90)              : {aggregated_forecaster['interval_coverage_p10_p90_pct']['mean']:.2f}% +/- {aggregated_forecaster['interval_coverage_p10_p90_pct']['ci95']:.2f}%")

    print("\n" + "=" * 96)
    print("           ABLATION STUDY SUMMARY (MEAN +/- t-DISTRIBUTION 95% CONFIDENCE INTERVAL)")
    print("=" * 96)
    print(f"{'Configuration':<34} | {'Energy (kWh)':<15} | {'Shortfall (min)':<18} | {'Actions':<14} | {'Active Nodes':<12}")
    print("-" * 96)
    for cfg in configs_list:
        e = summary_stats[cfg]["energy_kwh"]
        s = summary_stats[cfg]["capacity_shortfall_minutes"]
        a = summary_stats[cfg]["scaling_actions"]
        nd = summary_stats[cfg]["mean_active_nodes"]
        e_str = f"{e['mean']:.2f} +/- {e['ci95']:.2f}"
        s_str = f"{s['mean']:.1f} +/- {s['ci95']:.1f}"
        a_str = f"{a['mean']:.1f} +/- {a['ci95']:.1f}"
        nd_str = f"{nd['mean']:.1f} +/- {nd['ci95']:.1f}"
        print(f"{cfg:<34} | {e_str:<15} | {s_str:<18} | {a_str:<14} | {nd_str:<12}")
    print("=" * 96)

    # Paired Statistical Differences: full_aegis vs reactive_hpa_plus_consolidation
    e_diff_mean, e_diff_std, e_diff_ci = compute_paired_diff(
        metric_records["full_aegis"]["energy_kwh"],
        metric_records["reactive_hpa_plus_consolidation"]["energy_kwh"],
    )
    s_diff_mean, s_diff_std, s_diff_ci = compute_paired_diff(
        metric_records["full_aegis"]["capacity_shortfall_minutes"],
        metric_records["reactive_hpa_plus_consolidation"]["capacity_shortfall_minutes"],
    )
    a_diff_mean, a_diff_std, a_diff_ci = compute_paired_diff(
        metric_records["full_aegis"]["scaling_actions"],
        metric_records["reactive_hpa_plus_consolidation"]["scaling_actions"],
    )

    print("\n" + "=" * 96)
    print("   PAIRED DIFFERENCES: full_aegis MINUS reactive_hpa_plus_consolidation (per-seed delta)")
    print("=" * 96)
    print(f"  Delta Energy (kWh)       : {e_diff_mean:+.2f} +/- {e_diff_ci:.2f} kWh  (Negative = Aegis saves more energy)")
    print(f"  Delta Shortfall (minutes): {s_diff_mean:+.1f} +/- {s_diff_ci:.1f} min  (Negative = Aegis prevents shortfalls)")
    print(f"  Delta Scaling Actions    : {a_diff_mean:+.1f} +/- {a_diff_ci:.1f} act  (Negative = Aegis reduces churn)")
    print("=" * 96)

    # Save to eval/ablation_results.json
    final_output = {
        "timestamp": datetime.utcnow().isoformat(),
        "topology": topology,
        "node_count": len(nodes),
        "total_cpu_cores": total_cpu,
        "seeds": seeds,
        "duration_days": duration_days,
        "workload_scale": scale_workload,
        "forecast_horizon_minutes": horizon,
        "forecaster_metrics": aggregated_forecaster,
        "configurations": summary_stats,
        "paired_comparison_full_aegis_vs_reactive_consolidation": {
            "delta_energy_kwh": {"mean": e_diff_mean, "std": e_diff_std, "ci95": e_diff_ci},
            "delta_shortfall_minutes": {"mean": s_diff_mean, "std": s_diff_std, "ci95": s_diff_ci},
            "delta_scaling_actions": {"mean": a_diff_mean, "std": a_diff_std, "ci95": a_diff_ci},
        },
        "raw_runs": raw_seed_runs,
    }
    json_path = os.path.join(output_dir, "ablation_results.json")
    with open(json_path, "w") as f:
        json.dump(final_output, f, indent=2)
    print(f"\nFinal multi-seed benchmark artifacts saved to: {json_path}")
    return final_output


def main():
    parser = argparse.ArgumentParser(description="Aegis Multi-Seed Ablation Study Runner.")
    parser.add_argument("--seed", type=int, default=None, help="Single random seed to run (default: runs 5 seeds)")
    parser.add_argument("--seeds", type=str, default="42,101,202,303,404", help="Comma-separated seed list")
    parser.add_argument("--days", type=int, default=4, help="Trace length in days (default: 4, 1 calib + 3 test)")
    parser.add_argument("--horizon", type=int, default=10, help="Forecast horizon in minutes (default: 10)")
    parser.add_argument("--topology", type=str, default="large", choices=["small", "large"], help="Cluster topology: 'large' (20 nodes) or 'small' (4 nodes)")
    parser.add_argument("--scale", type=float, default=15.0, help="Workload scale factor (default: 15.0 for 20-node cluster)")
    parser.add_argument("--output", type=str, default="eval", help="Output directory for results")
    args = parser.parse_args()

    if args.seed is not None:
        seed_list = [args.seed]
    else:
        seed_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    # If small topology requested, default scale factor to 1.0
    scale = args.scale if args.topology == "large" else 1.0

    run_multi_seed_experiments(
        seeds=seed_list,
        duration_days=args.days,
        output_dir=args.output,
        horizon=args.horizon,
        topology=args.topology,
        scale_workload=scale,
    )


if __name__ == "__main__":
    main()
