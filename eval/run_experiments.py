"""
Executable script for Phase 9: Evaluation (HPA vs Aegis + Ablation).
Replays telemetry traces, evaluates all 4 configurations, and outputs comparative benchmarks.
"""

import os
import sys
import json
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from ml.evaluation.ablation import AblationStudy


def main():
    trace_path = "datasets/processed_sample_trace.parquet"
    if not os.path.exists(trace_path):
        trace_path = "datasets/sample_trace.parquet"

    print(f"Loading benchmark trace from: {trace_path}")
    df = pd.read_parquet(trace_path)
    # Evaluate over a 1440-minute (24-hour) sample slice
    eval_slice = df.iloc[:1440].copy()

    print(f"Executing 24-hour ablation study across {len(eval_slice)} time steps...")
    study = AblationStudy()
    results = study.run_comparison(eval_slice, output_dir="eval")

    print("\n" + "=" * 70)
    print("                 AEGIS ABLATION BENCHMARK RESULTS")
    print("=" * 70)
    print(f"{'Configuration':<22} | {'Energy (kWh)':<12} | {'SLO Violations':<15} | {'Churn':<8}")
    print("-" * 70)
    for name, m in results["configurations"].items():
        print(f"{name:<22} | {m['energy_kwh']:<12.2f} | {m['slo_violations']:<15} | {m['scaling_churn']:<8}")
    print("-" * 70)
    imp = results["improvements"]
    print(f"Energy Reduction vs HPA : {imp['energy_savings_vs_hpa_pct']}%")
    print(f"SLO Breach Reduction    : {imp['slo_violation_reduction_pct']}%")
    print(f"Scaling Churn Reduction : {imp['churn_reduction_pct']}%")
    print("=" * 70)
    print("Artifacts successfully generated at 'eval/ablation_results.json'")


if __name__ == "__main__":
    main()
