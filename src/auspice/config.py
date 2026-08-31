"""Runtime configuration.

One settings object, read once, validated at import of the process entry point rather
than scattered ``os.environ`` reads. Anything secret arrives through the environment and
never through a file that git can see.

The pattern here is deliberate: the settings object refuses to construct if a value that
would silently produce wrong behaviour is missing. A crawler with no contact address, or
an extraction run with no API key, should fail at startup rather than halfway through a
400,000 page corpus.
"""

from __future__ import annotations

import functools
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Environment(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class RawStoreBackend(StrEnum):
    local = "local"
    s3 = "s3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUSPICE_",
        env_file=(REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Environment = Environment.development

    # -- Database ----------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://auspice@127.0.0.1:55432/auspice")
    )
    test_database_url: PostgresDsn | None = None
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=50)

    # -- Raw object store --------------------------------------------------
    raw_backend: RawStoreBackend = RawStoreBackend.local
    raw_local_root: Path = Path("data/raw")
    raw_bucket: str = ""
    raw_endpoint_url: str = ""
    raw_access_key_id: str = ""
    raw_secret_access_key: str = ""

    # -- Crawler -----------------------------------------------------------
    crawler_user_agent: str = "AuspiceBot/0.1"
    crawler_contact: str = ""
    crawler_requests_per_minute: int = Field(default=20, ge=1, le=600)
    crawler_timeout_seconds: float = Field(default=45.0, gt=0)
    crawler_max_attempts: int = Field(default=4, ge=1, le=10)

    # -- Language models ---------------------------------------------------
    llm_provider: Literal["anthropic", "openai", "none"] = "none"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_frontier_model: str = ""
    llm_cheap_model: str = ""
    llm_max_attempts: int = Field(default=3, ge=1, le=8)

    # -- Transcription -----------------------------------------------------
    whisper_model: str = "large-v3"
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    ffmpeg_path: str = "ffmpeg"

    # -- API ---------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    """Origins the browser may call the API from.

    Both spellings of the loopback address, because they are the same server and a browser treats them as
    different origins. The default was localhost only while the web app's own default base URL is
    127.0.0.1, so every real cross origin request from the interface failed the same way: the page said the
    API did not answer while the API was running and healthy.

    Nothing caught it for a while because the browser tests stubbed the API at the network layer, so the
    first request to actually cross the origin boundary was the coordinate lookup in site search. Two
    defaults that have to agree and did not, which is the same shape as the connect-src bug in the web
    middleware.
    """
    api_keys: str = ""
    api_trust_forwarded_for: bool = False
    """Whether to believe the X-Forwarded-For header when rate limiting.

    Off by default, and that default matters. A client sets that header freely, so trusting it without a
    proxy in front hands anyone an unlimited allowance by rotating a string. Turn it on only when something
    upstream is guaranteed to overwrite it.
    """

    # -- Ledger ------------------------------------------------------------
    ledger_path: Path = Path("data/ledger")
    ledger_anchor_url: str = ""

    # -- Observability -----------------------------------------------------
    # Both are empty by default and both are fail closed rather than fail open.
    #
    # No DSN means no error tracker is started and no network call leaves the process. A service that
    # reads nothing but public records should not acquire a third party data processor because a
    # default was left on.
    #
    # No metrics token means the /metrics route is not registered at all, rather than registered and
    # answering 401. An unauthenticated metrics endpoint publishes request volumes, error rates and
    # model identity, and a route that does not exist cannot be probed.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    metrics_token: str = ""

    # -- Alert delivery ----------------------------------------------------
    # The default is `log`, which needs no credentials. That is deliberate: an unconfigured
    # deployment that writes every alert to the structured log is observably doing the right thing
    # and can be checked by reading the log. The failure to avoid is a deployment that looks healthy
    # because nothing errored while nothing was sent.
    #
    # Setting the channel to webhook or smtp without its required values raises rather than falling
    # back to the log, because an operator who configured mail wants to hear that it is broken now.
    alert_channel: Literal["log", "webhook", "smtp"] = "log"
    alert_max_delivery_attempts: int = Field(default=5, ge=1, le=50)
    alert_webhook_url: str = ""
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_username: str = ""
    alert_smtp_password: str = ""
    alert_smtp_starttls: bool = True
    alert_sender: str = ""
    alert_fallback_recipient: str = ""
    """Where a mail alert goes when the subscriber is not an email address.

    `watch.subscriber` is documented in the schema as an API key label until billing exists, so it is
    not reliably an address. With this set, such an alert reaches an operator. Without it, the send
    fails loudly and the alert stays in the queue. Neither option silently drops it.
    """

    # -- Paths -------------------------------------------------------------
    registry_path: Path = Path("data/registry")
    labels_path: Path = Path("data/labels")
    artifacts_path: Path = Path("artifacts")

    @field_validator(
        "raw_local_root", "ledger_path", "registry_path", "labels_path", "artifacts_path"
    )
    @classmethod
    def _absolutise(cls, value: Path) -> Path:
        """Relative paths are relative to the repository, not the current directory.

        A CLI invoked from a subdirectory must not write the corpus somewhere new.
        """
        return value if value.is_absolute() else (REPO_ROOT / value)

    @model_validator(mode="after")
    def _check_s3_complete(self) -> Settings:
        if self.raw_backend is RawStoreBackend.s3:
            missing = [
                name
                for name in ("raw_bucket", "raw_access_key_id", "raw_secret_access_key")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    "raw_backend is s3 but these are unset: " + ", ".join(sorted(missing))
                )
        return self

    @model_validator(mode="after")
    def _check_production_hygiene(self) -> Settings:
        if self.env is Environment.production:
            problems: list[str] = []
            if not self.crawler_contact:
                problems.append("crawler_contact must be set: section 15.2 requires an address")
            if self.raw_backend is not RawStoreBackend.s3:
                problems.append("raw_backend must be s3 in production")
            if not self.api_keys:
                problems.append("api_keys must be set: the API is not public")
            if problems:
                raise ValueError("production configuration is incomplete: " + "; ".join(problems))
        return self

    # -- Derived -----------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    def sqlalchemy_url(self, *, test: bool = False) -> str:
        if test:
            if self.test_database_url is None:
                raise RuntimeError(
                    "AUSPICE_TEST_DATABASE_URL is not set. Run "
                    "infra/scripts/bootstrap-postgres.ps1 or point it at a scratch database."
                )
            return str(self.test_database_url)
        return str(self.database_url)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process wide settings. Cached so the environment is read exactly once."""
    return Settings()


def reset_settings_cache() -> None:
    """Only for tests that deliberately change the environment."""
    get_settings.cache_clear()
