from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""
    fred_api_key: str = ""
    twelve_data_api_key: str = ""
    finnhub_api_key: str = ""
    postgres_password: str = "change-me"
    database_url: str = "sqlite:///./doublem.db"
    log_level: str = "INFO"
    watchlist: str = "SPY,QQQ,IWM"
    quote_refresh_minutes: int = 30
    daily_refresh_hour_utc: int = 22
    provider_daily_budget: int = 700
    http_timeout_seconds: int = 15
    default_currency: str = "USD"

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(v.strip()) for v in self.telegram_allowed_user_ids.split(",") if v.strip()}

    @property
    def symbols(self) -> list[str]:
        return sorted({s.strip().upper() for s in self.watchlist.split(",") if s.strip()})


settings = Settings()
