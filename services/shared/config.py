from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedConfig(BaseSettings):
    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "aegis"
    postgres_user: str = "admin"
    postgres_password: str = "secret"
    
    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # Telemetry URLs
    prometheus_url: str = "http://prometheus:9090"
    kepler_url: str = "http://kepler:9102"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"
    
    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Auth
    jwt_secret: str = "super-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    
    # Aegis Constants
    control_loop_interval: int = 60
    stale_telemetry_threshold: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = SharedConfig()
