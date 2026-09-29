"""
Unit tests for Phase 9: Evaluation and Ablation Benchmark framework.
"""

import numpy as np
import pandas as pd
import pytest

from datasets.generate_sample_traces import generate_workload_trace
from datasets.workload_patterns import generate_pattern_trace
from ml.evaluation.ablation import AblationStudy, rolling_conformal_adjustment


def test_ablation_study_execution_and_metrics(tmp_path):
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
    results = study.run_comparison(df, output_dir=str(tmp_path))

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


def test_served_demand_fraction_on_steady_trace(tmp_path):
    """Every non-oracle config must serve >95% of demand on a steady trace."""
    trace = generate_pattern_trace("steady-test", pattern="steady", duration_days=2, seed=42)
    study = AblationStudy()
    results = study.run_comparison(trace, output_dir=str(tmp_path))
    configs = results["configurations"]
    total_steps = results["trace_steps"]

    non_oracle = [c for c in configs if c != "oracle"]
    for cfg_name in non_oracle:
        m = configs[cfg_name]
        served_fraction = 1.0 - (m["capacity_shortfall_minutes"] / max(1, total_steps))
        assert served_fraction > 0.95, f"{cfg_name} served fraction {served_fraction:.4f} <= 0.95"


def test_served_demand_fraction_on_diurnal_trace(tmp_path):
    """Test that on a diurnal trace, forecast_only and full_aegis serve >95% of demand."""
    trace = generate_pattern_trace("diurnal-test", pattern="diurnal", duration_days=2, seed=42)
    study = AblationStudy()
    results = study.run_comparison(
        trace, output_dir=str(tmp_path), configs_to_run=["forecast_only", "full_aegis"]
    )
    configs = results["configurations"]
    total_steps = results["trace_steps"]
    for cfg_name in ["forecast_only", "full_aegis"]:
        m = configs[cfg_name]
        served_fraction = 1.0 - (m["capacity_shortfall_minutes"] / max(1, total_steps))
        assert served_fraction > 0.95, f"{cfg_name} served fraction {served_fraction:.4f} <= 0.95 on diurnal trace"


def _make_synthetic_stream(n=3000, seed=7):
    """Deterministic demand stream with known scale and heteroscedastic spikes."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    y = 12.0 + 6.0 * np.sin(2 * np.pi * t / 1440.0) + rng.normal(0, 0.5, n)
    p50 = y + rng.normal(0, 0.4, n)
    p90 = p50 + 1.0 + rng.uniform(0, 0.5, n)
    p10 = p50 - 1.0 - rng.uniform(0, 0.5, n)
    return y, p90, p10


def test_rolling_recalibration_uses_only_horizon_delayed_outcomes():
    """
    Causality audit: residuals used at decision step t_abs may only come from
    steps <= t_abs - H. Perturbing every *unobservable* outcome (s > t_abs - H,
    including all later steps) must not change any conformal prediction.
    """
    y, p90, p10 = _make_synthetic_stream()
    n_cal, horizon, window, tau = 1440, 10, 1440, 0.90

    base_p90c, base_p10c = rolling_conformal_adjustment(y, p90, p10, n_cal, horizon, window, tau)

    # Corrupt all outcomes strictly after (t_abs - H) for each test step, one probe step at a time.
    for probe_idx in [0, 1, 9, 10, 37, 500, 1000]:
        t_abs = n_cal + probe_idx
        y_corrupt = y.copy()
        y_corrupt[t_abs - horizon + 1:] = 9999.0  # unobservable window + all future
        p90_corrupt, p10_corrupt = rolling_conformal_adjustment(
            y_corrupt, p90, p10, n_cal, horizon, window, tau
        )
        assert abs(p90_corrupt[probe_idx] - base_p90c[probe_idx]) < 1e-9, (
            f"q_hat at t_abs={t_abs} changed when corrupting outcomes > t_abs-H (leak!)"
        )
        assert abs(p10_corrupt[probe_idx] - base_p10c[probe_idx]) < 1e-9

    # Sanity: perturbing an *observable, included* outcome (last index is t_abs - H - 1,
    # since the residual window [t_obs - W, t_obs) is exclusive of t_obs) must change the estimate.
    t_abs = n_cal + 500
    y_perturb = y.copy()
    y_perturb[t_abs - horizon - 1] += 100.0
    p90_perturb, _ = rolling_conformal_adjustment(y_perturb, p90, p10, n_cal, horizon, window, tau)
    assert abs(p90_perturb[500] - base_p90c[500]) > 1e-6


def test_forecast_config_pre_wake_respects_wake_latency(tmp_path):
    """With H >= W, forecast-driven node sizing must wake nodes so that they are
    active no later than the Oracle (both face the same W-step boot latency)."""
    trace = generate_pattern_trace("prewake", pattern="diurnal", duration_days=2, seed=42)
    study = AblationStudy(wake_up_latency_steps=3)
    res = study.run_comparison(
        trace,
        output_dir=str(tmp_path),
        configs_to_run=["full_aegis_conformal", "oracle"],
        return_series=True,
    )
    ae = res["configurations"]["full_aegis_conformal"]["series"]
    orc = res["configurations"]["oracle"]["series"]
    # Both must track the morning ramp: when demand exceeds 60% of its max, the
    # forecast config must already have at least half the oracle's active nodes.
    demand = np.array(ae["actual_demand"])
    thr = 0.6 * demand.max()
    ramp = np.where(demand > thr)[0]
    if len(ramp):
        first = ramp[0]
        assert ae["active_nodes"][first] >= 0.5 * orc["active_nodes"][first]
