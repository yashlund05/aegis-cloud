"""
Multi-seed, multi-pattern ablation experiment runner and sensitivity sweep for Aegis (Phase 9 & IEEE Paper Evaluation).

Executes across configurations over N seeds and 4 workload patterns:
- steady: Low variance, minimal diurnal swing
- diurnal: Strong daily day/night cycle
- bursty: Frequent Poisson-distributed short spikes
- flash_crowd: Sudden sustained multi-hour surge

Performs sensitivity sweeps over:
- Node wake-up latency: 1, 3, 5 minutes
- Idle power fraction: 30%, 50%, 70% of P_max
- Alpha (energy model exponent): 1.0, 1.5, 2.0
- Minimum active nodes (K_min): 1, 2, 3

Computes Student's t-distribution 95% confidence intervals and paired per-seed differences:
- full_aegis_conformal vs cluster_autoscaler
- full_aegis_conformal vs reactive_hpa_plus_consolidation
Reports whether 95% CIs exclude zero.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any, Tuple
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.abspath("."))

from datasets.workload_patterns import generate_pattern_trace
from ml.evaluation.ablation import AblationStudy, get_default_nodes


def compute_ci95(data: list) -> Tuple[float, float, float]:
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


def compute_paired_diff(a_vals: list, b_vals: list) -> Tuple[float, float, float, bool]:
    """
    Computes paired difference statistics (A - B) across seeds with t-distribution 95% CI.
    Returns: (mean, std, ci95, excludes_zero)
    """
    diffs = np.array(a_vals, dtype=float) - np.array(b_vals, dtype=float)
    n = len(diffs)
    mean = float(np.mean(diffs))
    if n <= 1:
        return mean, 0.0, 0.0, False
    std = float(np.std(diffs, ddof=1))
    sem = std / np.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    ci95 = float(t_crit * sem)
    excludes_zero = (mean - ci95 > 0) or (mean + ci95 < 0)
    return round(mean, 2), round(std, 2), round(ci95, 2), excludes_zero


def run_experiment_suite(
    patterns: List[str],
    seeds: List[int],
    duration_days: int = 5,
    horizon: int = 10,
    topology: str = "large",
    output_dir: str = "eval",
    wake_up_latency: int = 3,
    idle_power_frac: float = None,
    alpha: float = None,
    k_min: int = 2,
    study_label: str = "Primary Benchmark",
) -> Dict[str, Any]:
    nodes = get_default_nodes(scale=topology, idle_power_fraction=idle_power_frac, alpha=alpha)
    total_cpu = sum(n["cpu_capacity"] for n in nodes)

    configs_list = [
        "stock_hpa",
        "cluster_autoscaler",
        "reactive_hpa_plus_consolidation",
        "forecast_only",
        "forecast_placement",
        "forecast_plus_power_no_placement",
        "full_aegis",
        "full_aegis_conformal",
        "oracle",
    ]

    print("\n" + "=" * 105)
    print(f"  {study_label.upper()}: {topology.upper()} TOPOLOGY ({len(nodes)} NODES, {total_cpu:.1f} CORES)")
    print(f"  Patterns: {patterns} | Seeds: {seeds} | Duration: {duration_days}d | Horizon: {horizon}m")
    print(f"  Params: wake_up_latency={wake_up_latency}m, idle_power_frac={idle_power_frac}, alpha={alpha}, K_min={k_min}")
    print("=" * 105)

    study = AblationStudy(
        nodes=nodes,
        min_active_nodes=k_min,
        wake_up_latency_steps=wake_up_latency,
        cluster_autoscaler_scale_down_delay=10,
    )

    all_pattern_results = {}

    for pattern in patterns:
        print(f"\n>>> Running Pattern: {pattern.upper()} (across {len(seeds)} seeds)...")

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
            "interval_coverage_uncalibrated_pct": [],
            "interval_coverage_conformal_pct": [],
            "calibration_fraction_below_p10_uncalibrated": [],
            "calibration_fraction_below_p10_conformal": [],
            "calibration_fraction_below_p50": [],
            "calibration_fraction_below_p90_uncalibrated": [],
            "calibration_fraction_below_p90_conformal": [],
        }

        for seed in seeds:
            trace = generate_pattern_trace(
                workload_id=f"workload-{pattern}",
                pattern=pattern,
                duration_days=duration_days,
                seed=seed,
            )

            # Trace day 1 (0 to 1440 steps) strictly for split-conformal calibration; test on days 2 to 5
            res = study.run_comparison(
                trace_data=trace,
                output_dir=output_dir,
                forecast_horizon_minutes=horizon,
                calibration_window_steps=1440,
                scale_workload=1.0,
            )

            fm = res["forecaster_metrics"]
            for k in forecast_records:
                if k in fm:
                    forecast_records[k].append(fm[k])

            cfgs = res["configurations"]
            for cfg in configs_list:
                c_res = cfgs[cfg]
                for m_name in metric_records[cfg]:
                    metric_records[cfg][m_name].append(c_res[m_name])

        # Aggregate per-pattern stats
        pattern_summary = {}
        for cfg in configs_list:
            pattern_summary[cfg] = {}
            for m_name, vals in metric_records[cfg].items():
                mean, std, ci95 = compute_ci95(vals)
                pattern_summary[cfg][m_name] = {"mean": mean, "std": std, "ci95": ci95, "raw": vals}

        # Print table for this pattern
        print(f"\n--- Benchmark Summary for Pattern: {pattern.upper()} ---")
        print(f"{'Configuration':<34} | {'Energy (kWh)':<15} | {'Shortfall (min)':<18} | {'Actions':<14} | {'Active Nodes':<12}")
        print("-" * 105)
        for cfg in configs_list:
            e = pattern_summary[cfg]["energy_kwh"]
            s = pattern_summary[cfg]["capacity_shortfall_minutes"]
            a = pattern_summary[cfg]["scaling_actions"]
            nd = pattern_summary[cfg]["mean_active_nodes"]
            print(f"{cfg:<34} | {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} | {s['mean']:>6.1f} +/- {s['ci95']:<4.1f} | {a['mean']:>6.1f} +/- {a['ci95']:<4.1f} | {nd['mean']:>4.1f} +/- {nd['ci95']:<4.1f}")
        print("-" * 105)

        # Paired differences
        # 1. full_aegis_conformal vs cluster_autoscaler
        e_diff_ca_mean, _, e_diff_ca_ci, e_diff_ca_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["energy_kwh"],
            metric_records["cluster_autoscaler"]["energy_kwh"],
        )
        s_diff_ca_mean, _, s_diff_ca_ci, s_diff_ca_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["capacity_shortfall_minutes"],
            metric_records["cluster_autoscaler"]["capacity_shortfall_minutes"],
        )
        a_diff_ca_mean, _, a_diff_ca_ci, a_diff_ca_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["scaling_actions"],
            metric_records["cluster_autoscaler"]["scaling_actions"],
        )

        # 2. full_aegis_conformal vs reactive_hpa_plus_consolidation
        e_diff_rh_mean, _, e_diff_rh_ci, e_diff_rh_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["energy_kwh"],
            metric_records["reactive_hpa_plus_consolidation"]["energy_kwh"],
        )
        s_diff_rh_mean, _, s_diff_rh_ci, s_diff_rh_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["capacity_shortfall_minutes"],
            metric_records["reactive_hpa_plus_consolidation"]["capacity_shortfall_minutes"],
        )
        a_diff_rh_mean, _, a_diff_rh_ci, a_diff_rh_sig = compute_paired_diff(
            metric_records["full_aegis_conformal"]["scaling_actions"],
            metric_records["reactive_hpa_plus_consolidation"]["scaling_actions"],
        )

        print(f"Paired Deltas vs cluster_autoscaler (delta +/- 95% CI):")
        print(f"  Delta Energy   : {e_diff_ca_mean:+.2f} +/- {e_diff_ca_ci:.2f} kWh (Excludes zero: {e_diff_ca_sig})")
        print(f"  Delta Shortfall: {s_diff_ca_mean:+.1f} +/- {s_diff_ca_ci:.1f} min (Excludes zero: {s_diff_ca_sig})")
        print(f"  Delta Actions  : {a_diff_ca_mean:+.1f} +/- {a_diff_ca_ci:.1f} act (Excludes zero: {a_diff_ca_sig})")

        print(f"Paired Deltas vs reactive_hpa_plus_consolidation (delta +/- 95% CI):")
        print(f"  Delta Energy   : {e_diff_rh_mean:+.2f} +/- {e_diff_rh_ci:.2f} kWh (Excludes zero: {e_diff_rh_sig})")
        print(f"  Delta Shortfall: {s_diff_rh_mean:+.1f} +/- {s_diff_rh_ci:.1f} min (Excludes zero: {s_diff_rh_sig})")
        print(f"  Delta Actions  : {a_diff_rh_mean:+.1f} +/- {a_diff_rh_ci:.1f} act (Excludes zero: {a_diff_rh_sig})")

        all_pattern_results[pattern] = {
            "configurations": pattern_summary,
            "forecaster_metrics": {k: compute_ci95(v) for k, v in forecast_records.items()},
            "paired_vs_cluster_autoscaler": {
                "energy_kwh": {"diff": e_diff_ca_mean, "ci95": e_diff_ca_ci, "excludes_zero": e_diff_ca_sig},
                "shortfall_min": {"diff": s_diff_ca_mean, "ci95": s_diff_ca_ci, "excludes_zero": s_diff_ca_sig},
                "actions": {"diff": a_diff_ca_mean, "ci95": a_diff_ca_ci, "excludes_zero": a_diff_ca_sig},
            },
            "paired_vs_reactive_consolidation": {
                "energy_kwh": {"diff": e_diff_rh_mean, "ci95": e_diff_rh_ci, "excludes_zero": e_diff_rh_sig},
                "shortfall_min": {"diff": s_diff_rh_mean, "ci95": s_diff_rh_ci, "excludes_zero": s_diff_rh_sig},
                "actions": {"diff": a_diff_rh_mean, "ci95": a_diff_rh_ci, "excludes_zero": a_diff_rh_sig},
            },
        }

    return all_pattern_results


def run_sensitivity_sweeps(seeds: List[int], output_dir: str = "eval"):
    """
    Executes parameter sensitivity sweeps over:
    - Wake-up latency: 1, 3, 5 min
    - Idle power fraction: 0.30, 0.50, 0.70 of P_max
    - Alpha: 1.0, 1.5, 2.0
    - Minimum active nodes (K_min): 1, 2, 3
    """
    sweep_results = {}
    pattern = "diurnal"

    print("\n" + "=" * 105)
    print("                    STARTING PARAMETER SENSITIVITY SWEEPS (Pattern: DIURNAL)")
    print("=" * 105)

    # 1. Wake-up Latency Sweep
    print("\n>>> SENSITIVITY SWEEP 1: Node Wake-Up Latency (1m, 3m, 5m)")
    sweep_results["wake_up_latency"] = {}
    for lat in [1, 3, 5]:
        res = run_experiment_suite(
            patterns=[pattern],
            seeds=seeds,
            topology="large",
            wake_up_latency=lat,
            output_dir=output_dir,
            study_label=f"Wake-up Latency = {lat} min",
        )
        sweep_results["wake_up_latency"][f"{lat}m"] = res[pattern]

    # 2. Idle Power Fraction Sweep
    print("\n>>> SENSITIVITY SWEEP 2: Idle Power Fraction (30%, 50%, 70% of P_max)")
    sweep_results["idle_power_fraction"] = {}
    for frac in [0.30, 0.50, 0.70]:
        res = run_experiment_suite(
            patterns=[pattern],
            seeds=seeds,
            topology="large",
            idle_power_frac=frac,
            output_dir=output_dir,
            study_label=f"Idle Power Fraction = {int(frac*100)}%",
        )
        sweep_results["idle_power_fraction"][f"{int(frac*100)}%"] = res[pattern]

    # 3. Alpha (Energy Model Exponent) Sweep
    print("\n>>> SENSITIVITY SWEEP 3: Alpha Exponent (1.0, 1.5, 2.0)")
    sweep_results["alpha"] = {}
    for a in [1.0, 1.5, 2.0]:
        res = run_experiment_suite(
            patterns=[pattern],
            seeds=seeds,
            topology="large",
            alpha=a,
            output_dir=output_dir,
            study_label=f"Alpha = {a}",
        )
        sweep_results["alpha"][f"alpha_{a}"] = res[pattern]

    # 4. K_min (Minimum Active Nodes) Sweep
    print("\n>>> SENSITIVITY SWEEP 4: K_min Resilience Floor (1, 2, 3 nodes)")
    sweep_results["k_min"] = {}
    for k in [1, 2, 3]:
        res = run_experiment_suite(
            patterns=[pattern],
            seeds=seeds,
            topology="large",
            k_min=k,
            output_dir=output_dir,
            study_label=f"K_min = {k} nodes",
        )
        sweep_results["k_min"][f"k_{k}"] = res[pattern]

    sweep_path = os.path.join(output_dir, "sensitivity_sweep_results.json")
    with open(sweep_path, "w") as f:
        json.dump(sweep_results, f, indent=2)
    print(f"\nSensitivity sweep artifacts saved to: {sweep_path}")
    return sweep_results


def run_small_cluster_baseline(seeds: List[int], output_dir: str = "eval"):
    """
    Runs the 4-node cluster scenario to diagnose and demonstrate action count inversion
    and pinned K_min behavior.
    """
    print("\n" + "=" * 105)
    print("        SECONDARY BENCHMARK: SMALL CLUSTER BASELINE (4 NODES, 16 CORES)")
    print("=" * 105)
    return run_experiment_suite(
        patterns=["diurnal"],
        seeds=seeds,
        topology="small",
        k_min=2,
        output_dir=output_dir,
        study_label="Small Cluster Baseline (4 Nodes)",
    )


def main():
    parser = argparse.ArgumentParser(description="Aegis Multi-Pattern Ablation & Sensitivity Runner.")
    parser.add_argument("--seeds", type=str, default="42,101,202,303,404", help="Comma-separated seeds")
    parser.add_argument("--patterns", type=str, default="diurnal,steady,bursty,flash_crowd", help="Patterns")
    parser.add_argument("--days", type=int, default=5, help="Trace length in days (default: 5)")
    parser.add_argument("--horizon", type=int, default=10, help="Forecast horizon in minutes")
    parser.add_argument("--output", type=str, default="eval", help="Output directory")
    parser.add_argument("--sweep", action="store_true", help="Run full sensitivity sweeps")
    parser.add_argument("--small", action="store_true", help="Run small cluster baseline")
    args = parser.parse_args()

    seed_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    pattern_list = [p.strip() for p in args.patterns.split(",") if p.strip()]

    # Print Disjoint Data Split Windows
    print("=" * 105)
    print("                             DISJOINT DATA SPLIT BOUNDARIES")
    print("=" * 105)
    print("  1. Historical LightGBM Training : Day 0 to Day 7 (datasets/training_trace.parquet)")
    print("  2. Split-Conformal Calibration  : Trace Day 1 (steps 0 to 1440, strictly pre-test held-out)")
    print("  3. Out-of-Sample Test Evaluation: Trace Days 2 to 5 (steps 1440 to 7200, strictly disjoint)")
    print("=" * 105)

    # 1. Primary Benchmark (Multi-pattern, multi-seed on 20-node topology)
    primary_results = run_experiment_suite(
        patterns=pattern_list,
        seeds=seed_list,
        duration_days=args.days,
        horizon=args.horizon,
        topology="large",
        output_dir=args.output,
        study_label="Primary Multi-Pattern Benchmark (20 Nodes)",
    )

    primary_path = os.path.join(args.output, "multi_pattern_ablation_results.json")
    with open(primary_path, "w") as f:
        json.dump(primary_results, f, indent=2)
    print(f"\nMulti-pattern ablation artifacts saved to: {primary_path}")

    # 2. Small cluster baseline
    if args.small:
        run_small_cluster_baseline(seeds=seed_list, output_dir=args.output)

    # 3. Sensitivity sweeps
    if args.sweep:
        run_sensitivity_sweeps(seeds=seed_list, output_dir=args.output)


if __name__ == "__main__":
    main()
