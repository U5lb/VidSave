from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    DB_URL: str
    WEB_APP_URL: str
    MAIN_PHOTO_ID: str = (
        "https://raw.githubusercontent.com/u5lb/VidSave/main/backend/assets/avatar.jpg"
    )
    WORKER_TOKEN: SecretStr
    BOT_USERNAME: str = "vidsave_bot"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings(**{})
