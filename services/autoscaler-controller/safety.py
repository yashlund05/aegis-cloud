class SafetyChecker:
    def __init__(self, dead_zone_percent: float, cooldown_seconds: int):
        self.dead_zone_percent = dead_zone_percent
        self.cooldown_seconds = cooldown_seconds

    def should_scale(self, current_replicas: int, target_replicas: int, last_scaled_at: float) -> bool:
        # TODO: Implement dead zone (+-10%) and cooldown >= 5 min logic
        return True
