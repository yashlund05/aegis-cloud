from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class PredictorConfig(SharedConfig):
    model_storage_path: str = "/var/lib/aegis/models"
    drift_threshold: float = 0.05
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = PredictorConfig()
