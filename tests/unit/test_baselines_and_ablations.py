"""W3 unit tests: solver bypass for no_cpsat_ffd and shared simulation path for all arms."""
import ast
import inspect
import textwrap
from pathlib import Path

import numpy as np
import pytest

from ml.evaluation.ablation import AblationStudy

REPO = Path(__file__).resolve().parents[2]
BASELINES_SRC = (REPO / "eval" / "baselines_study.py").read_text(encoding="utf-8")


def _placement_opt_configs():
    """Parse the has_placement_opt membership tuple out of _simulate_configuration."""
    src = textwrap.dedent(inspect.getsource(AblationStudy._simulate_configuration))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "has_placement_opt" for t in node.targets
        ):
            comp = node.value
            assert isinstance(comp, ast.Compare)
            return {elt.value for elt in comp.comparators[0].elts}
    raise AssertionError("has_placement_opt assignment not found")


def _ffd_config_name():
    """Config name passed to _simulate_configuration for the no_cpsat_ffd arm."""
    return _arm_config_name("res_ffd")


def _rolling_config_name():
    """Config name passed to _simulate_configuration for the primary rolling Aegis arm."""
    return _arm_config_name("res_ro")


def _arm_config_name(result_var: str) -> str:
    """Positional config-name argument of the _simulate_configuration call assigned to `result_var`."""
    tree = ast.parse(BASELINES_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == result_var for t in node.targets
        ):
            call = node.value
            for a in call.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    return a.value
    raise AssertionError(f"{result_var} call not found")


def test_no_cpsat_ffd_bypasses_placement_optimizer():
    opt = _placement_opt_configs()
    ffd_cfg = _ffd_config_name()
    assert ffd_cfg == "forecast_plus_power_no_placement"
    assert ffd_cfg not in opt
    assert "full_aegis_conformal" in opt


def test_all_arms_use_simulate_configuration():
    tree = ast.parse(BASELINES_SRC)
    sim_calls, other_sim = 0, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name == "_simulate_configuration":
                sim_calls += 1
            elif name.startswith("_simulate") or name == "run_comparison":
                other_sim.append(name)
    assert sim_calls > 0
    assert other_sim == []


def _synthetic_workload(steps: int = 240, seed: int = 42):
    """Short synthetic demand trace (cores) with diurnal shape plus aligned forecasts."""
    rng = np.random.RandomState(seed)
    t = np.arange(steps)
    y = 3.0 + 1.5 * np.sin(2.0 * np.pi * t / 120.0) + 0.004 * t + rng.uniform(0.0, 0.2, steps)
    mem = np.full(steps, 4.0)
    p90 = y + 0.4
    return y, mem, p90


def test_behavioral_solver_bypass_on_synthetic_workload(monkeypatch):
    """
    Behavioral bypass check (W3b): run the exact configs the baselines study uses for the
    no_cpsat_ffd and rolling arms on a synthetic workload, with counters on
    (a) the in-simulator CP-SAT joint-placement entry point `_pack_pods(opt=True)` — the
        placement-optimization path that `has_placement_opt=True` arms route through, and
    (b) the live service CP-SAT solver `CPSolver.solve` (must never be reached offline).
    Config names are read from eval/baselines_study.py so any change to which solver path
    an arm routes through is caught by actually executing it.
    """
    from services.decision_engine.solver import CPSolver

    ffd_cfg = _ffd_config_name()
    rolling_cfg = _rolling_config_name()
    y, mem, p90 = _synthetic_workload()

    pack_counts = {"opt_true": 0, "opt_false": 0}
    cpsat_calls = {"solve": 0}

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    orig_pack = study._pack_pods

    def spying_pack(num_pods, opt):
        pack_counts["opt_true" if opt else "opt_false"] += 1
        return orig_pack(num_pods, opt)

    study._pack_pods = spying_pack

    orig_solve = CPSolver.solve

    def spying_solve(self, *args, **kwargs):
        cpsat_calls["solve"] += 1
        return orig_solve(self, *args, **kwargs)

    monkeypatch.setattr(CPSolver, "solve", spying_solve)

    study._simulate_configuration(y, mem, p90, ffd_cfg, forecast_horizon_minutes=10)
    ffd_opt_true, ffd_opt_false = pack_counts["opt_true"], pack_counts["opt_false"]

    pack_counts["opt_true"] = 0
    pack_counts["opt_false"] = 0
    study._simulate_configuration(y, mem, p90, rolling_cfg, forecast_horizon_minutes=10)
    roll_opt_true, roll_opt_false = pack_counts["opt_true"], pack_counts["opt_false"]

    # no_cpsat_ffd arm: zero calls into the joint-placement (CP-SAT) path, and the
    # FFD packing path is actually exercised (spy saw real work).
    assert ffd_opt_true == 0, (
        f"no_cpsat_ffd arm (config {ffd_cfg!r}) invoked the joint-placement optimizer "
        f"{ffd_opt_true} times; expected 0"
    )
    assert ffd_opt_false > 0, (
        f"no_cpsat_ffd arm (config {ffd_cfg!r}) never invoked the FFD packing path"
    )
    # normal rolling Aegis arm: placement-optimizer (CP-SAT) path is exercised.
    assert roll_opt_true > 0, (
        f"rolling arm (config {rolling_cfg!r}) never invoked the joint-placement optimizer"
    )
    assert roll_opt_false == 0, (
        f"rolling arm (config {rolling_cfg!r}) unexpectedly used the non-optimized packing path"
    )
    # The live service CP-SAT solver is never reached by the offline simulation for either arm.
    assert cpsat_calls["solve"] == 0, (
        f"offline simulation called services CPSolver.solve {cpsat_calls['solve']} times"
    )
