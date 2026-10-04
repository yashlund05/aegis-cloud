"""Dump per-app (app x target x arm) matched-shortfall results from a baselines JSON to CSV."""
import csv
import json
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "eval/baselines_results_v1.json"
dst = sys.argv[2] if len(sys.argv) > 2 else "eval/reports/per_app_baselines.csv"

d = json.load(open(src, encoding="utf-8"))
rows = []
for target, arms in d["matched_shortfall_pareto"].items():
    for arm, res in arms.items():
        if not isinstance(res, dict) or "per_app_results" not in res:
            continue
        for app, v in res["per_app_results"].items():
            rows.append({"app_id": app, "target": target, "arm": arm, **v})

fields = ["app_id", "target", "arm"] + [k for k in rows[0] if k not in ("app_id", "target", "arm")]
with open(dst, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
print(f"wrote {len(rows)} rows to {dst} (source git_commit={d['git_commit']}, dirty_flag={d['dirty_flag']})")
