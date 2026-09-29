"""
Headline-number provenance report for the frozen Aegis benchmark.

Prints every headline number with its source JSON file and the command that
produced it. Run after eval/run_experiments.py completes:

    python eval/summarize_results.py
"""

import json
import os
import sys

EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
CMD = "python eval/run_experiments.py --seeds 42,101,202,303,404 --output eval"


def load(name):
    path = os.path.join(EVAL, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def fmt_ci(entry):
    if isinstance(entry, dict) and "mean" in entry:
        return f"{entry['mean']:.2f} +/- {entry.get('ci95', 0.0):.2f}"
    return str(entry)


def main():
    print("=" * 112)
    print("  HEADLINE NUMBERS WITH PROVENANCE (frozen simulator)")
    print("=" * 112)

    # Primary benchmark
    mp = load("multi_pattern_ablation_results.json")
    if mp:
        print(f"\n[Primary multi-pattern benchmark]  source: eval/multi_pattern_ablation_results.json | cmd: {CMD}")
        for pat in mp:
            cfgs = mp[pat]["configurations"]
            ca, ae, orc = cfgs["cluster_autoscaler"], cfgs["full_aegis_conformal"], cfgs["oracle"]
            pd_ = mp[pat]["paired_vs_cluster_autoscaler"]
            print(f"  {pat:<17} CA energy {fmt_ci(ca['energy_kwh'])} kWh | aegis-conformal {fmt_ci(ae['energy_kwh'])} kWh | "
                  f"oracle {fmt_ci(orc['energy_kwh'])} kWh")
            print(f"  {'':<17} shortfall: CA {fmt_ci(ca['capacity_shortfall_minutes'])} min | aegis {fmt_ci(ae['capacity_shortfall_minutes'])} min | "
                  f"oracle {fmt_ci(orc['capacity_shortfall_minutes'])} min")
            print(f"  {'':<17} paired energy delta (aegis-CA): {pd_['energy_vs_ca']['mean']:+.2f} +/- {pd_['energy_vs_ca']['ci95']:.2f} kWh; "
                  f"paired shortfall delta: {pd_['shortfall_vs_ca']['mean']:+.1f} +/- {pd_['shortfall_vs_ca']['ci95']:.1f} min")

    # Item 2
    it2 = load("item2_timeseries.json")
    if it2:
        print(f"\n[Item 2: action decomposition]  source: eval/item2_timeseries.json | cmd: {CMD} (section B)")
        for pat in it2:
            for cfg, a in it2[pat]["actions"].items():
                print(f"  {pat:<10} {cfg:<26} events {a['events_ci'][0]:>6.1f} +/- {a['events_ci'][2]:.1f} | "
                      f"total replica delta {a['delta_ci'][0]:>7.1f} +/- {a['delta_ci'][2]:.1f}")

    # Item 3
    it3 = load("item3_kmin_sweep.json")
    if it3:
        print(f"\n[Item 3: K_min floor sweep on low_load]  source: eval/item3_kmin_sweep.json | cmd: {CMD} (section C)")
        for k, row in it3.items():
            ae = row["full_aegis_conformal"]
            print(f"  {k:<10} aegis-conformal: energy {fmt_ci(ae['energy_kwh'])} kWh, idle {fmt_ci(ae['energy_idle_kwh'])} kWh, "
                  f"mean active nodes {fmt_ci(ae['mean_active_nodes'])}, shortfall {fmt_ci(ae['capacity_shortfall_minutes'])} min")

    # Item 4
    it4 = load("pareto_frontier_results.json")
    if it4:
        print(f"\n[Item 4: Pareto + matched-shortfall pairing]  source: eval/pareto_frontier_results.json | cmd: {CMD} (section D)")
        for pat in it4:
            d = it4[pat]["matched_shortfall_paired_energy_delta"]
            orc = it4[pat]["oracle"][0]
            print(f"  {pat:<17} oracle point: energy {orc['energy']:.2f} kWh, shortfall {orc['shortfall']:.1f} min")
            print(f"  {'':<17} paired energy delta (aegis tau=0.90 - CA interp @ aegis shortfall): "
                  f"{d['mean']:+.2f} +/- {d['ci95']:.2f} kWh (excludes 0: {d['excludes_zero']}); per-seed {d['per_seed']}")

    # Item 5
    it5 = load("item5_wake_sweep.json")
    if it5:
        print(f"\n[Item 5: wake latency sweep]  source: eval/item5_wake_sweep.json | cmd: {CMD} (section E)")
        print(f"  forecast first beats reactive CA at W: {it5['forecast_first_beats_reactive_at_wake_latency_min']}")
        for key, row in it5["table"].items():
            ae, ca = row["full_aegis_conformal"], row["cluster_autoscaler"]
            print(f"  {key:<14} aegis {ae['energy_kwh'][0]:>7.2f} kWh / sf {ae['capacity_shortfall_minutes'][0]:>5.1f} min | "
                  f"CA {ca['energy_kwh'][0]:>7.2f} kWh / sf {ca['capacity_shortfall_minutes'][0]:>5.1f} min")

    # Item 6
    it6 = load("item6_placement.json")
    if it6:
        print(f"\n[Item 6: measured placement effect]  source: eval/item6_placement.json | cmd: {CMD} (section F)")
        for arm, s in it6["arms"].items():
            print(f"  {arm:<28} nodes {fmt_ci(s['mean_nodes_needed'])}, idle {fmt_ci(s['energy_idle_kwh'])} kWh, "
                  f"dynamic {fmt_ci(s['energy_dynamic_kwh'])} kWh, total {fmt_ci(s['energy_kwh'])} kWh")
        d = it6["paired_deltas"]
        print(f"  paired deltas (placement - spread): nodes {d['nodes']['mean']:+.2f} +/- {d['nodes']['ci95']:.2f}, "
              f"idle {d['idle_kwh']['mean']:+.2f} +/- {d['idle_kwh']['ci95']:.2f} kWh, total {d['total_kwh']['mean']:+.2f} +/- {d['total_kwh']['ci95']:.2f} kWh")

    # Item 7
    it7 = load("item7_calibration.json")
    if it7:
        print(f"\n[Item 7: calibration per-seed coverage]  source: eval/item7_calibration.json | cmd: {CMD} (section G)")
        for seed, v in it7["per_seed"].items():
            print(f"  seed {seed}: raw p90 {v['uncalibrated']:.4f} | single-day {v['single_day']:.4f} | rolling {v['rolling']:.4f}")

    # Item 8
    it8 = load("item8_flash_crowd.json")
    if it8:
        print(f"\n[Item 8: flash crowd, HPA-realistic scale-up]  source: eval/item8_flash_crowd.json | cmd: {CMD} (section H)")
        for cfg, m in it8["main"].items():
            print(f"  {cfg:<26} energy {fmt_ci(m['energy_kwh'])} kWh | shortfall {fmt_ci(m['capacity_shortfall_minutes'])} min | "
                  f"events {fmt_ci(m['scaling_actions'])} | replica delta {fmt_ci(m['scaling_churn'])}")
        print("  step-limit sweep (full_aegis_conformal):")
        for label, s in it8["step_limit_sweep"].items():
            print(f"    {label:<22} shortfall {fmt_ci(s['shortfall'])} min | events {fmt_ci(s['actions'])} | "
                  f"replica delta {fmt_ci(s['churn'])} | energy {fmt_ci(s['energy'])} kWh")

    # Item 9: freeze stamp from ablation_results.json
    ab = load("ablation_results.json")
    if ab:
        print(f"\n[Item 9: freeze stamp]  source: eval/ablation_results.json (written by every run_comparison call)")
        print(f"  simulator_config_hash : {ab.get('simulator_config_hash')}")
        print(f"  git_commit           : {ab.get('git_state', {}).get('git_commit')}")
        print(f"  git_dirty_files      : {ab.get('git_state', {}).get('git_dirty_files')}")
        print(f"  simulator_config     : {json.dumps(ab.get('simulator_config', {}), sort_keys=True)}")

    print("\nReproduce everything with: " + CMD)
    print("Unit tests (incl. >95% served-demand and recalibration causality): python -m pytest tests/unit/test_ablation_evaluation.py -q")


if __name__ == "__main__":
    main()
