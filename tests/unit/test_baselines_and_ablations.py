"""W3 unit tests: solver bypass for no_cpsat_ffd and shared simulation path for all arms."""
import ast
import inspect
import textwrap
from pathlib import Path

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
    tree = ast.parse(BASELINES_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "res_ffd" for t in node.targets
        ):
            call = node.value
            for a in call.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    return a.value
    raise AssertionError("res_ffd call not found")


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
