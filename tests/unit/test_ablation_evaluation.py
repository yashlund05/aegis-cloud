"""
Unit tests for Phase 9: Evaluation and Ablation Benchmark framework.
"""

import pandas as pd
import numpy as np
from datasets.generate_sample_traces import generate_workload_trace
from ml.evaluation.ablation import AblationStudy


def test_ablation_study_execution_and_metrics():
    # Generate synthetic 120-step trace with required columns
    trace = generate_workload_trace(
        workload_id="test-service",
        start_time=pd.Timestamp("2026-01-01"),
        duration_days=1,
        freq="1min",
        seed=42,
    )
    df = trace.iloc[:120].copy()

    study = AblationStudy()
    results = study.run_comparison(df, output_dir="eval")

    assert "configurations" in results
    assert "improvements" in results
    assert "forecaster_metrics" in results

    configs = results["configurations"]
    expected_configs = [
        "stock_hpa",
        "reactive_hpa_plus_consolidation",
        "forecast_only",
        "forecast_placement",
        "forecast_plus_power_no_placement",
        "full_aegis",
        "oracle",
    ]
    for cfg in expected_configs:
        assert cfg in configs
        m = configs[cfg]
        assert "energy_kwh" in m
        assert "capacity_shortfall_minutes" in m
        assert "scaling_actions" in m
        assert m["energy_kwh"] > 0.0

    # Forecaster metrics verification
    fm = results["forecaster_metrics"]
    assert "wmape_p50" in fm
    assert "pinball_loss_p10" in fm
    assert "pinball_loss_p50" in fm
    assert "pinball_loss_p90" in fm
    assert "interval_coverage_p10_p90_pct" in fm
