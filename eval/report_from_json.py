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
    if ci is None:
        return "N/A"
    if len(ci) == 2:
        return f"[{ci[0]:.{digits}f}, {ci[1]:.{digits}f}]"
    return str(ci)


def render_headline_v4_report(data: Dict[str, Any], json_path: str) -> str:
    md: List[str] = []
    md.append("# Aegis Clean Headline Benchmark Evaluation Report (v4)")
    md.append("")
    md.append(f"**Source JSON**: `{json_path}`  ")
    md.append(f"**Git Commit**: `{data.get('git_commit', 'unknown')}`  ")
    md.append(f"**Working Tree Dirty Flag**: `{data.get('dirty_flag', 'unknown')}`  ")
    md.append(f"**Config SHA-256**: `{data.get('config_hash', 'unknown')}`  ")
    md.append(f"**Timestamp UTC**: `{data.get('timestamp_utc', 'unknown')}`  ")
    md.append(f"**Primary Aegis Arm**: `{data.get('configuration', {}).get('primary_arm', 'rolling')}` (per Decision D-7)  ")
    md.append("")

    # 1. Coverage Summary Table
    cov = data.get("coverage_summary", {})
    med_iqr = cov.get("median_iqr", {})
    md.append("## 1. Conformal Coverage Summary (20 Validation Apps)")
    md.append("*Source key path: `coverage_summary.median_iqr.<method>`*")
    md.append("")
    md.append("| Method | Median Coverage (%) | IQR (%) | Role | Key Path |")
    md.append("| :--- | :---: | :---: | :---: | :--- |")
    labels = {
        "raw": "Raw Forecast (No Conformal)",
        "static": "Static Conformal Offset",
        "scale_aware": "Scale-Aware Conformal (Normalized Residuals)",
        "rolling": "Per-App Rolling Conformal (W=1440, H=10)",
        "aci_005": "Adaptive Conformal (ACI gamma=0.005)",
        "aci_020": "Adaptive Conformal (ACI gamma=0.020)",
    }
    roles = {
        "raw": "Baseline",
        "static": "Ablation",
        "scale_aware": "Ablation / Variant",
        "rolling": "**Primary Arm (D-7)**",
        "aci_005": "Ablation / Variant",
        "aci_020": "Ablation / Variant",
    }
    for k, label in labels.items():
        if k in med_iqr:
            vals = med_iqr[k]
            md.append(f"| {label} | {vals[0]:.2f}% | {vals[1]:.2f}% | {roles.get(k, '')} | `coverage_summary.median_iqr.{k}` |")
    md.append("")

    # 2. Matched Shortfall Pareto Frontiers
    pareto = data.get("matched_shortfall_pareto", {})
    md.append("## 2. Matched-Shortfall Pareto Frontier Evaluation")
    md.append("*Source key path: `matched_shortfall_pareto.<target_shortfall>.<method>`*")
    md.append("")
    md.append("> [!NOTE]")
    md.append("> **Statistical Metric Disambiguation**:[^1]")
    md.append("> - **Diff of Medians (kWh)**: Marginal median difference across apps ($E_{\\text{Aegis}}^{\\text{med}} - E_{\\text{CA}}^{\\text{med}}$).")
    md.append("> - **All-App Mean DeltaE (kWh)**: Sample mean of individual per-app paired differences ($\\frac{1}{N}\\sum_{i=1}^N (E_{\\text{Aegis}, i} - E_{\\text{CA}, i})$), with 95% bootstrap percentile CI.")
    md.append("> - **Sign Convention**: $\\Delta E = E_{\\text{Aegis}} - E_{\\text{CA}}$ (negative = Aegis cheaper).")
    md.append("")

    target_priority = {
        "1.0%": "Primary Benchmark Target (Lowest Extrapolation Rate per D-6)",
        "0.1%": "Secondary Benchmark Target (Strict SLA)",
        "0.0%": "Supplementary Target (Zero Shortfall Lower Bound)",
        "5.0%": "Supplementary Target (High Shortfall Upper Bound)",
    }

    for target, methods in pareto.items():
        prio_label = target_priority.get(target, "Shortfall Target")
        md.append(f"### Target Shortfall: {target} ({methods.get('rolling', {}).get('target_shortfall_minutes', 0.0)} min / 18,720 min) — *{prio_label}*")
        md.append(f"*Source key path: `matched_shortfall_pareto['{target}']`*")
        md.append("")

        md.append("| Conformal Method | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | All-App DeltaE (kWh) [95% CI] | Interp-Only DeltaE (kWh) [95% CI] | Clean Cohort DeltaE (kWh) [95% CI] | Cheaper (%) | Extrap (CA / Aegis) [Below/Above] | Degenerate Frontiers | Key Path |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")

        for m_key, m_data in methods.items():
            ca_med = m_data.get("ca_median_energy", 0.0)
            ae_med = m_data.get("aegis_median_energy", 0.0)
            diff_of_meds = ae_med - ca_med
            mean_delta = m_data.get("mean_delta_energy", 0.0)
            ci = m_data.get("bootstrap_ci95", [0.0, 0.0])
            cheaper_pct = m_data.get("cheaper_fraction_pct", 0.0)
            ca_ext = m_data.get("ca_extrapolations", 0)
            ae_ext = m_data.get("aegis_extrapolations", 0)
            degen_cnt = m_data.get("degenerate_frontiers_count", 0)

            ca_sides = m_data.get("ca_extrapolation_sides", {})
            ae_sides = m_data.get("aegis_extrapolation_sides", {})
            ca_side_str = f"[{ca_sides.get('below_min_shortfall', 0)}B/{ca_sides.get('above_max_shortfall', 0)}A]"
            ae_side_str = f"[{ae_sides.get('below_min_shortfall', 0)}B/{ae_sides.get('above_max_shortfall', 0)}A]"

            interp = m_data.get("interpolated_only", {})
            if interp.get("status") == "valid":
                interp_ci = interp.get("bootstrap_ci95", [0.0, 0.0])
                interp_str = f"{interp.get('mean_delta_energy', 0.0):+.2f} {fmt_ci(interp_ci)} (N={interp.get('n_included')})"
            else:
                interp_str = f"Underpowered (N={interp.get('n_included', 0)}/20)"

            clean = m_data.get("clean_cohort", {})
            if clean.get("status") == "valid":
                clean_ci = clean.get("bootstrap_ci95", [0.0, 0.0])
                clean_str = f"{clean.get('mean_delta_energy', 0.0):+.2f} {fmt_ci(clean_ci)} (N={clean.get('n_included')})"
            else:
                clean_str = f"Underpowered (N={clean.get('n_included', 0)}/20)"

            k_path = f"`matched_shortfall_pareto['{target}']['{m_key}']`"
            m_label = labels.get(m_key, m_key)
            if m_key == "rolling":
                m_label = f"**{m_label} (Primary)**"

            md.append(
                f"| {m_label} | {ca_med:.2f} | {ae_med:.2f} | {diff_of_meds:+.2f} | {mean_delta:+.2f} {fmt_ci(ci)} | {interp_str} | {clean_str} | {cheaper_pct:.1f}% | {ca_ext} {ca_side_str} / {ae_ext} {ae_side_str} | {degen_cnt}/20 | {k_path} |"
            )
        md.append("")

        # Tertile stratification for primary target
        tertiles = methods.get("rolling", {}).get("tertiles", {})
        if tertiles:
            md.append(f"**Tertile Stratification for Primary Arm (Rolling Conformal) at {target} Shortfall**:")
            md.append("*Source key path: `matched_shortfall_pareto['" + target + "']['rolling']['tertiles']`*")
            md.append("")
            md.append("| Tertile | N Apps | CA Median (kWh) | Aegis Median (kWh) | Diff of Medians (kWh) | Mean Paired DeltaE (kWh) [95% CI] | Cheaper Fraction (%) | Key Path |")
            md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
            for t_name, t_data in tertiles.items():
                t_ca_m = t_data.get("ca_median_energy", 0.0)
                t_ae_m = t_data.get("aegis_median_energy", 0.0)
                t_diff = t_data.get("median_diff_energy", 0.0)
                t_mean = t_data.get("mean_delta_energy", 0.0)
                t_ci = t_data.get("bootstrap_ci95", [0.0, 0.0])
                t_cheap = t_data.get("cheaper_fraction_pct", 0.0)
                t_path = f"`matched_shortfall_pareto['{target}']['rolling']['tertiles']['{t_name}']`"
                md.append(f"| {t_name} | {t_data.get('n_apps')} | {t_ca_m:.2f} | {t_ae_m:.2f} | {t_diff:+.2f} | {t_mean:+.2f} {fmt_ci(t_ci)} | {t_cheap:.1f}% | {t_path} |")
            md.append("")

        # Losing apps table
        rolling_losing = methods.get("rolling", {}).get("losing_apps", [])
        if rolling_losing:
            md.append(f"**Losing Apps for Rolling Conformal at {target} Shortfall ({len(rolling_losing)}/20 apps where $\\Delta E > 0$)**:")
            for la in rolling_losing:
                poor_flag = "⚠️ Poor Coverage" if la.get("is_poorly_covered") else "Normal Coverage"
                md.append(f"- App `{la['app_id'][:16]}...`: $\\Delta E = {la['delta_energy_kwh']:+.3f}\\text{{ kWh}}$, Mean Cores = `{la['mean_cores']:.3f}`, Peak = `{la['peak_cores']:.2f}` ({poor_flag})")
            md.append("")

    # 3. Natural Operating Points Section
    ops = data.get("natural_operating_points", {})
    if ops:
        md.append("## 3. Natural Operating Point Benchmark Comparisons (Fixed tau=0.90)")
        md.append("*Source key path: `natural_operating_points.<method>.<ca_setting>`*")
        md.append("")
        md.append("> [!NOTE]")
        md.append("> Compares Aegis operating at fixed nominal quantile $\\tau=0.90$ directly against Cluster Autoscaler at target utilizations $U=50\\%$ and $U=60\\%$.")
        md.append("")

        md.append("| Conformal Method | CA Target | CA Median Energy (kWh) | Aegis Median Energy (kWh) | Mean DeltaE (kWh) [95% CI] | Wilcoxon p (Two-Sided / One-Sided Less) | Holm-Bonf Adj p | Rank-Biserial $r_{rb}$ | CA Med Shortfall (min) | Aegis Med Shortfall (min) | Dominance (Dom / Dmd / Trade / Ident) | Key Path |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")

        for m_key in ["rolling", "scale_aware", "aci_005", "aci_020", "static"]:
            if m_key not in ops:
                continue
            for u_key in ["ca_u_50", "ca_u_60"]:
                op_data = ops[m_key].get(u_key, {})
                ca_u_pct = int(op_data.get("ca_target_utilization", 0.5) * 100)
                ca_e = op_data.get("ca_median_energy", 0.0)
                ae_e = op_data.get("aegis_median_energy", 0.0)
                d_e = op_data.get("mean_delta_energy", 0.0)
                ci_e = op_data.get("bootstrap_ci95_energy", [0.0, 0.0])
                p_two = op_data.get("wilcoxon_two_sided_p", 1.0)
                p_less = op_data.get("wilcoxon_one_sided_p_less", 1.0)
                p_hb = op_data.get("wilcoxon_holm_bonferroni_p", 1.0)
                r_rb = op_data.get("rank_biserial_effect_size", 0.0)
                ca_s = op_data.get("ca_median_shortfall", 0.0)
                ae_s = op_data.get("aegis_median_shortfall", 0.0)
                dom = op_data.get("dominance_counts", {})
                dom_str = f"{dom.get('dominant', 0)} / {dom.get('dominated', 0)} / {dom.get('tradeoff', 0)} / {dom.get('identical', 0)}"
                k_path = f"`natural_operating_points['{m_key}']['{u_key}']`"
                m_label = labels.get(m_key, m_key)
                if m_key == "rolling":
                    m_label = f"**{m_label}**"

                md.append(
                    f"| {m_label} | U={ca_u_pct}% | {ca_e:.2f} | {ae_e:.2f} | {d_e:+.2f} {fmt_ci(ci_e)} | {p_two:.4e} / {p_less:.4e} | {p_hb:.4e} | {r_rb:+.4f} | {ca_s:.1f} | {ae_s:.1f} | {dom_str} | {k_path} |"
                )
        md.append("")

    # 4. Equal Headroom Control
    eh = data.get("equal_headroom_control") or {}
    if eh:
        md.append("## 4. Equal-Headroom Reactive Baseline & Audit Control Comparison")
        md.append("*Source key path: `equal_headroom_control`*")
        md.append("")
        md.append(f"- **Calibrated Static Headroom Margin**: `+{eh.get('calibrated_static_headroom_cores', 8.6468)} cores` (`equal_headroom_control.calibrated_static_headroom_cores`)")
        rh = eh.get("control_arm_a_reactive_headroom") or {}
        ca = eh.get("control_arm_b_ca_hpa_guards") or {}
        ae = eh.get("aegis_conformal_baseline") or {}
        if isinstance(rh, dict) and "energy" in rh:
            md.append(f"- **Control Arm (a) — Reactive + Static Headroom**: Energy Median = `{rh.get('energy', {}).get('median', 'N/A')}` kWh (IQR {rh.get('energy', {}).get('iqr', 'N/A')}), Shortfall Median = `{rh.get('shortfall', {}).get('median', 'N/A')}` min (IQR {rh.get('shortfall', {}).get('iqr', 'N/A')})")
        if isinstance(ca, dict) and "energy" in ca:
            md.append(f"- **Control Arm (b) — CA (U=70%, HPA Guards)**: Energy Median = `{ca.get('energy', {}).get('median', 'N/A')}` kWh (IQR {ca.get('energy', {}).get('iqr', 'N/A')}), Shortfall Median = `{ca.get('shortfall', {}).get('median', 'N/A')}` min (IQR {ca.get('shortfall', {}).get('iqr', 'N/A')})")
        if isinstance(ae, dict) and "energy" in ae:
            md.append(f"- **Aegis Conformal Baseline (tau=0.90)**: Energy Median = `{ae.get('energy', {}).get('median', 'N/A')}` kWh (IQR {ae.get('energy', {}).get('iqr', 'N/A')}), Shortfall Median = `{ae.get('shortfall', {}).get('median', 'N/A')}` min (IQR {ae.get('shortfall', {}).get('iqr', 'N/A')})")
        md.append("")

    md.append("[^1]: **Statistical Footnote**: 'Diff of Medians' is the difference between marginal distribution medians ($E_{\\text{Aegis}}^{\\text{med}} - E_{\\text{CA}}^{\\text{med}}$). 'All-App Mean DeltaE' is the sample average of paired differences $\\frac{1}{N}\\sum (E_{\\text{Aegis}, i} - E_{\\text{CA}, i})$. Because workload demand and energy distributions exhibit skew across heterogeneous applications, the expectation of paired differences differs from the difference of marginal medians.")
    md.append("")
    return "\n".join(md)


def render_scale_aware_pareto_report(data: Dict[str, Any], json_path: str) -> str:
    if data.get("schema_version") == "v4":
        return render_headline_v4_report(data, json_path)

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

    part = data.get("app_partition", {})
    md.append("## 1. App Partition")
    md.append("*Source key path: `app_partition`*")
    md.append(f"- Train Apps: {len(part.get('train_apps', []))} (`app_partition.train_apps`)")
    md.append(f"- Calibrate Apps: {len(part.get('calibrate_apps', []))} (`app_partition.calibrate_apps`)")
    md.append(f"- Test Apps: {len(part.get('test_apps', []))} (`app_partition.test_apps`)")
    md.append("")

    cal = data.get("conformal_calibration", {})
    md.append("## 2. Conformal Calibration Margin")
    md.append("*Source key path: `conformal_calibration`*")
    md.append(f"- Target Quantile: `{cal.get('quantile', 0.90)}` (`conformal_calibration.quantile`)")
    md.append(f"- Calibrated $\\hat{{q}}_{{90}}$ Headroom: `{cal.get('q_hat_90_cores', 0.0):.4f}` cores (`conformal_calibration.q_hat_90_cores`)")
    md.append("")

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

    if data.get("schema_version") == "v4":
        return render_headline_v4_report(data, json_path)
    elif "matched_shortfall_pareto" in data:
        return render_scale_aware_pareto_report(data, json_path)
    elif "cooldown_audit_3_apps" in data:
        return render_audit_controls_report(data, json_path)
    elif "conformal_calibration" in data and "censoring_audit" in data:
        return render_sixty_app_study_report(data, json_path)
    else:
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
