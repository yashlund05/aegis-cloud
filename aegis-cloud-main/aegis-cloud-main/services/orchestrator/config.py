from services.shared.config import SharedConfig
from pydantic_settings import SettingsConfigDict

class OrchestratorConfig(SharedConfig):
    collector_url: str = "http://telemetry-collector:8000"
    predictor_url: str = "http://predictor:8000"
    decision_engine_url: str = "http://decision-engine:8000"
    autoscaler_url: str = "http://autoscaler-controller:8000"
    power_controller_url: str = "http://node-power-controller:8000"
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = OrchestratorConfig()
