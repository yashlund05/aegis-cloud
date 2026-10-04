"""
Task W3b STEP 1: behavioral solver-bypass mutation check.

Runs the W3 unit-test file (tests/unit/test_baselines_and_ablations.py) three times:
  1. baseline run on the pristine tree            -> expect PASS
  2. mutated tree: the no_cpsat_ffd arm in eval/baselines_study.py is temporarily
     rewired to call the joint-placement (CP-SAT) path ("forecast_plus_power_no_placement"
     -> "full_aegis_conformal" in the res_ffd call) -> expect FAIL
  3. reverted tree                                -> expect PASS

Writes the full captured pytest output and the verdicts to eval/reports/mutation_check.txt.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "eval" / "baselines_study.py"
TEST_FILE = "tests/unit/test_baselines_and_ablations.py"
REPORT = REPO / "eval" / "reports" / "mutation_check.txt"

MUTATION_ORIG = 'p90_ro, "forecast_plus_power_no_placement"'
MUTATION_NEW = 'p90_ro, "full_aegis_conformal"'


def run_pytest() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-v", "--tb=short"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=600,
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    original_bytes = STUDY.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    lines: list[str] = []
    lines.append("Task W3b STEP 1: behavioral solver-bypass mutation check")
    lines.append("=" * 70)
    lines.append(f"test file : {TEST_FILE}")
    lines.append(f"mutation  : in eval/baselines_study.py, the res_ffd call's config")
    lines.append(f"            {MUTATION_ORIG!r} -> {MUTATION_NEW!r}")
    lines.append(f"            (makes the no_cpsat_ffd arm route through the joint-placement")
    lines.append(f"             / CP-SAT path, i.e. 'temporarily make no_cpsat_ffd call the solver')")
    lines.append("")

    try:
        # --- Run 1: pristine tree, expect pass -----------------------------
        run1 = run_pytest()
        run1_pass = run1.returncode == 0
        lines.append(f"[1/3] pristine tree: exit={run1.returncode} -> {'PASS (expected)' if run1_pass else 'FAIL (UNEXPECTED)'}")
        lines.append("-" * 70)
        lines.append(run1.stdout)
        lines.append(run1.stderr)
        lines.append("")

        # --- Run 2: mutated tree, expect fail -------------------------------
        mutated = original_bytes.decode("utf-8")
        n_hits = mutated.count(MUTATION_ORIG)
        if n_hits != 1:
            lines.append(f"[2/3] MUTATION ABORTED: expected exactly 1 occurrence of the "
                         f"mutation target, found {n_hits}. Tree left pristine.")
            out = "\n".join(lines) + "\n"
            REPORT.write_text(out, encoding="utf-8")
            return 2
        mutated = mutated.replace(MUTATION_ORIG, MUTATION_NEW)
        STUDY.write_bytes(mutated.encode("utf-8"))
        try:
            run2 = run_pytest()
            run2_failed = run2.returncode != 0
            lines.append(f"[2/3] mutated tree (no_cpsat_ffd calls the solver): exit={run2.returncode} -> "
                         f"{'FAIL (expected: test catches the mutation)' if run2_failed else 'PASS (UNEXPECTED: test missed the mutation)'}")
            lines.append("-" * 70)
            lines.append(run2.stdout)
            lines.append(run2.stderr)
            lines.append("")
        finally:
            STUDY.write_bytes(original_bytes)
            restored_hash = sha256_of(STUDY)
            if restored_hash != original_hash:
                lines.append("CRITICAL: failed to restore eval/baselines_study.py to its original bytes!")
                out = "\n".join(lines) + "\n"
                REPORT.write_text(out, encoding="utf-8")
                return 3

        # --- Run 3: reverted tree, expect pass -------------------------------
        run3 = run_pytest()
        run3_pass = run3.returncode == 0
        lines.append(f"[3/3] reverted tree: exit={run3.returncode} -> {'PASS (expected)' if run3_pass else 'FAIL (UNEXPECTED)'}")
        lines.append("-" * 70)
        lines.append(run3.stdout)
        lines.append(run3.stderr)
        lines.append("")
    finally:
        # Belt and braces: guarantee the study file is pristine however we exit.
        if sha256_of(STUDY) != original_hash:
            STUDY.write_bytes(original_bytes)

    verdict = (
        "MUTATION CHECK: PASS"
        if (run1_pass and run2_failed and run3_pass)
        else "MUTATION CHECK: FAIL"
    )
    lines.append("-" * 70)
    lines.append(f"revert verified (sha256 matches original): yes")
    lines.append(verdict)
    lines.append(f"  pristine pass  : {'yes' if run1_pass else 'no'}")
    lines.append(f"  mutation caught: {'yes' if run2_failed else 'no'}")
    lines.append(f"  revert pass    : {'yes' if run3_pass else 'no'}")

    out = "\n".join(lines) + "\n"
    REPORT.write_text(out, encoding="utf-8")
    print(out)
    return 0 if (run1_pass and run2_failed and run3_pass) else 1


if __name__ == "__main__":
    sys.exit(main())
