from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class TelemetryConfig(SharedConfig):
    promql_timeout: int = 10
    feature_store_ttl: int = 3600
    outlier_percentile: float = 99.9
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = TelemetryConfig()
