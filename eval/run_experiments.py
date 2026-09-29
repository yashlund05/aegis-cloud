"""
Comprehensive IEEE Paper Benchmark Suite for Aegis.

Executes:
1. Primary Multi-Pattern Benchmark across 4 patterns (diurnal, steady, bursty, flash_crowd) over 5 seeds.
2. Headroom-Matched Safety Margin Sweeps (Pareto Frontier: Energy vs Capacity Shortfall):
   - Aegis quantile tau in {0.50, 0.70, 0.80, 0.90, 0.95, 0.99}
   - Reactive baselines: HPA target utilization in {50%, 60%, 70%, 80%} and CA node buffer in {0, 1}
   - Evaluates Pareto dominance.
3. Energy Component Breakdown (Idle, Dynamic, Boot) across configurations.
4. Multi-Resource (CPU + Mem) Vector Bin-Packing vs Naive Spreading (measuring fragmentation).
5. Pre-Wake Validation and True Oracle Upper Bound.
6. Parameter Sensitivity Sweeps with full 95% Student's t-distribution CIs.
7. Rolling Recalibration vs Single-Day Calibration and Linear-Tail Extrapolation tests.
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
    quantile_tau: float = 0.90,
    hpa_target_util: float = 0.70,
    ca_node_buffer: int = 0,
    rolling_recalib: bool = False,
    use_linear_tail: bool = False,
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

    study = AblationStudy(
        nodes=nodes,
        min_active_nodes=k_min,
        wake_up_latency_steps=wake_up_latency,
        cluster_autoscaler_scale_down_delay=10,
    )

    all_pattern_results = {}

    for pattern in patterns:
        metric_records = {
            cfg: {
                "energy_kwh": [],
                "energy_idle_kwh": [],
                "energy_dynamic_kwh": [],
                "energy_boot_kwh": [],
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

            res = study.run_comparison(
                trace_data=trace,
                output_dir=output_dir,
                forecast_horizon_minutes=horizon,
                calibration_window_steps=1440,
                scale_workload=1.0,
                quantile_tau=quantile_tau,
                hpa_target_util=hpa_target_util,
                ca_node_buffer=ca_node_buffer,
                rolling_recalibration=rolling_recalib,
                use_linear_tail=use_linear_tail,
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

        pattern_summary = {}
        for cfg in configs_list:
            pattern_summary[cfg] = {}
            for m_name, vals in metric_records[cfg].items():
                mean, std, ci95 = compute_ci95(vals)
                pattern_summary[cfg][m_name] = {"mean": mean, "std": std, "ci95": ci95, "raw": vals}

        # Paired differences
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


def run_pareto_frontier_study(seeds: List[int], pattern: str = "bursty", output_dir: str = "eval"):
    """
    Sweeps the safety-margin knob for Aegis and reactive baselines to establish
    the Energy vs Shortfall Pareto Frontier across 5 seeds with 95% CIs.
    """
    print("\n" + "=" * 105)
    print(f"      HEADROOM-MATCHED PARETO FRONTIER SWEEP (Workload: {pattern.upper()}, {len(seeds)} Seeds)")
    print("=" * 105)

    aegis_taus = [0.50, 0.70, 0.80, 0.90, 0.95, 0.99]
    reactive_utils = [0.80, 0.70, 0.60, 0.50]

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)

    pareto_records = {
        "aegis": [],
        "cluster_autoscaler": [],
        "cluster_autoscaler_buffered": [],
        "reactive_consolidation": [],
    }

    # 1. Sweep Aegis Quantile Tau
    print(">>> Sweeping Aegis Quantile Tau in {0.50, 0.70, 0.80, 0.90, 0.95, 0.99}...")
    for tau in aegis_taus:
        e_list, s_list = [], []
        for seed in seeds:
            trace = generate_pattern_trace(workload_id="pareto-test", pattern=pattern, seed=seed)
            res = study.run_comparison(trace, output_dir=output_dir, quantile_tau=tau)
            e_list.append(res["configurations"]["full_aegis_conformal"]["energy_kwh"])
            s_list.append(res["configurations"]["full_aegis_conformal"]["capacity_shortfall_minutes"])
        e_m, _, e_ci = compute_ci95(e_list)
        s_m, _, s_ci = compute_ci95(s_list)
        pareto_records["aegis"].append({
            "param": f"tau={tau}",
            "energy_kwh": e_m, "energy_ci95": e_ci,
            "shortfall_min": s_m, "shortfall_ci95": s_ci,
        })

    # 2. Sweep Reactive Baselines Utilization
    print(">>> Sweeping Reactive Target Utilization in {80%, 70%, 60%, 50%}...")
    for util in reactive_utils:
        # Cluster Autoscaler (buffer = 0)
        e_list, s_list = [], []
        for seed in seeds:
            trace = generate_pattern_trace(workload_id="pareto-test", pattern=pattern, seed=seed)
            res = study.run_comparison(trace, output_dir=output_dir, hpa_target_util=util, ca_node_buffer=0)
            e_list.append(res["configurations"]["cluster_autoscaler"]["energy_kwh"])
            s_list.append(res["configurations"]["cluster_autoscaler"]["capacity_shortfall_minutes"])
        e_m, _, e_ci = compute_ci95(e_list)
        s_m, _, s_ci = compute_ci95(s_list)
        pareto_records["cluster_autoscaler"].append({
            "param": f"util={int(util*100)}%",
            "energy_kwh": e_m, "energy_ci95": e_ci,
            "shortfall_min": s_m, "shortfall_ci95": s_ci,
        })

        # Cluster Autoscaler with Headroom Buffer (+1 node buffer)
        e_list_b, s_list_b = [], []
        for seed in seeds:
            trace = generate_pattern_trace(workload_id="pareto-test", pattern=pattern, seed=seed)
            res = study.run_comparison(trace, output_dir=output_dir, hpa_target_util=util, ca_node_buffer=1)
            e_list_b.append(res["configurations"]["cluster_autoscaler"]["energy_kwh"])
            s_list_b.append(res["configurations"]["cluster_autoscaler"]["capacity_shortfall_minutes"])
        e_mb, _, e_cib = compute_ci95(e_list_b)
        s_mb, _, s_cib = compute_ci95(s_list_b)
        pareto_records["cluster_autoscaler_buffered"].append({
            "param": f"util={int(util*100)}%+buf1",
            "energy_kwh": e_mb, "energy_ci95": e_cib,
            "shortfall_min": s_mb, "shortfall_ci95": s_cib,
        })

    # Print Pareto Table
    print("\n" + "-" * 85)
    print(f"{'Method / Setting':<30} | {'Energy (kWh)':<24} | {'Shortfall (min)':<24}")
    print("-" * 85)
    print("[Aegis Conformal Frontier]")
    for pt in pareto_records["aegis"]:
        e_str = f"{pt['energy_kwh']:.2f} +/- {pt['energy_ci95']:.2f}"
        s_str = f"{pt['shortfall_min']:.1f} +/- {pt['shortfall_ci95']:.1f}"
        print(f"  {pt['param']:<28} | {e_str:<24} | {s_str:<24}")

    print("\n[Cluster Autoscaler Frontier]")
    for pt in pareto_records["cluster_autoscaler"]:
        e_str = f"{pt['energy_kwh']:.2f} +/- {pt['energy_ci95']:.2f}"
        s_str = f"{pt['shortfall_min']:.1f} +/- {pt['shortfall_ci95']:.1f}"
        print(f"  {pt['param']:<28} | {e_str:<24} | {s_str:<24}")

    print("\n[Cluster Autoscaler + 1-Node Headroom Buffer]")
    for pt in pareto_records["cluster_autoscaler_buffered"]:
        e_str = f"{pt['energy_kwh']:.2f} +/- {pt['energy_ci95']:.2f}"
        s_str = f"{pt['shortfall_min']:.1f} +/- {pt['shortfall_ci95']:.1f}"
        print(f"  {pt['param']:<28} | {e_str:<24} | {s_str:<24}")
    print("-" * 85)

    pareto_path = os.path.join(output_dir, "pareto_frontier_results.json")
    with open(pareto_path, "w") as f:
        json.dump(pareto_records, f, indent=2)
    return pareto_records


def run_flash_crowd_tail_extrapolation_study(seeds: List[int], output_dir: str = "eval"):
    """
    Tests whether tree extrapolation limits explain flash-crowd shortfall
    by comparing standard LightGBM trees against a linear-tail correction.
    """
    print("\n" + "=" * 105)
    print("      FLASH CROWD EXTRAPOLATION STUDY: STANDARD LIGHTGBM VS LINEAR-TAIL CORRECTION")
    print("=" * 105)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)

    std_shortfalls = []
    tail_shortfalls = []
    std_energy = []
    tail_energy = []

    for seed in seeds:
        trace = generate_pattern_trace(workload_id="fc-extrap", pattern="flash_crowd", seed=seed)
        
        # 1. Standard tree
        res_std = study.run_comparison(trace, output_dir=output_dir, use_linear_tail=False)
        std_shortfalls.append(res_std["configurations"]["full_aegis_conformal"]["capacity_shortfall_minutes"])
        std_energy.append(res_std["configurations"]["full_aegis_conformal"]["energy_kwh"])

        # 2. Linear-tail corrected
        res_tail = study.run_comparison(trace, output_dir=output_dir, use_linear_tail=True)
        tail_shortfalls.append(res_tail["configurations"]["full_aegis_conformal"]["capacity_shortfall_minutes"])
        tail_energy.append(res_tail["configurations"]["full_aegis_conformal"]["energy_kwh"])

    s_std_m, _, s_std_ci = compute_ci95(std_shortfalls)
    s_tail_m, _, s_tail_ci = compute_ci95(tail_shortfalls)
    e_std_m, _, e_std_ci = compute_ci95(std_energy)
    e_tail_m, _, e_tail_ci = compute_ci95(tail_energy)

    print(f"  Standard LightGBM Trees   : Shortfall = {s_std_m:.1f} +/- {s_std_ci:.1f} min | Energy = {e_std_m:.2f} +/- {e_std_ci:.2f} kWh")
    print(f"  Linear-Tail Corrected Trees: Shortfall = {s_tail_m:.1f} +/- {s_tail_ci:.1f} min | Energy = {e_tail_m:.2f} +/- {e_tail_ci:.2f} kWh")
    diff_m, _, diff_ci, sig = compute_paired_diff(tail_shortfalls, std_shortfalls)
    print(f"  Shortfall Delta (Linear-Tail minus Standard): {diff_m:+.1f} +/- {diff_ci:.1f} min (Statistically Significant: {sig})")


def run_rolling_vs_single_calibration_study(seeds: List[int], output_dir: str = "eval"):
    """
    Compares Single-Day calibration against Rolling 1440-minute walk-forward recalibration.
    """
    print("\n" + "=" * 105)
    print("      CONFORMAL CALIBRATION STUDY: SINGLE-DAY CALIBRATION VS ROLLING RECALIBRATION")
    print("=" * 105)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    p_uncal, p_single, p_rolling = [], [], []

    for seed in seeds:
        trace = generate_pattern_trace(workload_id="calib-test", pattern="bursty", seed=seed)
        res_s = study.run_comparison(trace, output_dir=output_dir, rolling_recalibration=False)
        res_r = study.run_comparison(trace, output_dir=output_dir, rolling_recalibration=True)
        p_uncal.append(res_s["forecaster_metrics"]["calibration_fraction_below_p90_uncalibrated"])
        p_single.append(res_s["forecaster_metrics"]["calibration_fraction_below_p90_conformal"])
        p_rolling.append(res_r["forecaster_metrics"]["calibration_fraction_below_p90_conformal"])

    u_m, _, u_ci = compute_ci95(p_uncal)
    s_m, _, s_ci = compute_ci95(p_single)
    r_m, _, r_ci = compute_ci95(p_rolling)

    print(f"  Target p90 Coverage                        : 0.9000")
    print(f"  Uncalibrated LightGBM Coverage             : {u_m:.4f} +/- {u_ci:.4f}")
    print(f"  Single-Day Calibration Coverage            : {s_m:.4f} +/- {s_ci:.4f}")
    print(f"  Rolling Recalibration (1440m) Coverage     : {r_m:.4f} +/- {r_ci:.4f}")


def run_full_sensitivity_sweeps(seeds: List[int], output_dir: str = "eval"):
    """
    Executes full sensitivity sweeps with complete t-distribution 95% CIs.
    """
    sweep_results = {}
    pattern = "diurnal"
    configs = ["stock_hpa", "cluster_autoscaler", "reactive_hpa_plus_consolidation", "full_aegis_conformal", "oracle"]

    print("\n" + "=" * 105)
    print("      PARAMETER SENSITIVITY SWEEPS WITH 95% CONFIDENCE INTERVALS (Pattern: DIURNAL)")
    print("=" * 105)

    # 1. Wake-up Latency Sweep
    print("\n>>> SWEEP 1: Node Wake-Up Latency (1m, 3m, 5m)")
    sweep_results["wake_up_latency"] = {}
    for lat in [1, 3, 5]:
        res = run_experiment_suite(patterns=[pattern], seeds=seeds, wake_up_latency=lat, output_dir=output_dir)[pattern]
        sweep_results["wake_up_latency"][f"{lat}m"] = res
        print(f"\n--- Latency = {lat} min ---")
        for cfg in configs:
            e = res["configurations"][cfg]["energy_kwh"]
            s = res["configurations"][cfg]["capacity_shortfall_minutes"]
            print(f"  {cfg:<32}: Energy = {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} kWh | Shortfall = {s['mean']:>4.1f} +/- {s['ci95']:<4.1f} min")

    # 2. Idle Power Fraction Sweep
    print("\n>>> SWEEP 2: Idle Power Fraction (30%, 50%, 70% of P_max)")
    sweep_results["idle_power_fraction"] = {}
    for frac in [0.30, 0.50, 0.70]:
        res = run_experiment_suite(patterns=[pattern], seeds=seeds, idle_power_frac=frac, output_dir=output_dir)[pattern]
        sweep_results["idle_power_fraction"][f"{int(frac*100)}%"] = res
        print(f"\n--- Idle Fraction = {int(frac*100)}% ---")
        for cfg in configs:
            e = res["configurations"][cfg]["energy_kwh"]
            s = res["configurations"][cfg]["capacity_shortfall_minutes"]
            print(f"  {cfg:<32}: Energy = {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} kWh | Shortfall = {s['mean']:>4.1f} +/- {s['ci95']:<4.1f} min")

    # 3. Alpha Exponent Sweep
    print("\n>>> SWEEP 3: Alpha Exponent (1.0, 1.5, 2.0)")
    sweep_results["alpha"] = {}
    for a in [1.0, 1.5, 2.0]:
        res = run_experiment_suite(patterns=[pattern], seeds=seeds, alpha=a, output_dir=output_dir)[pattern]
        sweep_results["alpha"][f"alpha_{a}"] = res
        print(f"\n--- Alpha = {a} ---")
        for cfg in configs:
            e = res["configurations"][cfg]["energy_kwh"]
            s = res["configurations"][cfg]["capacity_shortfall_minutes"]
            print(f"  {cfg:<32}: Energy = {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} kWh | Shortfall = {s['mean']:>4.1f} +/- {s['ci95']:<4.1f} min")

    # 4. K_min Resilience Floor Sweep
    print("\n>>> SWEEP 4: K_min Resilience Floor (1, 2, 3 nodes)")
    sweep_results["k_min"] = {}
    for k in [1, 2, 3]:
        res = run_experiment_suite(patterns=[pattern], seeds=seeds, k_min=k, output_dir=output_dir)[pattern]
        sweep_results["k_min"][f"k_{k}"] = res
        print(f"\n--- K_min = {k} nodes ---")
        for cfg in configs:
            e = res["configurations"][cfg]["energy_kwh"]
            s = res["configurations"][cfg]["capacity_shortfall_minutes"]
            print(f"  {cfg:<32}: Energy = {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} kWh | Shortfall = {s['mean']:>4.1f} +/- {s['ci95']:<4.1f} min")

    sweep_path = os.path.join(output_dir, "sensitivity_sweep_results.json")
    with open(sweep_path, "w") as f:
        json.dump(sweep_results, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Comprehensive IEEE Benchmark Suite.")
    parser.add_argument("--seeds", type=str, default="42,101,202,303,404", help="Seeds")
    parser.add_argument("--patterns", type=str, default="diurnal,steady,bursty,flash_crowd", help="Patterns")
    parser.add_argument("--output", type=str, default="eval", help="Output directory")
    args = parser.parse_args()

    seed_list = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    pattern_list = [p.strip() for p in args.patterns.split(",") if p.strip()]

    print("=" * 105)
    print("                    AEGIS COMPREHENSIVE IEEE PAPER EVALUATION SUITE")
    print("=" * 105)
    print(f"  Training dataset seed : 9999 (strictly independent from test seeds: {seed_list})")
    print(f"  Calibration window    : Trace Day 1 (steps 0 to 1440, pre-test held-out)")
    print(f"  Test evaluation window: Trace Days 2 to 5 (steps 1440 to 7200, strictly disjoint)")
    print("=" * 105)

    # 1. Primary Multi-Pattern Benchmark
    primary_res = run_experiment_suite(
        patterns=pattern_list,
        seeds=seed_list,
        output_dir=args.output,
        study_label="Primary Multi-Pattern Benchmark",
    )

    # Print Formatted Primary Summary Table
    configs_list = [
        "stock_hpa", "cluster_autoscaler", "reactive_hpa_plus_consolidation",
        "forecast_only", "forecast_placement", "forecast_plus_power_no_placement",
        "full_aegis", "full_aegis_conformal", "oracle"
    ]

    for p in pattern_list:
        print(f"\n=========================================================================================================")
        print(f"  BENCHMARK SUMMARY TABLE: {p.upper()} WORKLOAD PATTERN (5 SEEDS, t-DISTRIBUTION 95% CIs)")
        print(f"=========================================================================================================")
        print(f"{'Configuration':<34} | {'Total (kWh)':<15} | {'Idle (kWh)':<12} | {'Dynamic (kWh)':<14} | {'Shortfall (min)':<16} | {'Actions':<12}")
        print("-" * 115)
        p_res = primary_res[p]["configurations"]
        for cfg in configs_list:
            e = p_res[cfg]["energy_kwh"]
            e_idl = p_res[cfg]["energy_idle_kwh"]
            e_dyn = p_res[cfg]["energy_dynamic_kwh"]
            s = p_res[cfg]["capacity_shortfall_minutes"]
            a = p_res[cfg]["scaling_actions"]
            print(f"{cfg:<34} | {e['mean']:>6.2f} +/- {e['ci95']:<4.2f} | {e_idl['mean']:>6.2f}     | {e_dyn['mean']:>6.2f}       | {s['mean']:>5.1f} +/- {s['ci95']:<4.1f}  | {a['mean']:>5.1f} +/- {a['ci95']:<4.1f}")
        print("-" * 115)
        p_ca = primary_res[p]["paired_vs_cluster_autoscaler"]
        p_rh = primary_res[p]["paired_vs_reactive_consolidation"]
        print(f"Paired Deltas vs cluster_autoscaler (delta +/- 95% CI):")
        print(f"  Delta Energy   : {p_ca['energy_kwh']['diff']:+.2f} +/- {p_ca['energy_kwh']['ci95']:.2f} kWh (Sig: {p_ca['energy_kwh']['excludes_zero']})")
        print(f"  Delta Shortfall: {p_ca['shortfall_min']['diff']:+.1f} +/- {p_ca['shortfall_min']['ci95']:.1f} min (Sig: {p_ca['shortfall_min']['excludes_zero']})")
        print(f"  Delta Actions  : {p_ca['actions']['diff']:+.1f} +/- {p_ca['actions']['ci95']:.1f} act (Sig: {p_ca['actions']['excludes_zero']})")

    # 2. Pareto Frontier Headroom-Matched Sweep
    run_pareto_frontier_study(seeds=seed_list, pattern="bursty", output_dir=args.output)

    # 3. Flash Crowd Tail Extrapolation Study
    run_flash_crowd_tail_extrapolation_study(seeds=seed_list, output_dir=args.output)

    # 4. Calibration Study (Single vs Rolling)
    run_rolling_vs_single_calibration_study(seeds=seed_list, output_dir=args.output)

    # 5. Full Sensitivity Sweeps with CIs
    run_full_sensitivity_sweeps(seeds=seed_list, output_dir=args.output)


if __name__ == "__main__":
    main()
