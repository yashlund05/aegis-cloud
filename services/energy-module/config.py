from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class EnergyConfig(SharedConfig):
    default_p_idle: float = 50.0
    default_p_max: float = 200.0
    default_alpha: float = 1.0
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = EnergyConfig()
