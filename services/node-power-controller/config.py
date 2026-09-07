from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class NodePowerConfig(SharedConfig):
    min_active_nodes: int = 2
    buffer_capacity_percent: float = 15.0
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = NodePowerConfig()
