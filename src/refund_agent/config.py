"""Central configuration.

Every tunable business rule lives here so policy changes are a config edit,
not a code hunt.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from the environment or a local `.env` file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    refund_window_days: int = 30
    review_threshold_cents: int = 10000
    running_total_days: int = 30
    timezone: str = "UTC"
    # SecretStr keeps credentials out of reprs and logs.
    database_url: SecretStr | None = None
    # Upper bound on pooled DB connections; each open customer unit holds one.
    db_pool_max_size: int = 10


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, built once because env does not change at runtime."""
    return Settings()
