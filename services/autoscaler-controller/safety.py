"""
Safety enforcement module for Aegis Autoscaler Controller (Phase 7).
Protects cluster stability via:
1. Dead zone threshold (+-10%) to prevent scaling oscillations / flapping.
2. Cooldown period (>= 300s / 5 min) between scaling mutations.
3. Max step clamping (default 10 replicas per cycle).
"""

import time
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class SafetyChecker:
    """
    Enforces dead zone and cooldown constraints to prevent autoscaling thrashing.
    """

    def __init__(
        self,
        dead_zone_percent: float = 0.10,
        cooldown_seconds: int = 300,
        max_scale_step: int = 10,
    ):
        # Normalize dead zone percentage to fraction (e.g. 10.0 -> 0.10)
        self.dead_zone_percent = (
            dead_zone_percent / 100.0 if dead_zone_percent > 1.0 else dead_zone_percent
        )
        self.cooldown_seconds = cooldown_seconds
        self.max_scale_step = max_scale_step

    def should_scale(
        self,
        current_replicas: int,
        target_replicas: int,
        last_scaled_at: Optional[float] = None,
        now: Optional[float] = None,
        min_replicas: int = 1,
        max_replicas: int = 50,
    ) -> Tuple[bool, str, int]:
        """
        Evaluates whether scaling should proceed.
        Returns:
            (can_scale: bool, reason: str, approved_target: int)
        """
        current_time = now if now is not None else time.time()

        # 0. Enforce min/max replica clamping
        bounded_target = max(min_replicas, min(max_replicas, target_replicas))

        # 1. No-op check
        if current_replicas == bounded_target:
            return False, "Target replicas matches current state; no change needed.", current_replicas

        # 2. Cooldown Enforcement
        if last_scaled_at is not None:
            elapsed = current_time - last_scaled_at
            if elapsed < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - elapsed)
                return (
                    False,
                    f"Cooldown active: {remaining}s remaining before next scale action.",
                    current_replicas,
                )

        # 3. Dead Zone Enforcement (+- 10%)
        # If current is 0, allow scaling up immediately
        if current_replicas > 0:
            delta = abs(bounded_target - current_replicas)
            fractional_change = delta / float(current_replicas)
            if fractional_change < self.dead_zone_percent:
                return (
                    False,
                    f"Change of {fractional_change * 100:.1f}% is within the dead zone (+-{self.dead_zone_percent * 100:.0f}%).",
                    current_replicas,
                )

        # 4. Max Step Clamping to avoid massive surge spikes
        delta = bounded_target - current_replicas
        if abs(delta) > self.max_scale_step:
            step = self.max_scale_step if delta > 0 else -self.max_scale_step
            clamped_target = current_replicas + step
            return (
                True,
                f"Scale approved with step dampening ({current_replicas} -> {clamped_target}, original target {bounded_target}).",
                clamped_target,
            )

        return (
            True,
            f"Scale approved ({current_replicas} -> {bounded_target}).",
            bounded_target,
        )
