from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class RecommendationConfig(SharedConfig):
    history_days: int = 14
    target_quantile: float = 0.95
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = RecommendationConfig()
