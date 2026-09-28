from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class APIGatewayConfig(SharedConfig):
    rate_limit_per_minute: int = 100
    orchestrator_url: str = "http://orchestrator:8000"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = APIGatewayConfig()
