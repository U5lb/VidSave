from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVER_URL: SecretStr
    TELEGRAM_API_URL: str
    BOT_TOKEN: SecretStr
    BOT_USERNAME: str = "__CheangemeBot__"

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_file_encoding="utf-8"
    )


settings = Settings(**{})
