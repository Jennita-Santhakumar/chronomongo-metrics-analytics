from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017/?replicaSet=rs0"
    mongo_db: str = "analytics"
    cors_origins: str = "http://localhost:5173"
    ttl_seconds: int = 7_776_000  # 90 days


settings = Settings()
