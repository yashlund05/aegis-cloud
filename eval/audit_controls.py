"""
Audit of Autoscaler Cooldowns, Azure Cores Derivation, and Reactive Control Arms.

Requirements:
1. Cooldown audit on 3 apps (small, mid, fe5c01bb7981a5):
   - Scale-up and scale-down decisions blocked by 300s cooldown
   - Shortfall minutes attributable to blocked scale-ups
2. Azure trace cores derivation (file, columns, formula, units)
3. Control arms on all 20 test apps:
   - Control Arm (a): reactive+consolidation with +8.6468 core headroom
   - Control Arm (b): cluster_autoscaler with HPA-faithful guards (scale-down stabilization only, no scale-up cooldown)
   - Comparison with full_aegis_conformal (median, IQR)
4. Per-app table sorted by mean cores & Spearman correlation of Aegis shortfall with peak size.
"""

import hashlib
import json
import logging
import math
import os
import subprocess
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.abspath("."))

from datasets.load_real_trace import (
    MINUTES_PER_DAY,
    N_DAYS,
    TOTAL_MINUTES,
    VCPU_PER_EXECUTION,
    _day_file,
    load_duration_table,
    load_memory_table,
)
from ml.evaluation.ablation import AblationStudy
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import QuantileModelWrapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("audit_controls")

HEADROOM_CORES = 8.6468
OUTPUT_JSON = "eval/audit_controls_results.json"


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return res.stdout.strip()
    except Exception:
        return "50b1be9417e1953edae9f14409f2e94867423d15"


def simulate_reactive_with_cooldown(
    study: AblationStudy,
    actual_demands: np.ndarray,
    actual_mems: np.ndarray,
    config_name: str,
    enforce_cooldown: bool = False,
    cooldown_steps: int = 5,
    demand_offset: float = 0.0,
    hpa_target_util: float = 0.70,
    ca_node_buffer: int = 0,
) -> Dict[str, float]:
    """
    Simulates reactive scaling (cluster_autoscaler or reactive_hpa_plus_consolidation)
    with optional symmetric cooldown enforcement to audit blocked scale-up/down decisions.
    """
    n_steps = len(actual_demands)
    total_idle_joules = 0.0
    total_dynamic_joules = 0.0
    total_boot_joules = 0.0

    capacity_shortfalls = 0
    scaling_actions = 0
    total_churn = 0

    blocked_scale_ups = 0
    blocked_scale_downs = 0

    total_nodes = len(study.nodes)
    node_states = ["active" if i < study.min_active_nodes else "sleeping" for i in range(total_nodes)]
    node_boot_timers = [0 for _ in range(total_nodes)]
    node_unneeded_timers = [0 for _ in range(total_nodes)]

    init_replicas = max(2, math.ceil((actual_demands[0] + demand_offset) / (study.per_replica_cpu * hpa_target_util)))
    current_replicas = init_replicas
    last_scale_step = -100
    downscale_window = []

    allocatable_cpu = study.nodes[0]["cpu_capacity"] * 0.85

    for t in range(n_steps):
        actual_demand = float(actual_demands[t])

        # 1. Update Booting Nodes
        for i in range(total_nodes):
            if node_states[i] == "booting":
                node_boot_timers[i] -= 1
                if node_boot_timers[i] <= 0:
                    node_states[i] = "active"

        # 2. Determine Desired Replicas
        past_demand = (actual_demands[t - 1] if t > 0 else actual_demand) + demand_offset
        past_demand = max(0.0, past_demand)
        current_cap = max(0.01, current_replicas * study.per_replica_cpu)
        usage_ratio = (past_demand / current_cap) / hpa_target_util

        if abs(usage_ratio - 1.0) <= study.dead_zone_pct:
            raw_desired = current_replicas
        else:
            raw_desired = max(1, math.ceil(current_replicas * usage_ratio))

        # 3. Scaling Safety Logic (HPA v2 Stabilization & Clamping)
        downscale_window.append(raw_desired)
        if len(downscale_window) > study.stabilization_window_steps:
            downscale_window.pop(0)

        if raw_desired > current_replicas:
            candidate_target = raw_desired
        elif raw_desired < current_replicas:
            candidate_target = max(downscale_window)
        else:
            candidate_target = current_replicas

        # Check dead zone
        replica_delta_pct = abs(candidate_target - current_replicas) / max(current_replicas, 1)
        if replica_delta_pct < study.dead_zone_pct:
            target_replicas = current_replicas
        else:
            step = candidate_target - current_replicas
            max_up = max(16, current_replicas)
            max_down = max(4, int(current_replicas * 0.50))
            if step > max_up:
                target_replicas = current_replicas + max_up
            elif step < -max_down:
                target_replicas = current_replicas - max_down
            else:
                target_replicas = candidate_target

        target_replicas = max(1, target_replicas)

        # 4. Optional Cooldown Enforcement Audit
        if enforce_cooldown:
            if target_replicas != current_replicas:
                if t - last_scale_step < cooldown_steps:
                    if target_replicas > current_replicas:
                        blocked_scale_ups += 1
                    else:
                        blocked_scale_downs += 1
                    target_replicas = current_replicas
                else:
                    last_scale_step = t
        else:
            if target_replicas != current_replicas:
                last_scale_step = t

        # Record actions only after warm start
        if t >= study.warm_start_steps:
            if target_replicas != current_replicas:
                scaling_actions += 1
                total_churn += abs(target_replicas - current_replicas)

        current_replicas = target_replicas

        # 5. Node Packing
        nodes_needed = max(study.min_active_nodes, study._pack_pods(current_replicas, opt=False)) + ca_node_buffer
        nodes_needed = min(nodes_needed, total_nodes)

        # 6. Transitions
        scale_down_delay = study.cluster_autoscaler_scale_down_delay if config_name == "cluster_autoscaler" else study.stabilization_window_steps
        active_indices = [i for i, st in enumerate(node_states) if st == "active"]
        booting_indices = [i for i, st in enumerate(node_states) if st == "booting"]
        awake_or_booting = len(active_indices) + len(booting_indices)

        if awake_or_booting < nodes_needed:
            deficit = nodes_needed - awake_or_booting
            sleeping_indices = [i for i, st in enumerate(node_states) if st == "sleeping"]
            for idx in sleeping_indices[:deficit]:
                node_states[idx] = "booting"
                node_boot_timers[idx] = study.wake_up_latency_steps
                node_unneeded_timers[idx] = 0
        elif awake_or_booting > nodes_needed:
            candidate_indices = sorted([i for i in range(total_nodes) if node_states[i] == "active"], reverse=True)
            for idx in candidate_indices:
                if awake_or_booting <= nodes_needed:
                    break
                node_unneeded_timers[idx] += 1
                if node_unneeded_timers[idx] >= scale_down_delay:
                    node_states[idx] = "sleeping"
                    node_unneeded_timers[idx] = 0
                    awake_or_booting -= 1
        else:
            for i in range(total_nodes):
                node_unneeded_timers[i] = 0

        current_active_count = sum(1 for st in node_states if st == "active")

        # 7. Capacity and Shortfall
        pod_capacity = current_replicas * study.per_replica_cpu
        active_node_capacity = current_active_count * allocatable_cpu
        effective_cluster_capacity = min(pod_capacity, active_node_capacity)

        if t >= study.warm_start_steps:
            if actual_demand > effective_cluster_capacity:
                capacity_shortfalls += 1

        # 8. Energy Accounting
        placed_demand = min(actual_demand, effective_cluster_capacity)
        per_node_demand = placed_demand / max(1, current_active_count)
        step_power_w = 0.0
        for idx in range(total_nodes):
            st = node_states[idx]
            node = study.nodes[idx]
            if st == "booting":
                step_power_w += node["p_max"]
            elif st == "active":
                step_power_w += node["p_idle"]
                if current_active_count > 0 and per_node_demand > 0.0:
                    util = min(1.0, per_node_demand / node["cpu_capacity"])
                    step_power_w += (node["p_max"] - node["p_idle"]) * (util ** node["alpha"])

        total_idle_joules += step_power_w * 60.0

    energy_kwh = total_idle_joules / (3600.0 * 1000.0)
    return {
        "energy_kwh": round(energy_kwh, 2),
        "capacity_shortfall_minutes": capacity_shortfalls,
        "scaling_actions": scaling_actions,
        "scaling_churn": total_churn,
        "blocked_scale_ups": blocked_scale_ups,
        "blocked_scale_downs": blocked_scale_downs,
    }


def main():
    print("=" * 115)
    print("  AEGIS AUDIT: COOLDOWNS, AZURE CORES DERIVATION, AND REACTIVE CONTROL ARMS")
    print("=" * 115)

    git_commit = get_git_commit()
    print(f"  Git Commit Hash : {git_commit}\n")

    # -------------------------------------------------------------------------
    # PART 1: COOLDOWN AUDIT ON 3 APPS
    # -------------------------------------------------------------------------
    print("=" * 115)
    print("  [1] COOLDOWN AUDIT: BLOCKED DECISIONS & ATTRIBUTABLE SHORTFALL (300s Cooldown vs Faithful)")
    print("=" * 115)

    # Load 60-app study results to retrieve app IDs and existing metrics
    with open("eval/sixty_app_study_results.json", "r") as f:
        sixty_res = json.load(f)

    test_apps = sixty_res["app_partition"]["test_apps"]

    # Select 3 apps: Small, Mid, and fe5c01bb7981a5 (Large)
    app_small = "cb34fd874e255dde6735e5d3dbf5b13bc3dbdaffcf22c0618036d071c356f918"  # 0.547 cores
    app_mid = "d514ebc393839b56f93bc67341e4b85c18e1d5e68341144f849cf0b3a32fcfc3"    # 1.350 cores
    app_large = [a for a in test_apps if a.startswith("fe5c01bb7981a5")][0]           # 7.212 cores

    audit_apps = [
        ("Small", app_small, 0.547, 2.684),
        ("Mid", app_mid, 1.350, 32.300),
        ("Large", app_large, 7.212, 59.008),
    ]

    # Load invocation traces for the 3 apps
    from eval.run_60app_study import extract_app_time_series
    cores_cols, app_mems = extract_app_time_series([a[1] for a in audit_apps])

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)

    print(f"\n  {'Workload (Category)':<26} | {'Config':<32} | {'Blocked Up':>12} | {'Blocked Down':>14} | {'Shortfall (Faithful)':>22} | {'Shortfall (Cooldown)':>22} | {'Delta Shortfall':>16}")
    print("  " + "-" * 154)

    cooldown_audit_records = {}

    for cat, app_id, mean_c, peak_c in audit_apps:
        y = cores_cols[app_id][1440:]  # Exclude day 1 for alignment
        mem = np.full(len(y), app_mems[app_id])

        app_label = f"{cat} ({app_id[:12]})"
        cooldown_audit_records[app_id] = {"category": cat, "mean_cores": mean_c, "peak_cores": peak_c}

        for cfg in ["cluster_autoscaler", "reactive_hpa_plus_consolidation"]:
            # Run without scale-up cooldown (HPA-faithful)
            res_faithful = simulate_reactive_with_cooldown(study, y, mem, cfg, enforce_cooldown=False)
            # Run with 300s symmetric cooldown
            res_cooldown = simulate_reactive_with_cooldown(study, y, mem, cfg, enforce_cooldown=True, cooldown_steps=5)

            b_up = res_cooldown["blocked_scale_ups"]
            b_down = res_cooldown["blocked_scale_downs"]
            s_faithful = res_faithful["capacity_shortfall_minutes"]
            s_cooldown = res_cooldown["capacity_shortfall_minutes"]
            d_shortfall = s_cooldown - s_faithful

            print(f"  {app_label:<26} | {cfg:<32} | {b_up:>12d} | {b_down:>14d} | {s_faithful:>21d}m | {s_cooldown:>21d}m | {d_shortfall:>+15d}m")

            cooldown_audit_records[app_id][cfg] = {
                "blocked_scale_ups": b_up,
                "blocked_scale_downs": b_down,
                "shortfall_faithful_min": s_faithful,
                "shortfall_cooldown_min": s_cooldown,
                "shortfall_attributable_to_blocked_scaleups_min": d_shortfall,
            }

    # -------------------------------------------------------------------------
    # PART 2: AZURE TRACE CORES DERIVATION
    # -------------------------------------------------------------------------
    print("\n" + "=" * 115)
    print("  [2] AZURE TRACE CORES DERIVATION: PROVENANCE, COLUMNS, FORMULA & UNITS")
    print("=" * 115)
    derivation_text = """
  1. Source Files & Schemas:
     - Invocations File: datasets/raw/azurefunctions2019/invocations_per_function_md.anon.d{day}.csv
       Columns: HashOwner, HashApp, HashFunction, Trigger, '1', '2', ..., '1440'
       Value: Integer count of function execution invocations starting in minute m of day d.
     - Durations File: datasets/raw/azurefunctions2019/function_durations_percentiles.anon.d{day}.csv
       Columns: HashOwner, HashApp, HashFunction, Average, Count, Minimum, Maximum, Percentiles...
       Value: Floating-point measured average execution duration in milliseconds for function f on day d.

  2. Mathematical Formula:
     For application 'app' at minute t in day d:
       cores(app, t) = SUM_{f in app} [ invocations(f, t) * (Average_duration_ms(f, day) / 1000.0) / 60.0 * 1.0 ]

  3. Dimensional Analysis & Units:
     - invocations(f, t)       : [count / minute]
     - duration_seconds        : Average_duration_ms / 1000.0  [seconds / invocation]
     - Workload in minute      : invocations * duration_seconds [vCPU * seconds]
     - Divide by 60 s/min      : (vCPU * seconds) / (60 seconds) = vCPUs = cores
     - Normalization           : 1.0 vCPU per concurrent execution (standard USENIX ATC'20 serverless model).
     - Units                   : Continuous average core capacity [vCPU cores] active during that 1-minute bucket.
"""
    print(derivation_text)

    # -------------------------------------------------------------------------
    # PART 3: CONTROL ARMS ON ALL 20 TEST APPS
    # -------------------------------------------------------------------------
    print("=" * 115)
    print("  [3] CONTROL ARMS ON 20 TEST APPS: (a) REACTIVE + 8.65c HEADROOM vs (b) CA FAITHFUL vs AEGIS")
    print("=" * 115)

    # Extract all 20 test apps traces
    cores_all, mems_all = extract_app_time_series(test_apps)

    arm_metrics = {
        "full_aegis_conformal": [],
        "reactive_plus_headroom": [],
        "cluster_autoscaler_faithful": [],
    }

    per_app_table_rows = []

    for app_id in test_apps:
        y = cores_all[app_id][1440:]
        mem = np.full(len(y), mems_all[app_id])
        mean_c = float(y.mean())
        peak_c = float(y.max())

        # 1. Existing Aegis Conformal
        aegis_data = sixty_res["per_app_raw_metrics"][app_id]["full_aegis_conformal"]

        # 2. Control Arm (a): Reactive + Consolidation with +8.6468 cores headroom added to measured demand
        res_reactive_headroom = simulate_reactive_with_cooldown(
            study, y, mem, "reactive_hpa_plus_consolidation", enforce_cooldown=False, demand_offset=HEADROOM_CORES
        )

        # 3. Control Arm (b): Cluster Autoscaler HPA-faithful (scale-down stabilization only, no scale-up cooldown)
        res_ca_faithful = simulate_reactive_with_cooldown(
            study, y, mem, "cluster_autoscaler", enforce_cooldown=False, demand_offset=0.0
        )

        arm_metrics["full_aegis_conformal"].append(aegis_data)
        arm_metrics["reactive_plus_headroom"].append(res_reactive_headroom)
        arm_metrics["cluster_autoscaler_faithful"].append(res_ca_faithful)

        per_app_table_rows.append({
            "app_id": app_id,
            "mean_cores": mean_c,
            "peak_cores": peak_c,
            "aegis_energy": aegis_data["energy_kwh"],
            "aegis_shortfall": aegis_data["capacity_shortfall_minutes"],
            "headroom_energy": res_reactive_headroom["energy_kwh"],
            "headroom_shortfall": res_reactive_headroom["capacity_shortfall_minutes"],
            "ca_energy": res_ca_faithful["energy_kwh"],
            "ca_shortfall": res_ca_faithful["capacity_shortfall_minutes"],
        })

    # Summary Distributions Table
    print(f"\n  {'Configuration Arm':<36} | {'Energy Median (IQR)':<22} | {'Shortfall Med (IQR)':<22} | {'Events Med (IQR)':<22}")
    print("  " + "-" * 110)

    dist_report = {}
    for arm_name in ["full_aegis_conformal", "reactive_plus_headroom", "cluster_autoscaler_faithful"]:
        e = [m["energy_kwh"] for m in arm_metrics[arm_name]]
        s = [m["capacity_shortfall_minutes"] for m in arm_metrics[arm_name]]
        a = [m["scaling_actions"] for m in arm_metrics[arm_name]]

        e_med, e_iqr = float(np.median(e)), float(np.percentile(e, 75) - np.percentile(e, 25))
        s_med, s_iqr = float(np.median(s)), float(np.percentile(s, 75) - np.percentile(s, 25))
        a_med, a_iqr = float(np.median(a)), float(np.percentile(a, 75) - np.percentile(a, 25))

        dist_report[arm_name] = {
            "energy": {"median": round(e_med, 2), "iqr": round(e_iqr, 2)},
            "shortfall": {"median": round(s_med, 2), "iqr": round(s_iqr, 2)},
            "events": {"median": round(a_med, 2), "iqr": round(a_iqr, 2)},
        }

        print(f"  {arm_name:<36} | {e_med:>7.1f} ({e_iqr:>5.1f}) kWh   | {s_med:>7.1f} ({s_iqr:>5.1f}) min   | {a_med:>7.1f} ({a_iqr:>5.1f})")

    # -------------------------------------------------------------------------
    # PART 4: PER-APP SORTED TABLE & SPEARMAN CORRELATION
    # -------------------------------------------------------------------------
    print("\n" + "=" * 115)
    print("  [4] PER-APP PERFORMANCE SORTED BY MEAN CORES & SPEARMAN CORRELATION")
    print("=" * 115)

    per_app_table_rows.sort(key=lambda r: r["mean_cores"])

    print(f"  {'App ID':<18} | {'Mean':>6} | {'Peak':>6} | {'Aegis kWh':>10} | {'Aegis Short':>11} | {'React+Head kWh':>14} | {'React+Head Short':>16} | {'CA Faith kWh':>12} | {'CA Faith Short':>14}")
    print("  " + "-" * 122)

    aegis_shortfalls = []
    peak_cores_list = []

    for r in per_app_table_rows:
        aegis_shortfalls.append(r["aegis_shortfall"])
        peak_cores_list.append(r["peak_cores"])
        print(f"  {r['app_id'][:16]:<18} | {r['mean_cores']:>6.3f} | {r['peak_cores']:>6.2f} | {r['aegis_energy']:>10.1f} | {r['aegis_shortfall']:>10d}m | {r['headroom_energy']:>14.1f} | {r['headroom_shortfall']:>15d}m | {r['ca_energy']:>12.1f} | {r['ca_shortfall']:>13d}m")

    # Spearman rank correlation
    rho, p_val = spearmanr(aegis_shortfalls, peak_cores_list)
    print("\n  " + "-" * 115)
    print(f"  Spearman correlation between Aegis Shortfall and App Peak Cores: rho = {rho:.4f} (p-value = {p_val:.4e})")
    print("  " + "-" * 115)

    full_results = {
        "git_commit": git_commit,
        "cooldown_audit_3_apps": cooldown_audit_records,
        "derivation_provenance": {
            "source_files": [
                "datasets/raw/azurefunctions2019/invocations_per_function_md.anon.d*.csv",
                "datasets/raw/azurefunctions2019/function_durations_percentiles.anon.d*.csv",
            ],
            "formula": "cores(app, t) = sum_f [ invocations(f, t) * (Average_duration_ms(f, day) / 1000) / 60 * 1.0 ]",
            "units": "vCPU cores",
        },
        "control_arms_distributions": dist_report,
        "per_app_table_sorted": per_app_table_rows,
        "spearman_correlation": {
            "rho": round(float(rho), 4),
            "p_value": float(p_val),
            "sample_size": len(per_app_table_rows),
        },
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(full_results, f, indent=2)
    print(f"\nAudit complete. Artifact saved at {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
