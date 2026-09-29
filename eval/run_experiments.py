"""
Multi-seed ablation experiment runner for Aegis (Phase 9 & Research Paper Evaluation).
Executes across 7 configurations over N seeds, regenerating the workload trace per seed.
Reports mean, std, and 95% confidence intervals for:
- Cluster energy (kWh)
- Capacity shortfall minutes
- Scaling actions
- Forecaster metrics (WMAPE, pinball loss, empirical p10-p90 coverage)
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
from ml.evaluation.ablation import AblationStudy


def compute_ci95(data: list) -> tuple:
    """
    Computes (mean, std, ci95_half_width) for a sample list.
    """
    arr = np.array(data, dtype=float)
    n = len(arr)
    mean = float(np.mean(arr))
    if n <= 1:
        return mean, 0.0, 0.0
    std = float(np.std(arr, ddof=1))
    sem = std / np.sqrt(n)
    # Student's t distribution with n-1 degrees of freedom
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    ci95 = float(t_crit * sem)
    return round(mean, 2), round(std, 2), round(ci95, 2)


def run_multi_seed_experiments(
    seeds: list,
    duration_days: int = 2,
    output_dir: str = "eval",
    horizon: int = 10,
):
    print("=" * 80)
    print("      AEGIS RIGOROUS ABLATION EXPERIMENTS (RESEARCH PAPER BENCHMARK)")
    print(f"      Seeds: {seeds} | Duration per seed: {duration_days} days | Horizon: {horizon} min")
    print("=" * 80)

    study = AblationStudy()

    # Data collection dictionaries
    configs_list = [
        "stock_hpa",
        "reactive_hpa_plus_consolidation",
        "forecast_only",
        "forecast_placement",
        "forecast_plus_power_no_placement",
        "full_aegis",
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
    }

    raw_seed_runs = []

    for seed_idx, seed in enumerate(seeds):
        print(f"\n[Seed {seed_idx + 1}/{len(seeds)} (seed={seed})] Generating independent workload trace...")
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

        run_result = study.run_comparison(
            trace_data=trace,
            output_dir=output_dir,
            forecast_horizon_minutes=horizon,
        )
        raw_seed_runs.append({"seed": seed, "run_result": run_result})

        # Forecaster metrics
        fm = run_result["forecaster_metrics"]
        for k in forecast_records:
            forecast_records[k].append(fm[k])

        # Config metrics
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
        mean, std, ci95 = compute_ci95(vals)
        aggregated_forecaster[f_name] = {
            "mean": mean,
            "std": std,
            "ci95": ci95,
            "raw": vals,
        }

    # Print Formatted Results
    print("\n" + "=" * 92)
    print("                          FORECASTING QUALITY BENCHMARK (WALK-FORWARD)")
    print("=" * 92)
    print(f"  WMAPE (p50)                  : {aggregated_forecaster['wmape_p50']['mean']}% +/- {aggregated_forecaster['wmape_p50']['ci95']}%")
    print(f"  Pinball Loss (q=0.10)        : {aggregated_forecaster['pinball_loss_p10']['mean']} +/- {aggregated_forecaster['pinball_loss_p10']['ci95']}")
    print(f"  Pinball Loss (q=0.50)        : {aggregated_forecaster['pinball_loss_p50']['mean']} +/- {aggregated_forecaster['pinball_loss_p50']['ci95']}")
    print(f"  Pinball Loss (q=0.90)        : {aggregated_forecaster['pinball_loss_p90']['mean']} +/- {aggregated_forecaster['pinball_loss_p90']['ci95']}")
    print(f"  Interval Coverage (p10-p90)  : {aggregated_forecaster['interval_coverage_p10_p90_pct']['mean']}% +/- {aggregated_forecaster['interval_coverage_p10_p90_pct']['ci95']}%")

    print("\n" + "=" * 92)
    print("                   ABLATION STUDY SUMMARY (MEAN +/- 95% CONFIDENCE INTERVAL)")
    print("=" * 92)
    print(f"{'Configuration':<34} | {'Energy (kWh)':<16} | {'Shortfall (min)':<18} | {'Actions':<14}")
    print("-" * 92)
    for cfg in configs_list:
        e = summary_stats[cfg]["energy_kwh"]
        s = summary_stats[cfg]["capacity_shortfall_minutes"]
        a = summary_stats[cfg]["scaling_actions"]
        e_str = f"{e['mean']:.2f} +/- {e['ci95']:.2f}"
        s_str = f"{s['mean']:.1f} +/- {s['ci95']:.1f}"
        a_str = f"{a['mean']:.1f} +/- {a['ci95']:.1f}"
        print(f"{cfg:<34} | {e_str:<16} | {s_str:<18} | {a_str:<14}")
    print("=" * 92)

    # Save to eval/ablation_results.json
    final_output = {
        "timestamp": datetime.utcnow().isoformat(),
        "seeds": seeds,
        "duration_days": duration_days,
        "forecast_horizon_minutes": horizon,
        "forecaster_metrics": aggregated_forecaster,
        "configurations": summary_stats,
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
    parser.add_argument("--days", type=int, default=2, help="Trace length in days (default: 2)")
    parser.add_argument("--horizon", type=int, default=10, help="Forecast horizon in minutes (default: 10)")
    parser.add_argument("--output", type=str, default="eval", help="Output directory for results")
    args = parser.parse_args()

    if args.seed is not None:
        seed_list = [args.seed]
    else:
        seed_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    run_multi_seed_experiments(
        seeds=seed_list,
        duration_days=args.days,
        output_dir=args.output,
        horizon=args.horizon,
    )


if __name__ == "__main__":
    main()
