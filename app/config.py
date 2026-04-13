# config.py
# Pydantic Settings — reads from environment variables / Secret Manager injections.

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    gemini_api_key: str = ""
    seesaw_api_key: str = ""
    gcs_bucket_name: str = "seesaw-models"
    firestore_project: str = ""
    app_version: str = "1.0.0"


settings = Settings()
