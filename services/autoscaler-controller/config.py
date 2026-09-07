from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class AutoscalerConfig(SharedConfig):
    cooldown_seconds: int = 300
    dead_zone_percent: float = 10.0
    dry_run: bool = False
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = AutoscalerConfig()
