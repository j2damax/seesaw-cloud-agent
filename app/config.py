# config.py
# Pydantic Settings — reads from environment variables / Secret Manager injections.

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    seesaw_api_key: str = ""
    gcs_bucket_name: str = "seesaw-models"
    firestore_project: str = ""
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
