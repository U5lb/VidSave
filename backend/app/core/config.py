from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    DB_URL: str
    WEB_APP_URL: str
    MAIN_PHOTO_ID: str | None = None
    WORKER_TOKEN: SecretStr

    model_config = SettingsConfigDict(
        env_file="../.env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings(**{})
