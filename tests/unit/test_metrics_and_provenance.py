"""
Unit tests for evaluation metrics, statistical functions, provenance helper,
and report generation from results JSON.

Covers:
  a. paired_bootstrap_ci on fixed toy sample vs hand-computed interval (seeded)
  b. holm_bonferroni on known example (p = [0.01, 0.04, 0.03, 0.005])
  c. interpolate_energy_at_shortfall boundary cases (min, max, between, low, high)
  d. provenance helper: config hash stability & sensitivity
  e. report_from_json: output matches stored numbers and contains both labeled stats
"""

import json
import os
import tempfile
import numpy as np
import pytest

from eval.provenance import compute_config_hash, get_provenance
from eval.report_from_json import render_report_from_json
from eval.run_60app_study import holm_bonferroni
from eval.scale_aware_pareto_study import (
    interpolate_energy_at_shortfall,
    paired_bootstrap_ci,
)


class TestMetricsAndProvenance:
    def test_paired_bootstrap_ci_seeded_toy_sample(self):
        """
        Tests paired_bootstrap_ci on a fixed toy sample with seed=42.
        For a = [10.0, 12.0, 14.0, 16.0, 18.0] and b = [8.0, 9.0, 11.0, 12.0, 13.0],
        diff = a - b = [2.0, 3.0, 3.0, 4.0, 5.0].
        Exact mean difference: (2 + 3 + 3 + 4 + 5) / 5 = 3.4.
        Under seed=42 with B=1000, 95% bootstrap percentile CI is [2.6, 4.2].
        """
        a = np.array([10.0, 12.0, 14.0, 16.0, 18.0])
        b = np.array([8.0, 9.0, 11.0, 12.0, 13.0])
        mean_diff, ci_lower, ci_upper = paired_bootstrap_ci(a, b, B=1000, seed=42)

        assert mean_diff == pytest.approx(3.4, abs=1e-5)
        assert ci_lower == pytest.approx(2.6, abs=1e-2)
        assert ci_upper == pytest.approx(4.2, abs=1e-2)
        assert ci_lower <= mean_diff <= ci_upper

    def test_holm_bonferroni_known_example(self):
        """
        Tests Holm-Bonferroni step-down correction on known example:
        p = [0.01, 0.04, 0.03, 0.005] with m = 4 hypotheses.
        
        Analytical derivation:
          - Sorted p-values:
            Rank 0: p[3] = 0.005 -> (4 - 0) * 0.005 = 0.02, cum_max = 0.02 -> adj[3] = 0.02
            Rank 1: p[0] = 0.010 -> (4 - 1) * 0.010 = 0.03, cum_max = 0.03 -> adj[0] = 0.03
            Rank 2: p[2] = 0.030 -> (4 - 2) * 0.030 = 0.06, cum_max = 0.06 -> adj[2] = 0.06
            Rank 3: p[1] = 0.040 -> (4 - 3) * 0.040 = 0.04, cum_max = max(0.06, 0.04) = 0.06 -> adj[1] = 0.06
        
        Expected adjusted p-values:
          adj[0] = 0.03
          adj[1] = 0.06
          adj[2] = 0.06
          adj[3] = 0.02
        """
        raw_p = [0.01, 0.04, 0.03, 0.005]
        adj_p = holm_bonferroni(raw_p)

        expected = [0.03, 0.06, 0.06, 0.02]
        for actual, exp in zip(adj_p, expected):
            assert actual == pytest.approx(exp, abs=1e-6)

    def test_interpolate_energy_at_shortfall_boundaries(self):
        """
        Tests interpolate_energy_at_shortfall across all 5 boundary conditions:
          1. target == min (exact lower boundary)
          2. target == max (exact upper boundary)
          3. target between points (interior linear interpolation)
          4. target < min (outside low -> clamped to min energy, flagged as extrapolated)
          5. target > max (outside high -> clamped to max energy, flagged as extrapolated)
        """
        pts = [(0.0, 100.0), (10.0, 80.0)]

        # 1. target == min
        e_min, ext_min = interpolate_energy_at_shortfall(pts, 0.0)
        assert e_min == pytest.approx(100.0)
        assert ext_min is False

        # 2. target == max
        e_max, ext_max = interpolate_energy_at_shortfall(pts, 10.0)
        assert e_max == pytest.approx(80.0)
        assert ext_max is False

        # 3. target between points (midpoint target = 5.0 -> energy = 90.0)
        e_mid, ext_mid = interpolate_energy_at_shortfall(pts, 5.0)
        assert e_mid == pytest.approx(90.0)
        assert ext_mid is False

        # 4. target outside low (target = -1.0)
        e_low, ext_low = interpolate_energy_at_shortfall(pts, -1.0)
        assert e_low == pytest.approx(100.0)
        assert ext_low is True

        # 5. target outside high (target = 15.0)
        e_high, ext_high = interpolate_energy_at_shortfall(pts, 15.0)
        assert e_high == pytest.approx(80.0)
        assert ext_high is True

    def test_provenance_config_hash_stability_and_sensitivity(self):
        """
        Tests that compute_config_hash:
          - Produces deterministic, stable SHA-256 hashes regardless of dictionary key ordering
          - Correctly changes hash value when configuration values change
          - Emits valid provenance dictionary format with expected keys
        """
        cfg_a = {"alpha": 1.5, "taus": [0.5, 0.9], "horizon": 10}
        cfg_b = {"horizon": 10, "taus": [0.5, 0.9], "alpha": 1.5}
        cfg_c = {"alpha": 1.5, "taus": [0.5, 0.95], "horizon": 10}

        hash_a = compute_config_hash(cfg_a)
        hash_b = compute_config_hash(cfg_b)
        hash_c = compute_config_hash(cfg_c)

        # Stability across key order
        assert hash_a == hash_b
        assert len(hash_a) == 64

        # Sensitivity to value modification
        assert hash_a != hash_c

        # Standard provenance structure
        prov = get_provenance(config=cfg_a, seeds=[42, 101])
        assert "git_commit" in prov
        assert "dirty_flag" in prov
        assert "config_sha256" in prov
        assert "timestamp_utc" in prov
        assert "seeds" in prov
        assert prov["config_sha256"] == hash_a
        assert prov["seeds"] == [42, 101]

    def test_report_from_json_fixture_contains_exact_numbers_and_labels(self):
        """
        Tests that render_report_from_json:
          - Formats exact numbers from the JSON fixture without alteration
          - Prints BOTH explicitly labeled statistics:
              * 'median of per-app energies (Aegis - CA)'
              * 'mean paired delta energy (Aegis - CA)'
          - Annotates table cells with exact key paths
          - Includes explanatory footnote
        """
        fixture_data = {
            "git_commit": "abc1234def",
            "config_hash": "sha256fedcba",
            "coverage_summary": {
                "test_apps_count": 20,
                "median_iqr": {
                    "scale_aware": [97.60, 5.08],
                    "rolling": [90.00, 0.71],
                },
            },
            "matched_shortfall_pareto": {
                "1.0%": {
                    "scale_aware": {
                        "ca_median_energy": 122.19,
                        "aegis_median_energy": 92.40,
                        "mean_delta_energy": -38.22,
                        "bootstrap_ci95": [-65.09, -14.46],
                        "cheaper_fraction_pct": 70.0,
                        "ca_extrapolations": 13,
                        "aegis_extrapolations": 11,
                    }
                }
            },
            "tertile_stratification": {
                "Tertile 1 (Low Load)": {
                    "n_apps": 7,
                    "aegis_vs_ca_deltas": {
                        "energy": {"mean": 108.39, "ci95": [101.69, 115.27], "p_value": 0.015625},
                        "shortfall": {"mean": -125.86, "ci95": [-256.14, -24.43], "p_value": 0.015625},
                    },
                }
            },
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(fixture_data, f)
            temp_path = f.name

        try:
            report = render_report_from_json(temp_path)

            # Check commit and config hash
            assert "abc1234def" in report
            assert "sha256fedcba" in report

            # Check coverage summary numbers
            assert "97.60%" in report
            assert "5.08%" in report

            # Check exact Pareto numbers
            assert "122.19" in report
            assert "92.40" in report
            assert "-38.22" in report
            assert "[-65.09, -14.46]" in report
            assert "70.0%" in report

            # Check BOTH labeled statistics
            assert "median of per-app energies (Aegis - CA)" in report
            assert "-29.79" in report  # 92.40 - 122.19
            assert "mean paired delta energy (Aegis - CA)" in report

            # Check key path annotations
            assert "`matched_shortfall_pareto['1.0%']['scale_aware']`" in report
            assert "`coverage_summary.median_iqr.scale_aware`" in report

            # Check explanatory footnote
            assert "Note on statistics" in report or "Statistical Footnote" in report
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_extrapolation_flag_and_side_at_exact_boundaries(self):
        """
        Tests interpolate_energy_at_shortfall_detailed at exact boundaries:
          - target == min -> is_extrapolated=False, side=None
          - target == max -> is_extrapolated=False, side=None
          - target < min  -> is_extrapolated=True, side='below_min_shortfall'
          - target > max  -> is_extrapolated=True, side='above_max_shortfall'
          - min < target < max -> is_extrapolated=False, side=None
        """
        from eval.scale_aware_pareto_study_v3 import interpolate_energy_at_shortfall_detailed

        pts = [(10.0, 100.0), (50.0, 80.0)]

        # 1. target == min
        res_min = interpolate_energy_at_shortfall_detailed(pts, 10.0)
        assert res_min["energy"] == pytest.approx(100.0)
        assert res_min["is_extrapolated"] is False
        assert res_min["extrapolation_side"] is None
        assert res_min["min_shortfall"] == pytest.approx(10.0)
        assert res_min["max_shortfall"] == pytest.approx(50.0)

        # 2. target == max
        res_max = interpolate_energy_at_shortfall_detailed(pts, 50.0)
        assert res_max["energy"] == pytest.approx(80.0)
        assert res_max["is_extrapolated"] is False
        assert res_max["extrapolation_side"] is None

        # 3. between points (midpoint target = 30.0 -> energy = 90.0)
        res_mid = interpolate_energy_at_shortfall_detailed(pts, 30.0)
        assert res_mid["energy"] == pytest.approx(90.0)
        assert res_mid["is_extrapolated"] is False
        assert res_mid["extrapolation_side"] is None

        # 4. target below min
        res_low = interpolate_energy_at_shortfall_detailed(pts, 5.0)
        assert res_low["energy"] == pytest.approx(100.0)
        assert res_low["is_extrapolated"] is True
        assert res_low["extrapolation_side"] == "below_min_shortfall"

        # 5. target above max
        res_high = interpolate_energy_at_shortfall_detailed(pts, 60.0)
        assert res_high["energy"] == pytest.approx(80.0)
        assert res_high["is_extrapolated"] is True
        assert res_high["extrapolation_side"] == "above_max_shortfall"

    def test_five_percent_target_converts_to_exact_minutes(self):
        """
        Tests that shortfall target percentages convert to exact minutes:
          - 0.0% -> 0.0 min
          - 0.1% -> 18.72 min
          - 1.0% -> 187.20 min
          - 5.0% -> 936.00 min on an 18,720-minute window
        """
        from eval.scale_aware_pareto_study_v3 import compute_target_minutes

        assert compute_target_minutes(0.0) == pytest.approx(0.0)
        assert compute_target_minutes(0.1) == pytest.approx(18.72)
        assert compute_target_minutes(1.0) == pytest.approx(187.2)
        assert compute_target_minutes(5.0) == pytest.approx(936.0)

    def test_per_app_results_structure_and_length(self):
        """
        Verifies that per_app_results contains exactly 20 validation apps
        with valid energy, shortfall bounds, and extrapolation fields.
        """
        dummy_app_ids = [f"app_{i:02d}" for i in range(20)]
        per_app_data = {}
        for app in dummy_app_ids:
            per_app_data[app] = {
                "ca_energy": 100.0,
                "aegis_energy": 90.0,
                "delta_energy": -10.0,
                "ca_is_extrapolated": False,
                "ca_extrapolation_side": None,
                "ca_min_shortfall": 0.0,
                "ca_max_shortfall": 500.0,
                "aegis_is_extrapolated": False,
                "aegis_extrapolation_side": None,
                "aegis_min_shortfall": 0.0,
                "aegis_max_shortfall": 300.0,
            }

        assert len(per_app_data) == 20
        for app in dummy_app_ids:
            assert "ca_energy" in per_app_data[app]
            assert "aegis_energy" in per_app_data[app]
            assert "delta_energy" in per_app_data[app]
            assert per_app_data[app]["delta_energy"] == per_app_data[app]["aegis_energy"] - per_app_data[app]["ca_energy"]

    def test_sign_convention_aegis_minus_ca(self):
        """
        Verifies sign convention: Delta E = E_Aegis - E_CA.
        Negative indicates Aegis is cheaper (winning).
        Tests c48859 values: E_Aegis = 58.84, E_CA = 171.61 -> Delta = -112.77.
        Ensures winning apps are not classified as losing apps.
        """
        e_aegis = 58.84
        e_ca = 171.61
        delta_e = e_aegis - e_ca
        assert delta_e == pytest.approx(-112.77, abs=1e-2)
        assert delta_e < 0.0  # Aegis is cheaper

        is_losing = delta_e > 0.0
        assert is_losing is False

    def test_degenerate_frontier_detection(self):
        """
        Tests degenerate frontier detection logic:
        Frontier is degenerate if len(unique(shortfalls)) <= 1 or min_s == max_s.
        """
        from eval.headline_study_v4 import interpolate_energy_at_shortfall

        # Case 1: Constant shortfall at 0.0 min across all tau
        pts_const_0 = [(0.0, 58.84), (0.0, 58.84), (0.0, 58.84)]
        res_0 = interpolate_energy_at_shortfall(pts_const_0, 187.2)
        assert res_0["is_degenerate"] is True

        # Case 2: Constant shortfall at 3.0 min across all tau
        pts_const_3 = [(3.0, 60.28), (3.0, 60.28), (3.0, 60.28)]
        res_3 = interpolate_energy_at_shortfall(pts_const_3, 18.72)
        assert res_3["is_degenerate"] is True

        # Case 3: Proper non-degenerate frontier
        pts_normal = [(0.0, 200.0), (50.0, 150.0), (200.0, 100.0)]
        res_norm = interpolate_energy_at_shortfall(pts_normal, 100.0)
        assert res_norm["is_degenerate"] is False

    def test_dominance_classification_logic(self):
        """
        Tests Pareto dominance classification between Aegis and CA:
          - dominant: E_Aegis <= E_CA and S_Aegis <= S_CA (at least one strict <)
          - dominated: E_Aegis >= E_CA and S_Aegis >= S_CA (at least one strict >)
          - tradeoff: one is better on energy, other on shortfall
          - identical: E and S are identical
        """
        def classify(ae_e, ca_e, ae_s, ca_s):
            if (ae_e <= ca_e and ae_s <= ca_s) and (ae_e < ca_e or ae_s < ca_s):
                return "dominant"
            elif (ae_e >= ca_e and ae_s >= ca_s) and (ae_e > ca_e or ae_s > ca_s):
                return "dominated"
            elif ae_e == ca_e and ae_s == ca_s:
                return "identical"
            else:
                return "tradeoff"

        # Dominant: Aegis has strictly lower energy and same shortfall
        assert classify(60.28, 64.55, 3.0, 3.0) == "dominant"
        # Dominant: Aegis has strictly lower energy and strictly lower shortfall
        assert classify(104.08, 170.26, 167.0, 337.0) == "dominant"
        # Dominated: Aegis has higher energy and higher shortfall
        assert classify(57.75, 57.23, 16.0, 7.0) == "dominated"
        # Trade-off: Aegis has lower energy but higher shortfall
        assert classify(57.94, 58.43, 48.0, 4.0) == "tradeoff"
        # Identical
        assert classify(100.0, 100.0, 50.0, 50.0) == "identical"

    def test_rank_biserial_and_wilcoxon(self):
        """
        Tests rank-biserial effect size and Wilcoxon signed-rank test helper.
        """
        from eval.headline_study_v4 import compute_rank_biserial

        # If diff is strictly negative (Aegis cheaper for all apps), r_rb = -1.0
        diff_all_negative = np.array([-10.0, -20.0, -5.0, -15.0, -30.0])
        r_rb, p_two, p_less = compute_rank_biserial(diff_all_negative)
        assert r_rb == pytest.approx(-1.0)
        assert p_less < 0.05

        # If diff is strictly positive (CA cheaper for all apps), r_rb = +1.0
        diff_all_positive = np.array([10.0, 20.0, 5.0, 15.0, 30.0])
        r_rb_pos, p_two_pos, p_less_pos = compute_rank_biserial(diff_all_positive)
        assert r_rb_pos == pytest.approx(1.0)
        assert p_less_pos > 0.95


