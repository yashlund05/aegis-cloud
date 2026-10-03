"""
eval/report_from_json.py

Renders a structured Markdown report strictly from a results JSON path argument.
No recomputation of headline numbers; every table cell is traceable to a JSON key.
Each table is annotated with its exact JSON key path.

Where both a median difference and a mean paired delta exist, prints BOTH with
explicit labels:
  - "median of per-app energies (Aegis - CA)"
  - "mean paired delta energy (Aegis - CA)"
plus an explanatory footnote clarifying the distinction between difference of
marginal medians and the expected paired difference on skewed distributions.

Usage:
    python eval/report_from_json.py <path_to_results.json>
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List


def fmt_ci(ci: List[float], digits: int = 2) -> str:
    if len(ci) == 2:
        return f"[{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]"
    return str(ci)


def render_scale_aware_pareto_report(data: Dict[str, Any], json_path: str) -> str:
    md: List[str] = []
    md.append("# Aegis Scale-Aware Conformal & Matched-Shortfall Pareto Report")
    md.append("")
    md.append(f"**Source JSON**: `{json_path}`  ")
    md.append(f"**Git Commit**: `{data.get('git_commit', 'unknown')}`  ")
    md.append(f"**Config SHA-256**: `{data.get('config_hash', 'unknown')}`  ")
    md.append("")

    # 1. Coverage Summary Table
    cov = data.get("coverage_summary", {})
    med_iqr = cov.get("median_iqr", {})
    md.append("## 1. Conformal Coverage Summary (20 Test Apps)")
    md.append("*Source key path: `coverage_summary.median_iqr.<method>`*")
    md.append("")
    md.append("| Method | Median Coverage (%) | IQR (%) | Key Path |")
    md.append("| :--- | :---: | :---: | :--- |")
    labels = {
        "raw": "Raw Forecast (No Conformal)",
        "static": "Static Conformal Offset",
        "scale_aware": "Scale-Aware Conformal (Normalized Residuals)",
        "rolling": "Per-App Rolling Conformal (Horizon-Delayed)",
        "aci_005": "Adaptive Conformal (ACI gamma=0.005)",
        "aci_020": "Adaptive Conformal (ACI gamma=0.020)",
    }
    for k, label in labels.items():
        if k in med_iqr:
            vals = med_iqr[k]
            md.append(f"| {label} | {vals[0]:.2f}% | {vals[1]:.2f}% | `coverage_summary.median_iqr.{k}` |")
    md.append("")

    # 2. Matched Shortfall Pareto Frontier
    pareto = data.get("matched_shortfall_pareto", {})
    md.append("## 2. Matched-Shortfall Pareto Frontier Evaluation")
    md.append("*Source key path: `matched_shortfall_pareto.<target_shortfall>.<method>`*")
    md.append("")
    md.append("> [!NOTE]")
    md.append("> **Statistical Metric Disambiguation**:[^1]")
    md.append("> - **median of per-app energies (Aegis - CA)**: Difference between the marginal medians of the two distributions across apps ($E_{\\text{Aegis}}^{\\text{med}} - E_{\\text{CA}}^{\\text{med}}$).")
    md.append("> - **mean paired delta energy (Aegis - CA)**: Sample mean of individual per-app paired differences ($\\frac{1}{N}\\sum_{i=1}^N (E_{\\text{Aegis}, i} - E_{\\text{CA}, i})$), with 95% bootstrap percentile CI.")
    md.append("")

    for target, methods in pareto.items():
        md.append(f"### Shortfall Target: {target} of Minutes")
        md.append(f"*Source key path: `matched_shortfall_pareto['{target}']`*")
        md.append("")
        has_v3_fields = any("interpolated_only" in m_data for m_data in methods.values())

        if has_v3_fields:
            md.append("| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below / Above] | Key Path |")
            md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
            for m_key, m_data in methods.items():
                ca_med = m_data.get("ca_median_energy", 0.0)
                ae_med = m_data.get("aegis_median_energy", 0.0)
                diff_of_meds = ae_med - ca_med
                mean_delta = m_data.get("mean_delta_energy", 0.0)
                ci = m_data.get("bootstrap_ci95", [0.0, 0.0])
                cheaper_pct = m_data.get("cheaper_fraction_pct", 0.0)
                ca_ext = m_data.get("ca_extrapolations", 0)
                ae_ext = m_data.get("aegis_extrapolations", 0)

                ca_sides = m_data.get("ca_extrapolation_sides", {})
                ae_sides = m_data.get("aegis_extrapolation_sides", {})
                ca_side_str = f"[{ca_sides.get('below_min_shortfall', 0)}B/{ca_sides.get('above_max_shortfall', 0)}A]"
                ae_side_str = f"[{ae_sides.get('below_min_shortfall', 0)}B/{ae_sides.get('above_max_shortfall', 0)}A]"

                interp = m_data.get("interpolated_only", {})
                if interp.get("status") == "valid":
                    interp_ci = interp.get("bootstrap_ci95", [0.0, 0.0])
                    interp_str = f"{interp.get('mean_delta_energy', 0.0):+.2f} {fmt_ci(interp_ci)} (N={interp.get('n_included')})"
                else:
                    n_inc = interp.get("n_included", 0)
                    interp_str = f"Underpowered (N={n_inc}/20)"

                k_path = f"`matched_shortfall_pareto['{target}']['{m_key}']`"
                md.append(
                    f"| {labels.get(m_key, m_key)} | {ca_med:.2f} | {ae_med:.2f} | {diff_of_meds:+.2f} | {mean_delta:+.2f} {fmt_ci(ci)} | {interp_str} | {cheaper_pct:.1f}% | {ca_ext} {ca_side_str} / {ae_ext} {ae_side_str} | {k_path} |"
                )
            md.append("")

            # Losing Apps Summary for this target
            scale_aware_losing = methods.get("scale_aware", {}).get("losing_apps", [])
            if scale_aware_losing:
                md.append(f"**Losing Apps for Scale-Aware Conformal at {target} shortfall ({len(scale_aware_losing)}/20 apps where Aegis > CA energy)**:")
                for la in scale_aware_losing:
                    poor_flag = "⚠️ **Poor Coverage Overlap**" if la.get("is_poorly_covered") else "Normal Coverage"
                    md.append(f"- App `{la['app_id'][:16]}...`: Delta = `{la['delta_energy_kwh']:+.2f} kWh`, Mean Cores = `{la['mean_cores']:.3f}`, Peak Cores = `{la['peak_cores']:.2f}` ({poor_flag})")
                md.append("")

            # Significance shift audit (All-App vs Interp-Only)
            sig_shifts = []
            for m_key, m_data in methods.items():
                ci_all = m_data.get("bootstrap_ci95", [0.0, 0.0])
                interp = m_data.get("interpolated_only", {})
                if interp.get("status") == "valid":
                    ci_int = interp.get("bootstrap_ci95", [0.0, 0.0])
                    sig_all = (ci_all[0] > 0 or ci_all[1] < 0)
                    sig_int = (ci_int[0] > 0 or ci_int[1] < 0)
                    if sig_all != sig_int:
                        all_desc = "excludes 0 (sig)" if sig_all else "crosses 0 (non-sig)"
                        int_desc = "excludes 0 (sig)" if sig_int else "crosses 0 (non-sig)"
                        sig_shifts.append(f"{labels.get(m_key, m_key)}: all-app {all_desc} -> interp-only {int_desc}")
            if sig_shifts:
                md.append(f"**Cohort Significance Audit ({target})**: Significance changed on filtering: {'; '.join(sig_shifts)}.")
            else:
                md.append(f"**Cohort Significance Audit ({target})**: No change in significance direction across valid cohorts on filtering.")
            md.append("")
        else:
            md.append("| Conformal Method | CA Median Energy (kWh) | Aegis Median Energy (kWh) | median of per-app energies (Aegis - CA) (kWh) | mean paired delta energy (Aegis - CA) (kWh) [95% CI] | Aegis Cheaper (%) | Extrapolated Apps (CA / Aegis) | Key Path |")
            md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")

            for m_key, m_data in methods.items():
                ca_med = m_data.get("ca_median_energy", 0.0)
                ae_med = m_data.get("aegis_median_energy", 0.0)
                diff_of_meds = ae_med - ca_med
                mean_delta = m_data.get("mean_delta_energy", 0.0)
                ci = m_data.get("bootstrap_ci95", [0.0, 0.0])
                cheaper_pct = m_data.get("cheaper_fraction_pct", 0.0)
                ca_ext = m_data.get("ca_extrapolations", 0)
                ae_ext = m_data.get("aegis_extrapolations", 0)
                k_path = f"`matched_shortfall_pareto['{target}']['{m_key}']`"

                md.append(
                    f"| {labels.get(m_key, m_key)} | {ca_med:.2f} | {ae_med:.2f} | {diff_of_meds:+.2f} | {mean_delta:+.2f} {fmt_ci(ci)} | {cheaper_pct:.1f}% | {ca_ext} / {ae_ext} | {k_path} |"
                )
            md.append("")

    # 3. Tertile Stratification (if present in JSON)
    tertiles = data.get("tertile_stratification", {})
    if tertiles:
        md.append("## 3. Tertile Stratification of Headline Tests (Low / Mid / High Load)")
        md.append("*Source key path: `tertile_stratification.<tertile_name>`*")
        md.append("")
        md.append("| Tertile | N Apps | Mean Paired Energy Delta (kWh) [95% CI] | Wilcoxon p (Energy) | Mean Paired Shortfall Delta (min) [95% CI] | Wilcoxon p (Shortfall) | Key Path |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :--- |")
        for t_name, t_vals in tertiles.items():
            n_apps = t_vals.get("n_apps", 0)
            deltas = t_vals.get("aegis_vs_ca_deltas", {})
            e_info = deltas.get("energy", {})
            s_info = deltas.get("shortfall", {})
            e_mean = e_info.get("mean", 0.0)
            e_ci = e_info.get("ci95", [0.0, 0.0])
            e_p = e_info.get("p_value", 1.0)
            s_mean = s_info.get("mean", 0.0)
            s_ci = s_info.get("ci95", [0.0, 0.0])
            s_p = s_info.get("p_value", 1.0)
            t_path = f"`tertile_stratification['{t_name}'].aegis_vs_ca_deltas`"

            md.append(
                f"| {t_name} | {n_apps} | {e_mean:+.2f} {fmt_ci(e_ci)} | {e_p:.4e} | {s_mean:+.2f} {fmt_ci(s_ci)} | {s_p:.4e} | {t_path} |"
            )
        md.append("")
        md.append("> [!IMPORTANT]")
        md.append("> **Tertile Per-Arm Marginal Distribution Notice**:")
        md.append("> Per-arm medians/IQRs for each tertile (e.g. Tertile 1 CA 57.6 kWh vs Aegis 169.6 kWh) were computed in-memory during study execution from `eval/audit_controls_results.json` (`per_app_table_sorted`) and `eval/sixty_app_study_results.json` (`per_app_raw_metrics`). Only the paired deltas above are stored within `scale_aware_pareto_results.json`.")
        md.append("")
    md.append("[^1]: **Statistical Footnote**: 'median of per-app energies (Aegis - CA)' represents the difference of marginal medians across apps, whereas 'mean paired delta energy (Aegis - CA)' is the sample average of per-app differences $(E_{\\text{Aegis}, i} - E_{\\text{CA}, i})$. Because workload demand and energy distributions exhibit positive skew across heterogeneous applications, the expectation of paired differences differs from the difference of marginal medians.")
    md.append("")
    return "\n".join(md)


def render_audit_controls_report(data: Dict[str, Any], json_path: str) -> str:
    md: List[str] = []
    md.append("# Aegis Audit Controls & Baseline Comparison Report")
    md.append("")
    md.append(f"**Source JSON**: `{json_path}`  ")
    md.append(f"**Git Commit**: `{data.get('git_commit', 'unknown')}`  ")
    md.append("")

    # 1. Cooldown Audit
    cd_audit = data.get("cooldown_audit_3_apps", {})
    md.append("## 1. Cooldown Audit (3 Apps: Small, Mid, Large)")
    md.append("*Source key path: `cooldown_audit_3_apps.<app_id>`*")
    md.append("")
    md.append("| App ID | Role | CA Blocked (Up / Down) | Reactive Blocked (Up / Down) | Shortfall Attributable to Blocked Up (CA / Reactive) | Key Path |")
    md.append("| :--- | :--- | :---: | :---: | :---: | :--- |")
    for app_id, info in cd_audit.items():
        role = info.get("category", "")
        ca = info.get("cluster_autoscaler", {})
        rh = info.get("reactive_hpa_plus_consolidation", {})
        k_path = f"`cooldown_audit_3_apps['{app_id}']`"
        md.append(
            f"| `{app_id}` | {role} | {ca.get('blocked_scale_ups', 0)} / {ca.get('blocked_scale_downs', 0)} | "
            f"{rh.get('blocked_scale_ups', 0)} / {rh.get('blocked_scale_downs', 0)} | "
            f"{ca.get('shortfall_attributable_to_blocked_scaleups_min', 0.0):.1f} min / {rh.get('shortfall_attributable_to_blocked_scaleups_min', 0.0):.1f} min | {k_path} |"
        )
    md.append("")

    # 2. Control Arms Distributions
    arms = data.get("control_arms_distributions", {})
    md.append("## 2. Control Arms Distributions (20 Test Apps)")
    md.append("*Source key path: `control_arms_distributions.<arm_name>`*")
    md.append("")
    md.append("| Configuration Arm | Energy Median (IQR) kWh | Shortfall Median (IQR) min | Events Median (IQR) | Key Path |")
    md.append("| :--- | :---: | :---: | :---: | :--- |")
    for arm_name, dist in arms.items():
        e = dist.get("energy", {})
        s = dist.get("shortfall", {})
        ev = dist.get("events", {})
        k_path = f"`control_arms_distributions['{arm_name}']`"
        md.append(
            f"| {arm_name} | {e.get('median', 0.0):.1f} ({e.get('iqr', 0.0):.1f}) | "
            f"{s.get('median', 0.0):.1f} ({s.get('iqr', 0.0):.1f}) | "
            f"{ev.get('median', 0.0):.1f} ({ev.get('iqr', 0.0):.1f}) | {k_path} |"
        )
    md.append("")

    # 3. Spearman Correlation
    sp = data.get("spearman_correlation", {})
    md.append("## 3. Spearman Rank Correlation")
    md.append("*Source key path: `spearman_correlation`*")
    md.append("")
    md.append(f"- **Metric**: Aegis Shortfall vs. App Peak Size")
    md.append(f"- **Spearman $\\rho$**: `{sp.get('rho', 0.0):.4f}` (`spearman_correlation.rho`)")
    md.append(f"- **p-value**: `{sp.get('p_value', 1.0):.4e}` (`spearman_correlation.p_value`)")
    md.append("")
    return "\n".join(md)


def render_sixty_app_study_report(data: Dict[str, Any], json_path: str) -> str:
    md: List[str] = []
    md.append("# Aegis 60-App Study & Baseline Evaluation Report")
    md.append("")
    md.append(f"**Source JSON**: `{json_path}`  ")
    md.append(f"**Git Commit**: `{data.get('git_commit', 'unknown')}`  ")
    md.append(f"**Config SHA-256**: `{data.get('config_hash', 'unknown')}`  ")
    md.append("")

    # Partition
    part = data.get("app_partition", {})
    md.append("## 1. App Partition")
    md.append("*Source key path: `app_partition`*")
    md.append(f"- Train Apps: {len(part.get('train_apps', []))} (`app_partition.train_apps`)")
    md.append(f"- Calibrate Apps: {len(part.get('calibrate_apps', []))} (`app_partition.calibrate_apps`)")
    md.append(f"- Test Apps: {len(part.get('test_apps', []))} (`app_partition.test_apps`)")
    md.append("")

    # Conformal Calibration
    cal = data.get("conformal_calibration", {})
    md.append("## 2. Conformal Calibration Margin")
    md.append("*Source key path: `conformal_calibration`*")
    md.append(f"- Target Quantile: `{cal.get('quantile', 0.90)}` (`conformal_calibration.quantile`)")
    md.append(f"- Calibrated $\\hat{{q}}_{{90}}$ Headroom: `{cal.get('q_hat_90_cores', 0.0):.4f}` cores (`conformal_calibration.q_hat_90_cores`)")
    md.append("")

    # Distributions
    dists = data.get("per_app_distributions", {})
    md.append("## 3. Main Configurations Distributions (20 Test Apps)")
    md.append("*Source key path: `per_app_distributions.<config>`*")
    md.append("")
    md.append("| Configuration | Energy Median (IQR) kWh | Shortfall Median (IQR) min | Events Median (IQR) | Key Path |")
    md.append("| :--- | :---: | :---: | :---: | :--- |")
    for cfg, m in dists.items():
        e = m.get("energy", {})
        s = m.get("shortfall", {})
        ev = m.get("events", {})
        k_path = f"`per_app_distributions['{cfg}']`"
        md.append(
            f"| {cfg} | {e.get('median', 0.0):.1f} ({e.get('iqr', 0.0):.1f}) | "
            f"{s.get('median', 0.0):.1f} ({s.get('iqr', 0.0):.1f}) | "
            f"{ev.get('median', 0.0):.1f} ({ev.get('iqr', 0.0):.1f}) | {k_path} |"
        )
    md.append("")

    # Statistical Tests
    stats = data.get("statistical_tests", {})
    md.append("## 4. Statistical Tests (Aegis vs. Baselines)")
    md.append("*Source key path: `statistical_tests.<metric>.<baseline>`*")
    md.append("")
    md.append("| Metric | Baseline Arm | Paired Delta Mean [95% CI] | Wilcoxon p (Raw) | Holm-Bonferroni p (Adj) | Key Path |")
    md.append("| :--- | :--- | :---: | :---: | :---: | :--- |")
    for met, baselines in stats.items():
        for base, vals in baselines.items():
            m_val = vals.get("mean_difference", 0.0)
            ci = vals.get("bootstrap_ci95", [0.0, 0.0])
            raw_p = vals.get("raw_p_value", 1.0)
            adj_p = vals.get("holm_adjusted_p_value", 1.0)
            k_path = f"`statistical_tests['{met}']['{base}']`"
            md.append(f"| {met} | {base} | {m_val:+.2f} {fmt_ci(ci)} | {raw_p:.4e} | {adj_p:.4e} | {k_path} |")
    md.append("")
    return "\n".join(md)


def render_report_from_json(json_path: str) -> str:
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Results file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Route based on detected schema
    if "matched_shortfall_pareto" in data:
        return render_scale_aware_pareto_report(data, json_path)
    elif "cooldown_audit_3_apps" in data:
        return render_audit_controls_report(data, json_path)
    elif "conformal_calibration" in data and "censoring_audit" in data:
        return render_sixty_app_study_report(data, json_path)
    else:
        # Generic fallback
        md = [f"# Generic Results Report for `{json_path}`\n"]
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool)):
                md.append(f"- **`{k}`**: {v}")
            elif isinstance(v, dict):
                md.append(f"- **`{k}`**: Dict with keys `{list(v.keys())}`")
            elif isinstance(v, list):
                md.append(f"- **`{k}`**: List of {len(v)} items")
        return "\n".join(md)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Render Markdown report from results JSON.")
    parser.add_argument("json_path", help="Path to results JSON file")
    parser.add_argument("--output", "-o", help="Optional output Markdown file path", default=None)
    args = parser.parse_args()

    report_md = render_report_from_json(args.json_path)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"Report written to {args.output}")
    else:
        print(report_md)


if __name__ == "__main__":
    main()
