"""
Task W3b STEP 2: per-arm, per-target reproducibility diff between the original W3
baselines run (eval/baselines_results_v1.json) and the clean-checkout re-run
(eval/baselines_results_v1_repro.json).

For every arm x matched-shortfall target and every arm x natural operating point, walks
all numeric leaves of both JSON documents and reports the maximum absolute difference.
Provenance fields (git_commit, timestamp_utc, dirty_flag) are expected to differ and are
reported separately as informational. Writes eval/reports/repro_diff.txt.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "eval" / "baselines_results_v1.json"
REPRO = REPO / "eval" / "baselines_results_v1_repro.json"
REPORT = REPO / "eval" / "reports" / "repro_diff.txt"
TOL = 1e-6

PROVENANCE_KEYS = {"git_commit", "timestamp_utc", "dirty_flag", "python_version"}


def numeric_leaves(obj, prefix=""):
    """Yield (path, value) for every numeric leaf in a nested dict/list."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield prefix, float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from numeric_leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from numeric_leaves(v, f"{prefix}[{i}]")


def compare_sections(v1, repro, section, get_arms):
    """Compare per-arm subsections; returns (rows, structural_issues)."""
    rows, issues = [], []
    sec1, sec2 = v1.get(section, {}), repro.get(section, {})
    arms1, arms2 = get_arms(v1), get_arms(repro)
    for arm in sorted(set(arms1) | set(arms2)):
        a1, a2 = sec1.get(arm), sec2.get(arm)
        if a1 is None or a2 is None:
            issues.append(f"{section}: arm '{arm}' missing in "
                          f"{'v1' if a1 is None else 'repro'}")
            continue
        sub1 = sec1[arm]
        sub2 = sec2[arm]
        for sub_key in sorted(set(sub1) | set(sub2)):
            if sub_key not in sub1 or sub_key not in sub2:
                issues.append(f"{section}.{arm}: subsection '{sub_key}' missing in "
                              f"{'v1' if sub_key not in sub1 else 'repro'}")
                continue
            l1 = dict(numeric_leaves(sub1[sub_key]))
            l2 = dict(numeric_leaves(sub2[sub_key]))
            keys1, keys2 = set(l1), set(l2)
            if keys1 != keys2:
                issues.append(f"{section}.{arm}.{sub_key}: numeric-leaf sets differ "
                              f"(v1-only: {sorted(keys1 - keys2)[:5]}, "
                              f"repro-only: {sorted(keys2 - keys1)[:5]})")
                continue
            max_diff = max((abs(l1[k] - l2[k]) for k in keys1), default=0.0)
            rows.append((section, arm, sub_key, len(keys1), max_diff))
    return rows, issues


def pareto_arms(doc):
    out = {}
    for target, sec in doc.get("matched_shortfall_pareto", {}).items():
        out.update({(target, arm): val for arm, val in sec.items()
                    if isinstance(val, dict)})
    return out


def main() -> int:
    with open(V1, "r", encoding="utf-8") as f:
        v1 = json.load(f)
    with open(REPRO, "r", encoding="utf-8") as f:
        repro = json.load(f)

    lines: list = []
    lines.append("Task W3b STEP 2: reproducibility diff - baselines_results_v1.json vs baselines_results_v1_repro.json")
    lines.append("=" * 110)
    lines.append(f"v1    commit={v1.get('git_commit')} dirty={v1.get('dirty_flag')} "
                 f"config_hash={v1.get('config_hash')}")
    lines.append(f"repro commit={repro.get('git_commit')} dirty={repro.get('dirty_flag')} "
                 f"config_hash={repro.get('config_hash')}")
    lines.append(f"config_hash identical: {v1.get('config_hash') == repro.get('config_hash')}")
    lines.append(f"tolerance for 'identical': max |v1 - repro| <= {TOL:g}")
    lines.append("")
    lines.append("Study configuration identical: "
                 f"{v1.get('configuration') == repro.get('configuration')}")
    lines.append("App partition identical: "
                 f"{v1.get('app_partition') == repro.get('app_partition')}")
    lines.append("")

    all_rows: list = []
    issues: list = []

    # Matched-shortfall Pareto: one row per (target, arm); includes per-app energies.
    sec1, sec2 = v1.get("matched_shortfall_pareto", {}), repro.get("matched_shortfall_pareto", {})
    for target in sorted(set(sec1) | set(sec2)):
        arms1 = {k for k, v in sec1.get(target, {}).items() if isinstance(v, dict)}
        arms2 = {k for k, v in sec2.get(target, {}).items() if isinstance(v, dict)}
        for arm in sorted(arms1 | arms2):
            if arm not in arms1 or arm not in arms2:
                issues.append(f"matched_shortfall_pareto[{target}]: arm '{arm}' missing in "
                              f"{'v1' if arm not in arms1 else 'repro'}")
                continue
            l1 = dict(numeric_leaves(sec1[target][arm]))
            l2 = dict(numeric_leaves(sec2[target][arm]))
            if set(l1) != set(l2):
                issues.append(f"matched_shortfall_pareto[{target}][{arm}]: numeric-leaf sets differ")
                continue
            max_diff = max((abs(l1[k] - l2[k]) for k in l1), default=0.0)
            all_rows.append(("matched_shortfall_pareto", f"target={target} arm={arm}", "", len(l1), max_diff))

    # Natural operating points: one row per (arm, ca_u).
    rows, iss = compare_sections(v1, repro, "natural_operating_points",
                                 lambda d: set(d.get("natural_operating_points", {})))
    all_rows.extend(rows)
    issues.extend(iss)

    lines.append(f"{'section':28s} {'arm / target':45s} {'sub':10s} {'#fields':>8s} {'max |diff|':>12s}")
    lines.append("-" * 110)
    for section, arm, sub, n, diff in all_rows:
        lines.append(f"{section:28s} {arm:45s} {sub:10s} {n:>8d} {diff:>12.6g}")
    lines.append("")

    overall_max = max((r[4] for r in all_rows), default=0.0)
    n_rows = len(all_rows)

    # Provenance fields, informational only.
    prov_diffs = []
    for k in PROVENANCE_KEYS:
        if v1.get(k) != repro.get(k):
            prov_diffs.append(k)

    within = overall_max <= TOL and not issues
    lines.append("SUMMARY")
    lines.append("-" * 110)
    lines.append(f"arm x target/subsection comparisons: {n_rows}")
    lines.append(f"numeric fields compared (total, with repetition across comparisons): {sum(r[3] for r in all_rows)}")
    lines.append(f"overall max absolute difference: {overall_max:.6g}")
    lines.append(f"structural issues (missing arms/fields): {len(issues)}")
    for iss in issues:
        lines.append(f"  - {iss}")
    lines.append(f"provenance fields differing (expected, informational): {prov_diffs or '(none)'}")
    lines.append(f"MAX DIFF WITHIN {TOL:g}: {'YES' if within else 'NO'}")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if within else 1


if __name__ == "__main__":
    sys.exit(main())
