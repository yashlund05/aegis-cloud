class PowerModel:
    """
    Computes the estimated power consumption of a node or component
    based on its utilization.
    """
    def __init__(self, p_idle: float, p_max: float, alpha: float):
        """
        :param p_idle: Idle power consumption in Watts
        :param p_max: Maximum power consumption in Watts
        :param alpha: Non-linear scaling factor (usually >= 1.0)
        """
        self.p_idle = p_idle
        self.p_max = p_max
        self.alpha = alpha

    def compute_power(self, utilization: float) -> float:
        """
        Computes power using the non-linear model:
        P(u) = P_idle + (P_max - P_idle) * u^alpha
        
        :param utilization: Utilization factor between 0.0 (idle) and 1.0 (max)
        :return: Estimated power in Watts
        """
        if utilization < 0.0 or utilization > 1.0:
            raise ValueError(f"Utilization must be between 0.0 and 1.0, got {utilization}")
        
        return self.p_idle + (self.p_max - self.p_idle) * (utilization ** self.alpha)


def compute_power(utilization: float, p_idle: float, p_max: float, alpha: float) -> float:
    """
    Module-level function computing power consumption:
    P(u) = P_idle + (P_max - P_idle) * u^alpha
    """
    model = PowerModel(p_idle=p_idle, p_max=p_max, alpha=alpha)
    return model.compute_power(utilization)


def compute_energy_kwh(power_watts: float, duration_seconds: float) -> float:
    """
    Computes energy in kilowatt-hours (kWh) from power in Watts and duration in seconds.
    """
    return (power_watts * duration_seconds) / (1000.0 * 3600.0)

