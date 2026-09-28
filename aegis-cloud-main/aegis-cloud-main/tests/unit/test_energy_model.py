import pytest
from services.energy_module.power_model import compute_power, compute_energy_kwh

class TestEnergyModel:
    def test_idle_power(self):
        """At zero utilization, power should equal P_idle."""
        power = compute_power(0.0, p_idle=100.0, p_max=300.0, alpha=1.5)
        assert power == pytest.approx(100.0)

    def test_max_power(self):
        """At full utilization, power should equal P_max."""
        power = compute_power(1.0, p_idle=100.0, p_max=300.0, alpha=1.5)
        assert power == pytest.approx(300.0)

    def test_mid_utilization(self):
        """At 50% utilization with alpha=2, power should be P_idle + 0.25*(P_max-P_idle)."""
        power = compute_power(0.5, p_idle=100.0, p_max=300.0, alpha=2.0)
        expected = 100.0 + (300.0 - 100.0) * (0.5 ** 2.0)
        assert power == pytest.approx(expected)

    def test_power_increases_with_utilization(self):
        powers = [compute_power(u, 100.0, 300.0, 1.5) for u in [0.0, 0.25, 0.5, 0.75, 1.0]]
        for i in range(len(powers) - 1):
            assert powers[i] < powers[i + 1]

    def test_energy_kwh_calculation(self):
        """1 hour at 200W = 0.2 kWh."""
        kwh = compute_energy_kwh(power_watts=200.0, duration_seconds=3600)
        assert kwh == pytest.approx(0.2)

    def test_invalid_utilization_raises(self):
        with pytest.raises(ValueError):
            compute_power(-0.1, 100.0, 300.0, 1.5)
        with pytest.raises(ValueError):
            compute_power(1.1, 100.0, 300.0, 1.5)
