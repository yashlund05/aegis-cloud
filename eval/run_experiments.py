"""
Comprehensive IEEE Paper Benchmark Suite for Aegis (frozen simulator harness).

Sections (all print tables and persist JSON under eval/):
  A. Primary Multi-Pattern Benchmark  -> eval/multi_pattern_ablation_results.json
  B. Item 2: Replica/node time series + action-count decomposition -> eval/item2_timeseries.json
  C. Item 3: K_min sweep on low_load  -> eval/item3_kmin_sweep.json
  D. Item 4: Pareto frontier incl. oracle + matched-shortfall paired deltas
     on Poisson bursty AND structured_burst -> eval/pareto_frontier_results.json
  E. Item 5: Node wake latency sweep {1,3,5,10,15} min -> eval/item5_wake_sweep.json
  F. Item 6: Measured placement effect (power-down on in both arms) -> eval/item6_placement.json
  G. Item 7: Rolling vs single-day calibration, per-seed raw coverage -> eval/item7_calibration.json
  H. Item 8: HPA-realistic scale-up flash crowd study + step-limit sweep -> eval/item8_flash_crowd.json

Run:  python eval/run_experiments.py --seeds 42,101,202,303,404
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Tuple

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.abspath("."))

from datasets.workload_patterns import generate_pattern_trace
from ml.evaluation.ablation import AblationStudy, get_default_nodes

ALL_CONFIGS = [
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


def compute_ci95(data: list) -> Tuple[float, float, float]:
    arr = np.array(data, dtype=float)
    n = len(arr)
    mean = float(np.mean(arr))
    if n <= 1:
        return mean, 0.0, 0.0
    std = float(np.std(arr, ddof=1))
    sem = std / np.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    return round(mean, 2), round(std, 2), round(float(t_crit * sem), 2)


def paired_diff(a_vals: list, b_vals: list) -> Dict[str, float]:
    diffs = np.array(a_vals, dtype=float) - np.array(b_vals, dtype=float)
    n = len(diffs)
    mean = float(np.mean(diffs))
    if n <= 1:
        return {"mean": mean, "ci95": 0.0, "excludes_zero": False}
    std = float(np.std(diffs, ddof=1))
    sem = std / np.sqrt(n)
    t_crit = float(stats.t.ppf(0.975, df=n - 1))
    ci95 = float(t_crit * sem)
    return {
        "mean": round(mean, 3),
        "ci95": round(ci95, 3),
        "excludes_zero": bool(mean - ci95 > 0 or mean + ci95 < 0),
    }


def interp_energy_at_shortfall(points: List[Tuple[float, float]], target_sf: float) -> float:
    """Linear interpolation of energy at a target shortfall along a method's
    (shortfall, energy) sweep curve. points must be sorted by shortfall."""
    pts = sorted(points, key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    return float(np.interp(target_sf, xs, ys))


# ---------------------------------------------------------------------------
# A. Primary multi-pattern benchmark
# ---------------------------------------------------------------------------
def run_primary(seeds: List[int], patterns: List[str], output_dir: str) -> Dict:
    print("\n" + "=" * 118)
    print("  [A] PRIMARY MULTI-PATTERN BENCHMARK (5 seeds, warm-start 60 min excluded, t-based 95% CIs)")
    print("=" * 118)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    out = {}
    for pattern in patterns:
        rec = {cfg: {m: [] for m in (
            "energy_kwh", "energy_idle_kwh", "energy_dynamic_kwh", "energy_boot_kwh",
            "capacity_shortfall_minutes", "scaling_actions", "scaling_churn",
            "mean_allocated_replicas", "mean_active_nodes")} for cfg in ALL_CONFIGS}
        fm_rec: Dict[str, list] = {}
        for seed in seeds:
            trace = generate_pattern_trace(f"workload-{pattern}", pattern=pattern, duration_days=5, seed=seed)
            res = study.run_comparison(trace, output_dir=output_dir)
            for k, v in res["forecaster_metrics"].items():
                fm_rec.setdefault(k, []).append(v)
            for cfg in ALL_CONFIGS:
                for m in rec[cfg]:
                    rec[cfg][m].append(res["configurations"][cfg][m])

        summary = {cfg: {m: compute_ci95(v) for m, v in rec[cfg].items()} for cfg in ALL_CONFIGS}
        # keep raw per-seed values for pairing
        for cfg in ALL_CONFIGS:
            for m, v in rec[cfg].items():
                summary[cfg][m] = {"mean": summary[cfg][m][0], "std": summary[cfg][m][1],
                                   "ci95": summary[cfg][m][2], "raw": v}

        print(f"\n  BENCHMARK SUMMARY: {pattern.upper()}  (trace = 5 days, eval = 5700 min after warm start)")
        hdr = (f"  {'Configuration':<34} | {'Total kWh':<16} | {'Idle kWh':<13} | {'Dyn kWh':<13} | "
               f"{'Shortfall min':<17} | {'Actions(ev)':<13} | {'Churn(pods)':<13} | {'Nodes':<7}")
        print(hdr)
        print("  " + "-" * 132)
        for cfg in ALL_CONFIGS:
            e, i, d = summary[cfg]["energy_kwh"], summary[cfg]["energy_idle_kwh"], summary[cfg]["energy_dynamic_kwh"]
            s, a, c, n = (summary[cfg]["capacity_shortfall_minutes"], summary[cfg]["scaling_actions"],
                          summary[cfg]["scaling_churn"], summary[cfg]["mean_active_nodes"])
            print(f"  {cfg:<34} | {e['mean']:>7.2f} +/-{e['ci95']:<6.2f} | {i['mean']:>6.2f}       | "
                  f"{d['mean']:>6.2f}       | {s['mean']:>6.1f} +/-{s['ci95']:<5.1f} | {a['mean']:>5.1f} +/-{a['ci95']:<5.1f} | "
                  f"{c['mean']:>6.1f}       | {n['mean']:>4.1f}")

        paired = {
            "energy_vs_ca": paired_diff(rec["full_aegis_conformal"]["energy_kwh"], rec["cluster_autoscaler"]["energy_kwh"]),
            "shortfall_vs_ca": paired_diff(rec["full_aegis_conformal"]["capacity_shortfall_minutes"], rec["cluster_autoscaler"]["capacity_shortfall_minutes"]),
            "churn_vs_ca": paired_diff(rec["full_aegis_conformal"]["scaling_churn"], rec["cluster_autoscaler"]["scaling_churn"]),
        }
        print("  Paired deltas (full_aegis_conformal - cluster_autoscaler), per-seed, 95% t-interval:")
        print(f"    Energy   : {paired['energy_vs_ca']['mean']:+.2f} +/- {paired['energy_vs_ca']['ci95']:.2f} kWh  (CI excludes 0: {paired['energy_vs_ca']['excludes_zero']})")
        print(f"    Shortfall: {paired['shortfall_vs_ca']['mean']:+.1f} +/- {paired['shortfall_vs_ca']['ci95']:.1f} min   (CI excludes 0: {paired['shortfall_vs_ca']['excludes_zero']})")
        print(f"    Churn    : {paired['churn_vs_ca']['mean']:+.1f} +/- {paired['churn_vs_ca']['ci95']:.1f} pods  (CI excludes 0: {paired['churn_vs_ca']['excludes_zero']})")

        out[pattern] = {"configurations": summary,
                        "forecaster_metrics": {k: compute_ci95(v) for k, v in fm_rec.items()},
                        "forecaster_metrics_raw": fm_rec,
                        "paired_vs_cluster_autoscaler": paired}
    with open(os.path.join(output_dir, "multi_pattern_ablation_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# B. Item 2: time series + action decomposition
# ---------------------------------------------------------------------------
def run_item2(seeds: List[int], output_dir: str, seed_for_series: int = 42) -> Dict:
    print("\n" + "=" * 118)
    print("  [B / ITEM 2] REPLICA & ACTIVE-NODE TRAJECTORIES + ACTION DECOMPOSITION")
    print("=" * 118)
    cfgs = ["cluster_autoscaler", "full_aegis_conformal", "oracle"]
    out: Dict = {}
    for pattern in ("diurnal", "bursty"):
        study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
        trace = generate_pattern_trace(f"item2-{pattern}", pattern=pattern, duration_days=5, seed=seed_for_series)
        res = study.run_comparison(trace, output_dir=output_dir, configs_to_run=cfgs, return_series=True)

        print(f"\n  {pattern.upper()}, seed {seed_for_series}: replicas / active nodes over time (hourly samples from warm-start)")
        print(f"  {'minute':>7} | {'demand':>8} | " + " | ".join(f"{c.replace('full_aegis_','aegis_'):>26}" for c in cfgs))
        print("  " + "-" * 100)
        sers = {c: res["configurations"][c]["series"] for c in cfgs}
        minutes = sers[cfgs[0]]["minute"]
        for k in range(0, len(minutes), 60):
            row = []
            for c in cfgs:
                s = sers[c]
                row.append(f"r={s['replicas'][k]:>3} n={s['active_nodes'][k]:>2} sf={s['shortfall'][k]}")
            print(f"  {minutes[k]:>7} | {sers[cfgs[0]]['actual_demand'][k]:>8.2f} | " + " | ".join(f"{r:>26}" for r in row))

        print(f"\n  Action counts, {pattern.upper()} (mean over seeds {seeds}; events vs total replica delta):")
        agg = {c: {"events": [], "delta": []} for c in cfgs}
        for seed in seeds:
            tr = generate_pattern_trace(f"item2-{pattern}", pattern=pattern, duration_days=5, seed=seed)
            r = study.run_comparison(tr, output_dir=output_dir, configs_to_run=cfgs)
            for c in cfgs:
                agg[c]["events"].append(r["configurations"][c]["scaling_actions"])
                agg[c]["delta"].append(r["configurations"][c]["scaling_churn"])
        print(f"  {'Config':<28} | {'Action events (mean +/- ci)':<28} | {'Total replica delta (mean +/- ci)':<34}")
        print("  " + "-" * 100)
        for c in cfgs:
            ev, dv = compute_ci95(agg[c]["events"]), compute_ci95(agg[c]["delta"])
            print(f"  {c:<28} | {ev[0]:>8.1f} +/- {ev[2]:<6.1f}          | {dv[0]:>10.1f} +/- {dv[2]:<6.1f}")
            agg[c]["events_ci"] = ev
            agg[c]["delta_ci"] = dv
        out[pattern] = {"series": {c: sers[c] for c in cfgs}, "actions": agg}
    with open(os.path.join(output_dir, "item2_timeseries.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# C. Item 3: K_min sweep on low_load
# ---------------------------------------------------------------------------
def run_item3(seeds: List[int], output_dir: str) -> Dict:
    print("\n" + "=" * 118)
    print("  [C / ITEM 3] K_MIN RESILIENCE-FLOOR SWEEP ON LOW-LOAD TRACE (warm start excluded)")
    print("=" * 118)
    cfgs = ["cluster_autoscaler", "full_aegis_conformal", "oracle"]
    out = {}
    for k in (1, 2, 3):
        study = AblationStudy(min_active_nodes=k, wake_up_latency_steps=3)
        rec = {c: {m: [] for m in ("energy_kwh", "energy_idle_kwh", "capacity_shortfall_minutes", "mean_active_nodes")} for c in cfgs}
        for seed in seeds:
            trace = generate_pattern_trace("kmin-lowload", pattern="low_load", duration_days=5, seed=seed)
            res = study.run_comparison(trace, output_dir=output_dir, configs_to_run=cfgs)
            for c in cfgs:
                for m in rec[c]:
                    rec[c][m].append(res["configurations"][c][m])
        out[f"k_min={k}"] = {c: {m: compute_ci95(v) for m, v in rec[c].items()} for c in cfgs}
        print(f"\n  --- K_min = {k} (low_load trace, demand 1.5-5.6 cores) ---")
        print(f"  {'Config':<28} | {'Total kWh':<16} | {'Idle kWh':<16} | {'Mean active nodes':<19} | {'Shortfall':<13}")
        print("  " + "-" * 105)
        for c in cfgs:
            e, i, n, s = (out[f"k_min={k}"][c]["energy_kwh"], out[f"k_min={k}"][c]["energy_idle_kwh"],
                          out[f"k_min={k}"][c]["mean_active_nodes"], out[f"k_min={k}"][c]["capacity_shortfall_minutes"])
            print(f"  {c:<28} | {e[0]:>7.2f} +/-{e[2]:<6.2f} | {i[0]:>6.2f} +/-{i[2]:<6.2f} | {n[0]:>8.2f}            | {s[0]:>6.1f}")
    with open(os.path.join(output_dir, "item3_kmin_sweep.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# D. Item 4: Pareto frontier with oracle + matched-shortfall paired deltas
# ---------------------------------------------------------------------------
def run_item4(seeds: List[int], output_dir: str, patterns=("bursty", "structured_burst")) -> Dict:
    print("\n" + "=" * 118)
    print("  [D / ITEM 4] PARETO FRONTIER (Aegis tau sweep vs CA utilization sweep) + ORACLE POINT")
    print("  Paired per-seed energy deltas at matched shortfall via interpolation along each method's curve")
    print("=" * 118)

    aegis_taus = [0.50, 0.70, 0.80, 0.90, 0.95, 0.99]
    ca_utils = [0.80, 0.70, 0.60, 0.50]
    out = {}

    for pattern in patterns:
        study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
        # per-seed curves
        curves = {"aegis": {s: [] for s in seeds}, "ca": {s: [] for s in seeds}, "oracle": {s: [] for s in seeds}}
        for seed in seeds:
            trace = generate_pattern_trace("pareto", pattern=pattern, duration_days=5, seed=seed)
            for tau in aegis_taus:
                r = study.run_comparison(trace, output_dir=output_dir, quantile_tau=tau,
                                         configs_to_run=["full_aegis_conformal"])
                m = r["configurations"]["full_aegis_conformal"]
                curves["aegis"][seed].append((m["capacity_shortfall_minutes"], m["energy_kwh"]))
            for util in ca_utils:
                r = study.run_comparison(trace, output_dir=output_dir, hpa_target_util=util,
                                         configs_to_run=["cluster_autoscaler"])
                m = r["configurations"]["cluster_autoscaler"]
                curves["ca"][seed].append((m["capacity_shortfall_minutes"], m["energy_kwh"]))
            r = study.run_comparison(trace, output_dir=output_dir, configs_to_run=["oracle"])
            m = r["configurations"]["oracle"]
            curves["oracle"][seed].append((m["capacity_shortfall_minutes"], m["energy_kwh"]))

        agg = {}
        for meth in ("aegis", "ca", "oracle"):
            pts = curves[meth]
            n_points = len(next(iter(pts.values())))
            agg[meth] = []
            for i in range(n_points):
                e_list = [pts[s][i][1] for s in seeds]
                s_list = [pts[s][i][0] for s in seeds]
                e, s = compute_ci95(e_list), compute_ci95(s_list)
                agg[meth].append({"energy": e[0], "energy_ci95": e[2], "shortfall": s[0], "shortfall_ci95": s[2]})

        # Matched-shortfall paired deltas: target = per-seed CA default shortfall cannot be
        # interpolated per-seed against a common grid, so use each seed's own aegis default
        # (tau=0.90) shortfall as that seed's target, interpolate CA energy at it.
        diffs = []
        for seed in seeds:
            target_sf = curves["aegis"][seed][3][0]  # tau=0.90 is index 3
            ca_e = interp_energy_at_shortfall(curves["ca"][seed], target_sf)
            ae_e = curves["aegis"][seed][3][1]
            diffs.append(ae_e - ca_e)
        n = len(diffs)
        mean_d = float(np.mean(diffs))
        ci_d = float(stats.t.ppf(0.975, df=n - 1) * np.std(diffs, ddof=1) / np.sqrt(n)) if n > 1 else 0.0

        print(f"\n  PARETO TABLE: {pattern.upper()} (Poisson bursts)" if pattern == "bursty"
              else f"\n  PARETO TABLE: {pattern.upper()} (scheduled recurring bursts with jitter)")
        print(f"  {'Method/Setting':<26} | {'Energy kWh':<18} | {'Shortfall min':<18}")
        print("  " + "-" * 70)
        for i, pt in enumerate(agg["aegis"]):
            print(f"  aegis tau={aegis_taus[i]:<5.2f}        | {pt['energy']:>7.2f} +/-{pt['energy_ci95']:<6.2f} | {pt['shortfall']:>6.1f} +/-{pt['shortfall_ci95']:<5.1f}")
        for i, pt in enumerate(agg["ca"]):
            print(f"  CA util={int(ca_utils[i]*100):<3d}%           | {pt['energy']:>7.2f} +/-{pt['energy_ci95']:<6.2f} | {pt['shortfall']:>6.1f} +/-{pt['shortfall_ci95']:<5.1f}")
        for pt in agg["oracle"]:
            print(f"  {'oracle (perfect foresight)':<26} | {pt['energy']:>7.2f} +/-{pt['energy_ci95']:<6.2f} | {pt['shortfall']:>6.1f} +/-{pt['shortfall_ci95']:<5.1f}")
        print(f"\n  Paired energy delta (aegis tau=0.90 - CA interpolated at aegis's shortfall), per seed: "
              f"{[round(d,2) for d in diffs]}")
        print(f"    mean {mean_d:+.2f} kWh, 95% t-interval +/-{ci_d:.2f}, excludes 0: {bool(mean_d - ci_d > 0 or mean_d + ci_d < 0)}")

        out[pattern] = {
            "aegis": [{"tau": t, **pt} for t, pt in zip(aegis_taus, agg["aegis"])],
            "cluster_autoscaler": [{"util": u, **pt} for u, pt in zip(ca_utils, agg["ca"])],
            "oracle": agg["oracle"],
            "matched_shortfall_paired_energy_delta": {
                "per_seed": [round(d, 3) for d in diffs],
                "mean": round(mean_d, 3), "ci95": round(ci_d, 3),
                "excludes_zero": bool(mean_d - ci_d > 0 or mean_d + ci_d < 0),
            },
        }
    with open(os.path.join(output_dir, "pareto_frontier_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# E. Item 5: wake latency sweep
# ---------------------------------------------------------------------------
def run_item5(seeds: List[int], output_dir: str, patterns=("diurnal", "bursty")) -> Dict:
    print("\n" + "=" * 118)
    print("  [E / ITEM 5] NODE WAKE-LATENCY SWEEP (1, 3, 5, 10, 15 min) - 5 seeds")
    print("=" * 118)
    cfgs = ["cluster_autoscaler", "full_aegis_conformal", "oracle"]
    out = {}
    crossover = {}
    for pattern in patterns:
        crossover_pat = None
        for lat in (1, 3, 5, 10, 15):
            key = f"{pattern}@{lat}m"
            rec = {c: {m: [] for m in ("energy_kwh", "capacity_shortfall_minutes")} for c in cfgs}
            for seed in seeds:
                study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=lat)
                trace = generate_pattern_trace("wake", pattern=pattern, duration_days=5, seed=seed)
                res = study.run_comparison(trace, output_dir=output_dir, configs_to_run=cfgs)
                for c in cfgs:
                    for m in rec[c]:
                        rec[c][m].append(res["configurations"][c][m])
            out[key] = {c: {m: compute_ci95(v) for m, v in rec[c].items()} for c in cfgs}
            a, ca = out[key]["full_aegis_conformal"], out[key]["cluster_autoscaler"]
            beats = a["energy_kwh"][0] < ca["energy_kwh"][0] and a["capacity_shortfall_minutes"][0] <= ca["capacity_shortfall_minutes"][0]
            if beats and crossover_pat is None:
                crossover_pat = lat
            print(f"\n  --- {pattern}, wake latency = {lat} min (forecast lookahead capped at horizon H=10) ---")
            print(f"  {'Config':<28} | {'Energy kWh':<18} | {'Shortfall min':<15}")
            print("  " + "-" * 68)
            for c in cfgs:
                e, s = out[key][c]["energy_kwh"], out[key][c]["capacity_shortfall_minutes"]
                print(f"  {c:<28} | {e[0]:>7.2f} +/-{e[2]:<6.2f} | {s[0]:>6.1f}")
        crossover[pattern] = crossover_pat
        print(f"\n  => {pattern}: forecasting (full_aegis_conformal) first beats reactive CA on both energy and "
              f"shortfall at W = {crossover_pat if crossover_pat else 'never (within 1-15 min)'} min")
    with open(os.path.join(output_dir, "item5_wake_sweep.json"), "w") as f:
        json.dump({"table": out, "forecast_first_beats_reactive_at_wake_latency_min": crossover}, f, indent=2)
    return out


# ---------------------------------------------------------------------------
# F. Item 6: measured placement effect
# ---------------------------------------------------------------------------
def run_item6(seeds: List[int], output_dir: str) -> Dict:
    print("\n" + "=" * 118)
    print("  [F / ITEM 6] MEASURED PLACEMENT EFFECT - both arms with node power-down enabled")
    print("=" * 118)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    arms = {"no_placement (spread)": "forecast_plus_power_no_placement",
            "with_placement (pack)": "full_aegis"}
    rec = {a: {m: [] for m in ("energy_kwh", "energy_idle_kwh", "energy_dynamic_kwh",
                               "capacity_shortfall_minutes", "mean_active_nodes", "mean_nodes_needed",
                               "mean_allocated_replicas")} for a in arms}
    for seed in seeds:
        trace = generate_pattern_trace("place", pattern="diurnal", duration_days=5, seed=seed)
        res = study.run_comparison(trace, output_dir=output_dir, configs_to_run=list(arms.values()))
        for a, c in arms.items():
            for m in rec[a]:
                rec[a][m].append(res["configurations"][c][m])
    summary = {a: {m: compute_ci95(v) for m, v in rec[a].items()} for a in arms}

    print(f"\n  {'Arm':<28} | {'Nodes needed':<14} | {'Idle kWh':<18} | {'Dyn kWh':<18} | {'Total kWh':<18} | {'Shortfall':<10}")
    print("  " + "-" * 118)
    for a in arms:
        s = summary[a]
        print(f"  {a:<28} | {s['mean_nodes_needed'][0]:>6.2f}        | {s['energy_idle_kwh'][0]:>6.2f} +/-{s['energy_idle_kwh'][2]:<6.2f} | "
              f"{s['energy_dynamic_kwh'][0]:>6.2f} +/-{s['energy_dynamic_kwh'][2]:<6.2f} | {s['energy_kwh'][0]:>6.2f} +/-{s['energy_kwh'][2]:<6.2f} | {s['capacity_shortfall_minutes'][0]:>6.1f}")
    d_idle = paired_diff(rec["with_placement (pack)"]["energy_idle_kwh"], rec["no_placement (spread)"]["energy_idle_kwh"])
    d_tot = paired_diff(rec["with_placement (pack)"]["energy_kwh"], rec["no_placement (spread)"]["energy_kwh"])
    d_nodes = paired_diff(rec["with_placement (pack)"]["mean_nodes_needed"], rec["no_placement (spread)"]["mean_nodes_needed"])
    print(f"\n  Paired deltas (placement - no_placement): nodes {d_nodes['mean']:+.2f} +/-{d_nodes['ci95']:.2f}, "
          f"idle {d_idle['mean']:+.2f} +/-{d_idle['ci95']:.2f} kWh, total {d_tot['mean']:+.2f} +/-{d_tot['ci95']:.2f} kWh")

    # Mechanism: raw packer measurement across the replica range observed on this trace
    print("\n  Mechanism - measured bins for the heterogeneous pod mix (50% (0.6 CPU,1.2 GB) / 50% (0.2 CPU,3.5 GB)),")
    print("  kube-scheduler spreading vs first-fit-decreasing consolidation (no assumed pods/node):")
    print(f"  {'pods':>6} | {'spread nodes':>13} | {'pack nodes':>11} | {'pods/node spread':>17} | {'pods/node pack':>15}")
    print("  " + "-" * 72)
    pack_tbl = []
    for N in (6, 12, 24, 36, 48, 60, 72, 84, 96):
        sp, pk = study._pack_pods(N, opt=False), study._pack_pods(N, opt=True)
        pack_tbl.append({"pods": N, "spread_nodes": sp, "pack_nodes": pk})
        print(f"  {N:>6} | {sp:>13} | {pk:>11} | {N/sp:>17.2f} | {N/pk:>15.2f}")

    with open(os.path.join(output_dir, "item6_placement.json"), "w") as f:
        json.dump({"arms": summary, "paired_deltas": {"nodes": d_nodes, "idle_kwh": d_idle, "total_kwh": d_tot},
                   "packer_measurement": pack_tbl}, f, indent=2)
    return {"arms": summary}


# ---------------------------------------------------------------------------
# G. Item 7: calibration study
# ---------------------------------------------------------------------------
def run_item7(seeds: List[int], output_dir: str) -> Dict:
    print("\n" + "=" * 118)
    print("  [G / ITEM 7] CONFORMAL CALIBRATION: SINGLE-DAY vs ROLLING RECALIBRATION (target p90 coverage 0.9000)")
    print("  Causality: rolling residual window at decision step t is [t-H-W, t-H) - outcomes delayed by horizon H;")
    print("  enforced and unit-tested in tests/unit/test_ablation_evaluation.py::test_rolling_recalibration_uses_only_horizon_delayed_outcomes")
    print("=" * 118)
    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    per_seed = {}
    for seed in seeds:
        trace = generate_pattern_trace("calib", pattern="bursty", duration_days=5, seed=seed)
        r_single = study.run_comparison(trace, output_dir=output_dir, rolling_recalibration=False,
                                        configs_to_run=["full_aegis_conformal"])
        r_roll = study.run_comparison(trace, output_dir=output_dir, rolling_recalibration=True,
                                      configs_to_run=["full_aegis_conformal"])
        per_seed[seed] = {
            "uncalibrated": r_single["forecaster_metrics"]["calibration_fraction_below_p90_uncalibrated"],
            "single_day": r_single["forecaster_metrics"]["calibration_fraction_below_p90_conformal"],
            "rolling": r_roll["forecaster_metrics"]["calibration_fraction_below_p90_conformal"],
            "rolling_interval_coverage_pct": r_roll["forecaster_metrics"]["interval_coverage_conformal_pct"],
        }
    print(f"\n  {'Seed':>6} | {'raw p90':>9} | {'single-day':>11} | {'rolling':>9}")
    print("  " + "-" * 48)
    for seed in seeds:
        v = per_seed[seed]
        print(f"  {seed:>6} | {v['uncalibrated']:>9.4f} | {v['single_day']:>11.4f} | {v['rolling']:>9.4f}")
    for key in ("uncalibrated", "single_day", "rolling"):
        vals = [per_seed[s][key] for s in seeds]
        arr = np.array(vals, dtype=float)
        mean = float(np.mean(arr))
        if len(arr) > 1:
            ci = float(stats.t.ppf(0.975, df=len(arr) - 1) * np.std(arr, ddof=1) / np.sqrt(len(arr)))
        else:
            ci = 0.0
        print(f"  mean {key:<12}: {mean:.4f} +/- {ci:.4f} (std {np.std(arr, ddof=1):.4f})")
    with open(os.path.join(output_dir, "item7_calibration.json"), "w") as f:
        json.dump({"per_seed": per_seed}, f, indent=2)
    return per_seed


# ---------------------------------------------------------------------------
# H. Item 8: flash crowd with HPA-realistic scale-up + step-limit sweep
# ---------------------------------------------------------------------------
def run_item8(seeds: List[int], output_dir: str) -> Dict:
    print("\n" + "=" * 118)
    print("  [H / ITEM 8] FLASH CROWD: HPA-REALISTIC SCALE-UP (max(4 pods, 100%) per 15s aggregated to 1 min)")
    print("  vs legacy fixed caps; CA, stock HPA, Aegis conformal and oracle in one table")
    print("=" * 118)
    cfgs = ["stock_hpa", "cluster_autoscaler", "full_aegis_conformal", "oracle"]

    # Main table with the realistic policy (max_scale_step=None default)
    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    rec = {c: {m: [] for m in ("energy_kwh", "capacity_shortfall_minutes", "scaling_actions", "scaling_churn")} for c in cfgs}
    for seed in seeds:
        trace = generate_pattern_trace("fc", pattern="flash_crowd", duration_days=5, seed=seed)
        res = study.run_comparison(trace, output_dir=output_dir, configs_to_run=cfgs)
        for c in cfgs:
            for m in rec[c]:
                rec[c][m].append(res["configurations"][c][m])
    main = {c: {m: compute_ci95(v) for m, v in rec[c].items()} for c in cfgs}
    print(f"\n  {'Config':<28} | {'Energy kWh':<18} | {'Shortfall min':<17} | {'Action events':<16} | {'Replica delta':<15}")
    print("  " + "-" * 100)
    for c in cfgs:
        e, s, a, ch = main[c]["energy_kwh"], main[c]["capacity_shortfall_minutes"], main[c]["scaling_actions"], main[c]["scaling_churn"]
        print(f"  {c:<28} | {e[0]:>7.2f} +/-{e[2]:<6.2f} | {s[0]:>6.1f} +/-{s[2]:<5.1f} | {a[0]:>6.1f} +/-{a[2]:<5.1f} | {ch[0]:>6.1f}")

    # Step-limit sweep (cap applied per 1-min decision step)
    print(f"\n  Scale-up step-limit sweep on flash_crowd (full_aegis_conformal; 'HPA' = max(16, current)/min):")
    print(f"  {'max step':<10} | {'Shortfall min':<17} | {'Action events':<16} | {'Replica delta':<15} | {'Energy kWh':<15}")
    print("  " + "-" * 85)
    sweep = {}
    for cap, label in [(1, "1 pod/min"), (2, "2 pods/min"), (4, "4 pods/min"), (8, "8 pods/min"),
                       (10, "10 pods/min (old)"), (None, "HPA-realistic")]:
        st = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3, max_scale_step=cap)
        s_l, a_l, c_l, e_l = [], [], [], []
        for seed in seeds:
            trace = generate_pattern_trace("fc", pattern="flash_crowd", duration_days=5, seed=seed)
            res = st.run_comparison(trace, output_dir=output_dir, configs_to_run=["full_aegis_conformal"])
            m = res["configurations"]["full_aegis_conformal"]
            s_l.append(m["capacity_shortfall_minutes"]); a_l.append(m["scaling_actions"])
            c_l.append(m["scaling_churn"]); e_l.append(m["energy_kwh"])
        s, a, c, e = compute_ci95(s_l), compute_ci95(a_l), compute_ci95(c_l), compute_ci95(e_l)
        sweep[label] = {"shortfall": s, "actions": a, "churn": c, "energy": e}
        print(f"  {label:<18} | {s[0]:>6.1f} +/-{s[2]:<5.1f} | {a[0]:>6.1f} +/-{a[2]:<5.1f} | {c[0]:>6.1f}          | {e[0]:>6.2f}")

    with open(os.path.join(output_dir, "item8_flash_crowd.json"), "w") as f:
        json.dump({"main": main, "step_limit_sweep": sweep}, f, indent=2)
    return {"main": main, "sweep": sweep}


def main():
    parser = argparse.ArgumentParser(description="Aegis frozen-simulator IEEE benchmark suite.")
    parser.add_argument("--seeds", type=str, default="42,101,202,303,404")
    parser.add_argument("--patterns", type=str, default="diurnal,steady,bursty,structured_burst,flash_crowd")
    parser.add_argument("--output", type=str, default="eval")
    parser.add_argument("--sections", type=str, default="A,B,C,D,E,F,G,H",
                        help="Comma-separated sections to run (A=primary, B=item2, ...)")
    args = parser.parse_args()

    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    sections = {s.strip().upper() for s in args.sections.split(",")}
    os.makedirs(args.output, exist_ok=True)

    print("=" * 118)
    print("  AEGIS FROZEN-SIMULATOR IEEE EVALUATION SUITE")
    print(f"  Seeds: {seeds} | Patterns: {patterns}")
    print("  Training data: seed 9999 pooled 6-pattern pool (independent of test seeds), cores units")
    print("  Calibration: trace day 1 (steps 0-1440); test: steps 1440+; warm start 60 min excluded from all metrics")
    print("=" * 118)

    if "A" in sections:
        run_primary(seeds, patterns, args.output)
    if "B" in sections:
        run_item2(seeds, args.output, seed_for_series=42)
    if "C" in sections:
        run_item3(seeds, args.output)
    if "D" in sections:
        run_item4(seeds, args.output)
    if "E" in sections:
        run_item5(seeds, args.output)
    if "F" in sections:
        run_item6(seeds, args.output)
    if "G" in sections:
        run_item7(seeds, args.output)
    if "H" in sections:
        run_item8(seeds, args.output)

    print("\nSUITE COMPLETE. All JSON artifacts under eval/.")


if __name__ == "__main__":
    main()
