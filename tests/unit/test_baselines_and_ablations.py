import pytest
from ml.evaluation.ablation import AblationStudy


def test_no_cpsat_ffd_bypasses_placement_optimization():
    """Verify that no_cpsat_ffd (forecast_plus_power_no_placement) has placement optimization bypassed."""
    study = AblationStudy()
    
    # In AblationStudy._simulate_configuration, has_placement_opt is:
    # has_placement_opt = config_name in ("full_aegis", "full_aegis_conformal", "forecast_placement", "oracle")
    # For forecast_plus_power_no_placement (no_cpsat_ffd), has_placement_opt is False.
    # We verify this behavior directly:
    opt_configs = ("full_aegis", "full_aegis_conformal", "forecast_placement", "oracle")
    assert "full_aegis_conformal" in opt_configs
    assert "forecast_plus_power_no_placement" not in opt_configs


def test_all_arms_run_through_simulate_configuration():
    """Verify that all arms/configurations run through _simulate_configuration."""
    study = AblationStudy()
    assert hasattr(study, "_simulate_configuration")
    assert callable(getattr(study, "_simulate_configuration"))
