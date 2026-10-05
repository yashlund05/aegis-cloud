"""
Task W3b STEP 2: clean-checkout reproducibility audit for the W3 baselines study.

Run from the MAIN repo working tree. It:

1. Clones the current HEAD into a temp dir (pre-fix clone), copies in the gitignored
   external dataset inputs (Azure 2019 trace cache + per-app memory CSVs), and runs an
   instrumented probe of every file-loading step of eval/baselines_study.py with a
   Python audit hook recording every file opened. Files missing from the clean checkout
   are exactly the uncommitted ones the study needs.
2. Clones the current HEAD again (post-fix clone; HEAD must already contain the committed
   artifacts), copies in the same dataset inputs, and runs the FULL baselines study under
   a generated sitecustomize shim (on PYTHONPATH) so file opens are recorded for the
   parent process AND every ProcessPoolExecutor spawn worker, producing
   eval/baselines_results_v1_repro.json inside the post-fix clone.
3. Aggregates both event sets, checks each path against `git ls-files` and the
   filesystem, verifies copied-input integrity by sha256, and writes
   eval/reports/artifacts_audit.txt in the MAIN repo. Also copies the repro JSON back to
   the main repo's eval/ directory (byte-identical).

Usage:
    python eval/run_artifacts_audit.py [--workers 6]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "eval" / "reports" / "artifacts_audit.txt"
REPRO_JSON_NAME = "baselines_results_v1_repro.json"

# Gitignored external dataset inputs the study needs at runtime (Azure Functions 2019
# trace derivatives; provenance pinned by datasets/CHECKSUMS.txt and the deterministic
# extraction script datasets/load_real_trace.py). Not model artifacts.
DATASET_INPUTS = ["datasets/azure_30_study_apps.parquet"] + [
    f"datasets/raw/azurefunctions2019/app_memory_percentiles.anon.d{d:02d}.csv"
    for d in range(1, 13)
]

# Static manifest: every file outside eval/ the baselines study chain reads or writes,
# with the code path that touches it. The dynamic audit corroborates each entry.
STATIC_MANIFEST = [
    {
        "path": "ml/models/artifacts_60app/aegis_h10m_q10.txt",
        "role": "baseline model artifact (LightGBM p10, primary forecaster)",
        "referenced": "eval/baselines_study.py via MODELS_DIR (eval/headline_study_v4.py), lgb.Booster(model_file=...)",
    },
    {
        "path": "ml/models/artifacts_60app/aegis_h10m_q50.txt",
        "role": "baseline model artifact (LightGBM p50, primary forecaster)",
        "referenced": "eval/baselines_study.py via MODELS_DIR (eval/headline_study_v4.py), lgb.Booster(model_file=...)",
    },
    {
        "path": "ml/models/artifacts_60app/aegis_h10m_q90.txt",
        "role": "baseline model artifact (LightGBM p90, primary forecaster)",
        "referenced": "eval/baselines_study.py via MODELS_DIR (eval/headline_study_v4.py), lgb.Booster(model_file=...)",
    },
    {
        "path": "ml/models/artifacts_linear/feature_columns.json",
        "role": "baseline model artifact (quantile_linear feature list)",
        "referenced": "eval/baselines_study.py: open() + json.load",
    },
    {
        "path": "ml/models/artifacts_linear/quantile_linear_q50.joblib",
        "role": "baseline model artifact (sklearn QuantileRegressor p50, quantile_linear arm)",
        "referenced": "eval/baselines_study.py: joblib.load",
    },
    {
        "path": "ml/models/artifacts_linear/quantile_linear_q90.joblib",
        "role": "baseline model artifact (sklearn QuantileRegressor p90, quantile_linear arm)",
        "referenced": "eval/baselines_study.py: joblib.load",
    },
    {
        "path": "ml/models/artifacts/aegis_h5m_q10.txt",
        "role": "baseline model artifact (AegisPredictor h5m p10)",
        "referenced": "ml/inference/predict.py AegisPredictor.load_models() glob, instantiated by AblationStudy.__init__ in every baselines worker",
    },
    {
        "path": "ml/models/artifacts/aegis_h10m_q10.txt",
        "role": "baseline model artifact (AegisPredictor h10m p10)",
        "referenced": "ml/inference/predict.py AegisPredictor.load_models() glob, instantiated by AblationStudy.__init__ in every baselines worker",
    },
    {
        "path": "ml/models/artifacts/aegis_h15m_q50.txt",
        "role": "baseline model artifact (AegisPredictor h15m p50, representative of the 9 h{5,10,15}m x q{10,50,90} boosters + 9 _meta.json files loaded by each worker)",
        "referenced": "ml/inference/predict.py AegisPredictor.load_models() glob, instantiated by AblationStudy.__init__ in every baselines worker",
    },
    {
        "path": "ml/models/registry.json",
        "role": "model registry (committed); NOT read or written by the baselines study chain - only ml/models/registry.py ModelRegistry (instantiated by ml/training/train_lightgbm.py training functions) touches it; audit verifies zero dynamic events",
        "referenced": "none in the baselines study import chain (expected: 0 observed events)",
    },
    {
        "path": "datasets/azure_30_study_apps.parquet",
        "role": "external dataset input, gitignored by design (study cache of the 30-app Azure trace; also WRITTEN by load_study_data() if absent)",
        "referenced": "eval/headline_study_v4.py load_study_data(): pd.read_parquet (CACHE_FILE)",
    },
    {
        "path": "datasets/raw/azurefunctions2019/app_memory_percentiles.anon.d01.csv",
        "role": "external dataset input, gitignored by design (Azure raw trace; representative of d01..d12 read by load_memory_table)",
        "referenced": "datasets/load_real_trace.py load_memory_table(), called from eval/headline_study_v4.py load_study_data()",
    },
]

EXCLUDED_DIR_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}

PROBE_SCRIPT_TEMPLATE = r'''
"""Generated by eval/run_artifacts_audit.py - pre-fix loading-path probe (pre-fix clone)."""
import json, os, sys, tempfile

# The probe script lives in the temp dir, so sys.path[0] is that dir, not the clone root;
# the study modules must be imported from the clone working directory.
sys.path.insert(0, os.getcwd())

LOG_DIR = sys.argv[1]
os.makedirs(LOG_DIR, exist_ok=True)
_fd = os.open(os.path.join(LOG_DIR, "pid_%d.log" % os.getpid()),
              os.O_APPEND | os.O_CREAT | os.O_WRONLY)

def _hook(event, args):
    if event == "open":
        try:
            line = json.dumps({"p": str(args[0]), "m": str(args[1])}) + "\n"
            os.write(_fd, line.encode("utf-8"))
        except Exception:
            pass

sys.addaudithook(_hook)

import joblib
import lightgbm as lgb

failures = []

def failures_dump(*_a):
    with open(os.path.join(LOG_DIR, "probe_failures.txt"), "w") as f:
        f.write("\n".join(failures))

try:
    from eval.baselines_study import run_baselines_study  # full import chain
    from eval.headline_study_v4 import MODELS_DIR, HORIZON_MINUTES, load_study_data
except Exception as e:
    failures.append("import chain: %s: %s" % (type(e).__name__, e))
    failures_dump()
    sys.exit(1)

# 1. study data loading (cache parquet + raw memory CSVs)
try:
    load_study_data()
except Exception as e:
    failures.append("load_study_data: %s: %s" % (type(e).__name__, e))

# 2. LightGBM boosters from MODELS_DIR (artifacts_60app)
for q in (0.1, 0.5, 0.9):
    p = os.path.join(MODELS_DIR, "aegis_h%dm_q%d.txt" % (HORIZON_MINUTES, int(q * 100)))
    try:
        lgb.Booster(model_file=p)
    except Exception as e:
        failures.append("%s: %s: %s" % (p, type(e).__name__, e))

# 3. AblationStudy default constructor (AegisPredictor loads ml/models/artifacts)
try:
    from ml.evaluation.ablation import AblationStudy
    AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
except Exception as e:
    failures.append("AblationStudy(): %s: %s" % (type(e).__name__, e))

# 4. quantile_linear artifacts (expected uncommitted pre-fix)
for name in ("quantile_linear_q50.joblib", "quantile_linear_q90.joblib"):
    p = os.path.join("ml", "models", "artifacts_linear", name)
    try:
        joblib.load(p)
    except Exception as e:
        failures.append("%s: %s: %s" % (p, type(e).__name__, e))

failures_dump()
print("PROBE DONE; %d failures" % len(failures))
'''


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_out(repo: Path, *args: str) -> str:
    res = subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        return ""
    return res.stdout


def clone_head(dest: Path) -> None:
    res = subprocess.run(
        ["git", "clone", "--quiet", str(REPO), str(dest)],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git clone failed: {res.stderr}")


def copy_dataset_inputs(clone: Path, integrity: list, label: str) -> None:
    for rel in DATASET_INPUTS:
        src = REPO / rel
        dst = clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        s_hash, d_hash = sha256_of(src), sha256_of(dst)
        integrity.append((label, rel, s_hash == d_hash, s_hash[:16]))


def verify_dataset_inputs(clone: Path, integrity: list, label: str) -> None:
    """Aggregate-only mode: re-verify the sha256 of dataset inputs already in a preserved clone."""
    for rel in DATASET_INPUTS:
        src = REPO / rel
        dst = clone / rel
        if not dst.exists():
            integrity.append((label, rel, False, "-"))
            continue
        s_hash, d_hash = sha256_of(src), sha256_of(dst)
        integrity.append((label, rel, s_hash == d_hash, s_hash[:16]))


def load_events(log_dir: Path, resolve_root: Path) -> dict:
    """path -> {'modes': set, 'count': int, 'pids': set}

    Relative open() paths are recorded verbatim by the audit hook; they are relative to
    the cwd of the process that opened them (the clone), so resolve against resolve_root.
    Pure-digit paths are integer file descriptors passed to open()/fdopen (e.g. by
    multiprocessing plumbing), not filesystem paths - skip them.
    """
    events: dict = {}
    for log in sorted(log_dir.glob("pid_*.log")):
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            p, m = rec.get("p", ""), rec.get("m", "") or ""
            if p.isdigit():
                continue
            try:
                rp = Path(p)
                if not rp.is_absolute():
                    p = str(resolve_root / rp)
            except Exception:
                pass
            e = events.setdefault(os.path.normpath(p), {"modes": set(), "count": 0, "pids": set()})
            e["modes"].add(m if m else "<default>")
            e["count"] += 1
            e["pids"].add(log.stem)
    return events


def repo_relative_events(events: dict, root: Path) -> dict:
    """Keep events inside `root`, excluding noise dirs; return relpath_posix -> event."""
    out = {}
    root_n = os.path.normpath(str(root)).lower()
    for p, e in events.items():
        pn = os.path.normpath(p).lower()
        if not pn.startswith(root_n + os.sep):
            continue
        try:
            rel = os.path.relpath(p, root).replace("\\", "/")
        except ValueError:
            # Windows reserved device names (nul, con, ...) or cross-mount paths:
            # not real repo files, skip them.
            continue
        parts = set(rel.split("/")[:-1])
        if parts & EXCLUDED_DIR_PARTS:
            continue
        if rel.endswith(".pyc"):
            continue
        out[rel] = e
    return out


def outside_eval(rel_events: dict) -> dict:
    return {r: e for r, e in rel_events.items() if not r.startswith("eval/")}


def committed_status(clone: Path, rel: str) -> bool:
    return bool(git_out(clone, "ls-files", "--", rel).strip())


def write_sitecustomize(tmpdir: Path, log_dir: Path) -> None:
    shim = f'''
import sys, os, json
_LOG_DIR = r"{log_dir}"
os.makedirs(_LOG_DIR, exist_ok=True)
try:
    _fd = os.open(os.path.join(_LOG_DIR, "pid_%d.log" % os.getpid()),
                  os.O_APPEND | os.O_CREAT | os.O_WRONLY)
except Exception:
    _fd = None

def _hook(event, args):
    if event == "open" and _fd is not None:
        try:
            if isinstance(args[0], int):
                return  # fd-based open (multiprocessing plumbing), not a filesystem path
            line = json.dumps({{"p": str(args[0]), "m": str(args[1])}}) + "\\n"
            os.write(_fd, line.encode("utf-8"))
        except Exception:
            pass

sys.addaudithook(_hook)
'''
    (tmpdir / "sitecustomize.py").write_text(shim, encoding="utf-8")


def fmt_event_row(rel: str, e: dict, clone: Path) -> str:
    modes = ",".join(sorted(e["modes"]))
    writes = any(c in modes for c in "wax+")
    kind = "WRITE" if writes else "read"
    com = "committed" if committed_status(clone, rel) else "NOT COMMITTED"
    exists = "present" if (clone / rel).exists() else "MISSING"
    return f"  {rel:75s} {kind:6s} x{e['count']:<6d} {exists:8s} {com}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--aggregate-only", type=str, default=None, metavar="WORKDIR",
                        help="re-aggregate the report from a preserved audit work dir "
                             "(clones + audit-event logs + repro output) without re-running the study")
    args = parser.parse_args()

    if args.aggregate_only:
        work = Path(args.aggregate_only)
        pre_clone = work / "aegis_prefix"
        post_clone = work / "aegis_repro"
        pre_log = work / "audit_events_prefix"
        post_log = work / "audit_events_post"
        probe_res = None
        study_res = None
        study_log = work / "repro_run.log"
    else:
        work = Path(tempfile.mkdtemp(prefix="aegis_w3b_audit_"))
        pre_clone = work / "aegis_prefix"
        post_clone = work / "aegis_repro"
        pre_log = work / "audit_events_prefix"
        post_log = work / "audit_events_post"
        pre_log.mkdir()
        post_log.mkdir()
        probe_res = None
        study_res = None
        study_log = work / "repro_run.log"

    integrity: list = []
    report: list = []
    report.append("Task W3b STEP 2: clean-checkout artifacts audit (baselines study)")
    report.append("=" * 100)
    report.append(f"main repo HEAD: {git_out(REPO, 'rev-parse', 'HEAD').strip()}")
    report.append(f"method: git clone HEAD into temp dirs; Python audit hook (sys.addaudithook, event 'open')")
    report.append(f"        records every file opened by the study process tree (parent + spawn workers);")
    report.append(f"        each repo-relative path outside eval/ is checked against `git ls-files` and the filesystem.")
    if args.aggregate_only:
        report.append(f"mode: --aggregate-only (report re-aggregated from preserved audit work dir; no re-run)")
    report.append(f"work dir: {work}")
    report.append("")

    # ---------------- Phase 1: probe in a fresh clone of HEAD ----------------
    report.append("PHASE 1 - fresh clone of current HEAD, instrumented loading-path probe")
    report.append("-" * 100)
    if not args.aggregate_only:
        clone_head(pre_clone)
        copy_dataset_inputs(pre_clone, integrity, "probe-clone")
        probe_file = work / "probe_script.py"
        probe_file.write_text(PROBE_SCRIPT_TEMPLATE, encoding="utf-8")
        probe_res = subprocess.run(
            [sys.executable, str(probe_file), str(pre_log)],
            cwd=str(pre_clone), capture_output=True, text=True, timeout=1800,
        )
    report.append(f"clone: {pre_clone} at HEAD {git_out(pre_clone, 'rev-parse', 'HEAD').strip()}")
    pre_events = repo_relative_events(load_events(pre_log, pre_clone), pre_clone)
    pre_outside = outside_eval(pre_events)
    pre_failures_file = pre_log / "probe_failures.txt"
    pre_failures = pre_failures_file.read_text(encoding="utf-8").splitlines() if pre_failures_file.exists() else []
    if probe_res is not None:
        report.append(f"probe exit: {probe_res.returncode}; stdout tail: {probe_res.stdout.strip().splitlines()[-1] if probe_res.stdout.strip() else '(none)'}")
    else:
        report.append(f"probe outcome (from preserved logs): {'0 failures' if not pre_failures else f'{len(pre_failures)} failures'}")
    report.append("probe load failures (these are exactly the files the study needs but the clean checkout lacks):")
    if pre_failures:
        for f in pre_failures:
            report.append(f"  - {f}")
    else:
        report.append("  - (none)")
    report.append("")
    report.append("Files outside eval/ touched by the baselines-study loading path in the PRE-FIX clean clone:")
    for rel in sorted(pre_outside):
        report.append(fmt_event_row(rel, pre_outside[rel], pre_clone))
    report.append("")

    # ---------------- Phase 2: full audited repro run in a post-fix clone -------------
    report.append("PHASE 2 - fresh clone of current HEAD (post artifact commit), full baselines study re-run")
    report.append("-" * 100)
    repro_json = post_clone / "eval" / REPRO_JSON_NAME
    if not args.aggregate_only:
        clone_head(post_clone)
        report.append(f"clone: {post_clone} at HEAD {git_out(post_clone, 'rev-parse', 'HEAD').strip()}")
        dirty = git_out(post_clone, "status", "--porcelain").strip()
        report.append(f"clone working-tree status before run: {'CLEAN (only gitignored dataset inputs copied in)' if not dirty else dirty}")
        copy_dataset_inputs(post_clone, integrity, "repro-clone")
        write_sitecustomize(work, post_log)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(work) + os.pathsep + env.get("PYTHONPATH", "")
        study_res = subprocess.run(
            [sys.executable, "eval/baselines_study.py",
             "--output", f"eval/{REPRO_JSON_NAME}", "--workers", str(args.workers)],
            cwd=str(post_clone), capture_output=True, text=True, timeout=4 * 3600, env=env,
        )
        study_log.write_text(study_res.stdout + "\n" + study_res.stderr, encoding="utf-8")
    else:
        report.append(f"clone: {post_clone} (preserved) at HEAD {git_out(post_clone, 'rev-parse', 'HEAD').strip()}")
        verify_dataset_inputs(post_clone, integrity, "repro-clone")
    if study_res is not None:
        report.append(f"study exit: {study_res.returncode} (log: {study_log})")
    else:
        completed_ok = repro_json.exists() and "Baselines study completed" in study_log.read_text(encoding="utf-8", errors="replace")
        report.append(f"study outcome (from preserved logs): {'exit 0, completed' if completed_ok else 'NOT COMPLETED'} (log: {study_log})")
    report.append(f"repro output written: eval/{REPRO_JSON_NAME} in the post-fix clone -> "
                  f"{'exists' if repro_json.exists() else 'MISSING'}")
    if repro_json.exists():
        with open(repro_json, "r", encoding="utf-8") as f:
            repro_prov = json.load(f)
        report.append(f"repro provenance: git_commit={repro_prov.get('git_commit')}, "
                      f"dirty_flag={repro_prov.get('dirty_flag')}, config_hash={repro_prov.get('config_hash')}")
    report.append("")

    post_events = repo_relative_events(load_events(post_log, post_clone), post_clone)
    post_outside = outside_eval(post_events)
    report.append("Files outside eval/ read or written by the full baselines-study run in the POST-FIX clean clone:")
    for rel in sorted(post_outside):
        report.append(fmt_event_row(rel, post_outside[rel], post_clone))
    report.append("")
    writes_inside_eval = sorted(r for r, e in repo_relative_events(load_events(post_log, post_clone), post_clone).items()
                                if r.startswith("eval/") and any(c in "".join(e["modes"]) for c in "wax+"))
    report.append("Writes inside eval/ (allowed): " + ", ".join(writes_inside_eval))
    report.append("")

    # ---------------- Static manifest cross-check -------------------------------------
    report.append("STATIC MANIFEST (every file outside eval/ the baselines study chain reads/writes, per code path)")
    report.append("-" * 100)
    report.append(f"{'path':75s} {'committed':9s} {'in clean clone':14s} {'dynamically observed'}")
    for entry in STATIC_MANIFEST:
        rel = entry["path"]
        com = "yes" if committed_status(post_clone, rel) else "NO"
        exists = "yes" if (post_clone / rel).exists() else "NO"
        observed = "yes" if rel in post_outside else ("yes (pre-fix probe)" if rel in pre_outside else "no*")
        report.append(f"  {rel:73s} {com:9s} {exists:14s} {observed}")
    report.append("  * 'no' = not observed by the audit hook in the listed run; see role note. "
                  "ml/models/registry.json must show 0 events (not used by this study).")
    report.append("")
    for entry in STATIC_MANIFEST:
        report.append(f"  {entry['path']}")
        report.append(f"      role      : {entry['role']}")
        report.append(f"      referenced: {entry['referenced']}")
    report.append("")

    # ---------------- Dataset input integrity + verdicts ------------------------------
    report.append("External dataset inputs (gitignored by design; sha256-verified against the main repo):")
    for label, rel, ok, h in integrity:
        report.append(f"  [{label}] {'OK ' if ok else 'MISMATCH'} {h}…  {rel}")
    report.append("")

    pre_missing = sorted(r for r in pre_outside if not (pre_clone / r).exists())
    report.append("VERDICTS")
    report.append("-" * 100)
    report.append(f"1. Files the baselines study needs outside eval/ that were MISSING from the pre-fix clean checkout:")
    if pre_missing:
        for rel in pre_missing:
            report.append(f"   - {rel} (committed: {'yes' if committed_status(pre_clone, rel) else 'NO'})")
    else:
        report.append("   - (none)")
    uncommitted_baseline_artifacts = [r for r in pre_missing if r.startswith("ml/models/")]
    report.append(f"2. Uncommitted baseline MODEL artifacts: "
                  f"{', '.join(uncommitted_baseline_artifacts) if uncommitted_baseline_artifacts else '(none)'}")
    model_artifacts_ok = all(
        committed_status(post_clone, e["path"]) and (post_clone / e["path"]).exists()
        for e in STATIC_MANIFEST
        if e["path"].startswith("ml/models/") and e["path"] != "ml/models/registry.json"
    )
    report.append(f"3. Post-fix: all baseline model artifacts committed and present in the post-fix clean clone: "
                  f"{'yes' if model_artifacts_ok else 'NO'}")
    study_ok = (study_res.returncode == 0 if study_res is not None
                else repro_json.exists() and "Baselines study completed" in study_log.read_text(encoding="utf-8", errors="replace"))
    report.append(f"4. Full baselines study re-run on the clean tree: "
                  f"{'SUCCEEDED' if study_ok and repro_json.exists() else 'FAILED'} -> eval/{REPRO_JSON_NAME}")
    report.append(f"5. ml/models/registry.json touched by the study: "
                  f"{'NO (0 events, as expected)' if 'ml/models/registry.json' not in post_outside else 'YES (unexpected!)'}")
    report.append("")
    report.append(f"repro run study log copied to main repo: eval/reports/repro_run.log")

    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

    # Copy repro JSON + study log back to the main repo (byte-identical).
    if repro_json.exists():
        shutil.copyfile(repro_json, REPO / "eval" / REPRO_JSON_NAME)
    if study_log.exists():
        shutil.copyfile(study_log, REPO / "eval" / "reports" / "repro_run.log")

    print(f"audit report written: {REPORT}")
    print(f"repro json copied to main repo: eval/{REPRO_JSON_NAME}")
    return 0 if (study_ok and repro_json.exists()) else 1


if __name__ == "__main__":
    sys.exit(main())
