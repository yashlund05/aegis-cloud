import logging
import time

logger = logging.getLogger(__name__)

class SafetyChecker:
    def __init__(self, dead_zone_percent: float = 0.10, cooldown_seconds: int = 300):
        self.dead_zone_percent = dead_zone_percent
        self.cooldown_seconds = cooldown_seconds

    def should_scale(self, current_replicas: int, target_replicas: int, last_scaled_at: float) -> bool:
        """
        Determines whether scaling should proceed based on:
        1. Dead-zone: Skip if change is within ±10% of current replicas.
        2. Cooldown: Skip if last scale event was less than 5 minutes ago.
        """
        # Cooldown check (>= 5 minutes since last scale)
        elapsed = time.time() - last_scaled_at
        if elapsed < self.cooldown_seconds:
            logger.info(
                f"Cooldown active: {elapsed:.0f}s elapsed, "
                f"need {self.cooldown_seconds}s. Skipping scale."
            )
            return False

        # Dead-zone check (±10%)
        if current_replicas == 0:
            return target_replicas > 0

        change_pct = abs(target_replicas - current_replicas) / current_replicas
        if change_pct <= self.dead_zone_percent:
            logger.info(
                f"Within dead-zone: {change_pct:.1%} change "
                f"(threshold: {self.dead_zone_percent:.1%}). Skipping scale."
            )
            return False

        return True
