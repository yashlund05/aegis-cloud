"""
Unit tests for Phase 9: Evaluation and Ablation Benchmark framework.
"""

import pandas as pd
import numpy as np
from ml.evaluation.ablation import AblationStudy


def test_ablation_study_execution_and_metrics():
    # Generate synthetic 100-step trace
    np.random.seed(42)
    timestamps = pd.date_range("2026-01-01", periods=100, freq="1min")
    cpu_vals = np.random.uniform(0.5, 3.5, size=100)
    df = pd.DataFrame({"timestamp": timestamps, "cpu_usage": cpu_vals})

    study = AblationStudy()
    results = study.run_comparison(df, output_dir="eval")

    assert "configurations" in results
    assert "improvements" in results

    configs = results["configurations"]
    assert "stock_hpa" in configs
    assert "forecast_only" in configs
    assert "forecast_placement" in configs
    assert "full_aegis" in configs

    # Verify metric fields exist
    for cfg_name, metrics in configs.items():
        assert "energy_kwh" in metrics
        assert "slo_violations" in metrics
        assert "scaling_churn" in metrics
        assert metrics["energy_kwh"] > 0.0

    # Full Aegis must have lower energy consumption than stock HPA
    assert configs["full_aegis"]["energy_kwh"] < configs["stock_hpa"]["energy_kwh"]
