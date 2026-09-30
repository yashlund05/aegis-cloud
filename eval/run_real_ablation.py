"""
Part 2 - Component ablation of full_aegis_conformal on the 68-core real set
(Azure Functions 2019 apps), using the frozen simulator via call-time switches
only (config_name + forecast-stream selection). No frozen file is modified.

Ablation ladder, each row removes one component from full_aegis_conformal
(forecast + conformal + placement + node power-down):

  full                       full_aegis_conformal          all components
  minus conformal            full_aegis                    raw (uncalibrated) p90 stream
  minus placement            forecast_plus_power_no_placement + conformal stream
                             (spreading instead of bin-packing; power-down kept)
  minus power-down           forecast_placement + conformal stream
                             (all 20 nodes always on; placement kept)
  minus forecast             reactive_hpa_plus_consolidation
                             reactive HPA control + node power-down; the reactive
                             controller consumes past actuals, so conformal and
                             placement leave with the forecast by construction

Usage: python eval/run_real_ablation.py
"""

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath("."))

from eval.run_real_trace import prepare_streams, git_state  # noqa: E402
from ml.evaluation.ablation import AblationStudy  # noqa: E402

OUTPUT_JSON = "eval/real_ablation_results.json"
HORIZON = 10

ROWS = [
    ("full (all components)", "full_aegis_conformal", "static_conformal"),
    ("minus conformal", "full_aegis", "raw"),
    ("minus placement", "forecast_plus_power_no_placement", "static_conformal"),
    ("minus power-down", "forecast_placement", "static_conformal"),
    ("minus forecast (reactive+consolidation)", "reactive_hpa_plus_consolidation", "raw"),
]


def main():
    paths = sorted(glob.glob("datasets/real_*.parquet"))
    if not paths:
        sys.exit("No datasets/real_*.parquet found - run datasets/load_real_trace.py first.")

    print("=" * 112)
    print("  COMPONENT ABLATION of full_aegis_conformal on the 68-core real-trace set (Azure Functions 2019)")
    print("  frozen simulator, call-time switches only: config_name + forecast stream")
    print("  streams: static_conformal = tau 0.90 offset from the 15% calibration segment; raw = uncalibrated p90")
    print("=" * 112)

    study = AblationStudy(model_dir="ml/models/artifacts_real", min_active_nodes=2, wake_up_latency_steps=3)
    results = {"apps": {}}

    for path in paths:
        streams = prepare_streams(path)
        app = streams["app"]
        a = streams["_arrays"]
        stream_for = {"static_conformal": a["p90_static_test"], "raw": a["p90_raw_full"][a["test_mask"]]}

        print(f"\n  === {app} (test demand mean {streams['test_demand_cores']['mean']} / "
              f"max {streams['test_demand_cores']['max']} cores) ===")
        print(f"  {'row':<42} | {'energy kWh':>10} | {'shortfall min':>13} | {'events':>7} | {'replica delta':>13}")
        print("  " + "-" * 100)
        rows = {}
        for label, cfg, stream_kind in ROWS:
            res = study._simulate_configuration(
                actual_demands=a["y_test"], actual_mems=a["mem_test"],
                p90_forecasts=stream_for[stream_kind], config_name=cfg,
                forecast_horizon_minutes=HORIZON,
            )
            rows[label] = {"config": cfg, "stream": stream_kind,
                           "energy_kwh": res["energy_kwh"],
                           "capacity_shortfall_minutes": res["capacity_shortfall_minutes"],
                           "scaling_actions": res["scaling_actions"],
                           "scaling_churn": res["scaling_churn"]}
            print(f"  {label:<42} | {res['energy_kwh']:>10.2f} | {res['capacity_shortfall_minutes']:>13.1f} | "
                  f"{res['scaling_actions']:>7.0f} | {res['scaling_churn']:>13.0f}")
        results["apps"][app] = rows

    # component costs, averaged across apps (energy deltas vs the full system)
    print("\n  COMPONENT COST (mean over apps; energy kWh and shortfall min attributable to each component)")
    comps = ["minus conformal", "minus placement", "minus power-down", "minus forecast (reactive+consolidation)"]
    print(f"  {'component removed':<42} | {'dE vs full':>10} | {'d short vs full':>15} | {'d events vs full':>16}")
    print("  " + "-" * 92)
    comp_summary = {}
    for comp in comps:
        d_e = float(np.mean([results["apps"][a][comp]["energy_kwh"] - results["apps"][a]["full (all components)"]["energy_kwh"]
                             for a in results["apps"]]))
        d_s = float(np.mean([results["apps"][a][comp]["capacity_shortfall_minutes"] - results["apps"][a]["full (all components)"]["capacity_shortfall_minutes"]
                             for a in results["apps"]]))
        d_v = float(np.mean([results["apps"][a][comp]["scaling_actions"] - results["apps"][a]["full (all components)"]["scaling_actions"]
                             for a in results["apps"]]))
        comp_summary[comp] = {"d_energy_kwh": round(d_e, 3), "d_shortfall_min": round(d_s, 3),
                              "d_events": round(d_v, 3)}
        print(f"  {comp:<42} | {d_e:>+10.2f} | {d_s:>+15.1f} | {d_v:>+16.1f}")

    results["ablation_rows"] = [{"label": l, "config": c, "stream": s} for l, c, s in ROWS]
    results["component_cost_mean_over_apps"] = comp_summary
    results["note"] = ("minus-placement and minus-power-down keep the static conformal stream to isolate the "
                       "component; minus-forecast is necessarily fully reactive (reactive_hpa_plus_consolidation). "
                       "The simulator is deterministic given a fixed trace, so numbers are exact, not sampled.")
    results["trace"] = "Azure Functions 2019, 68-core eligibility set (see eval/real_trace_results.json)"
    results["protocol"] = {"split": "60/15/25 per workload", "horizon_minutes": HORIZON,
                           "conformal_tau": 0.90, "models_dir": "ml/models/artifacts_real"}
    results["simulator_config_hash"] = AblationStudy().compute_config_hash(results["protocol"])
    results["git"] = git_state()
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  wrote {OUTPUT_JSON} (git: {results['git']['commit'][:8]}, tag: {results['git']['tag_at_head']}, "
          f"config hash: {results['simulator_config_hash'][:16]}...)")


if __name__ == "__main__":
    main()
