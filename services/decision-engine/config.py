"""
Configuration for Decision Engine Service (Phase 5).
"""

from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict


class DecisionEngineConfig(SharedConfig):
    solver_timeout_ms: int = 10000
    enable_ffd_fallback: bool = True
    utilization_max: float = 0.85
    overcommit_ratio: float = 0.10
    min_active_nodes: int = 1
    ha_max_pods_per_node_ratio: float = 0.50

    # Objective weights
    weight_energy: float = 1.0
    weight_scaling_churn: float = 0.5
    weight_slo_headroom: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


config = DecisionEngineConfig()
