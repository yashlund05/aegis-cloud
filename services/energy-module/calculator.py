class EnergyCalculator:
    def compute_kwh(self, power_watts: float, duration_hours: float) -> float:
        # TODO: integrate over time for kWh
        return (power_watts / 1000.0) * duration_hours
