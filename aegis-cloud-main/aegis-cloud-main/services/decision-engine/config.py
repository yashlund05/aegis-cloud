from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class DecisionEngineConfig(SharedConfig):
    solver_timeout_ms: int = 5000
    enable_ffd_fallback: bool = True
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = DecisionEngineConfig()
