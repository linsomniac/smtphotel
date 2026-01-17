"""Configuration management using pydantic-settings."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    AIDEV-NOTE: All configuration is done via environment variables.
    The BIND_ADDRESS defaults to 127.0.0.1 for security - requires explicit
    opt-in to expose to network by setting BIND_ADDRESS=0.0.0.0
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=True,
    )

    # Server ports
    smtp_port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=2525, alias="SMTP_PORT", description="SMTP server port"
    )
    http_port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=8025, alias="HTTP_PORT", description="HTTP server port (API + Web UI)"
    )

    # Network binding - defaults to localhost for security
    bind_address: str = Field(
        default="127.0.0.1",
        alias="BIND_ADDRESS",
        description="Bind address for SMTP and HTTP (use 0.0.0.0 to expose)",
    )

    # Database
    db_path: str = Field(
        default="/data/smtphotel.db",
        alias="DB_PATH",
        description="SQLite database path",
    )

    # Message retention
    max_message_age_hours: Annotated[int, Field(ge=0)] = Field(
        default=0,
        alias="MAX_MESSAGE_AGE_HOURS",
        description="Delete messages older than N hours (0 = disabled)",
    )
    max_message_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        alias="MAX_MESSAGE_COUNT",
        description="Keep only N most recent messages (0 = disabled)",
    )
    prune_interval_seconds: Annotated[int, Field(ge=10)] = Field(
        default=300,
        alias="PRUNE_INTERVAL_SECONDS",
        description="How often to run pruning (5 min default)",
    )

    # Message limits
    max_message_size_mb: Annotated[int, Field(ge=1, le=100)] = Field(
        default=25,
        alias="MAX_MESSAGE_SIZE_MB",
        description="Maximum message size in MB",
    )
    max_storage_mb: Annotated[int, Field(ge=0)] = Field(
        default=0,
        alias="MAX_STORAGE_MB",
        description="Maximum total storage in MB (0 = unlimited)",
    )

    # SMTP abuse controls
    max_connections: Annotated[int, Field(ge=1, le=10000)] = Field(
        default=100,
        alias="MAX_CONNECTIONS",
        description="Maximum concurrent SMTP connections",
    )
    smtp_timeout_seconds: Annotated[int, Field(ge=10, le=600)] = Field(
        default=60,
        alias="SMTP_TIMEOUT_SECONDS",
        description="SMTP connection timeout",
    )
    rate_limit_per_minute: Annotated[int, Field(ge=0)] = Field(
        default=0,
        alias="RATE_LIMIT_PER_MINUTE",
        description="Max messages per IP per minute (0 = disabled)",
    )

    # CORS
    cors_origins: str = Field(
        default="",
        alias="CORS_ORIGINS",
        description="Allowed CORS origins (empty = same-origin only)",
    )

    @field_validator("bind_address")
    @classmethod
    def validate_bind_address(cls, v: str) -> str:
        """Validate bind address is a valid IP or hostname."""
        v = v.strip()
        if not v:
            return "127.0.0.1"
        return v

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """Validate CORS origins - never allow wildcard."""
        if v.strip() == "*":
            raise ValueError(
                "Wildcard CORS origins (*) are not allowed for security. "
                "Please specify explicit origins."
            )
        return v.strip()

    @property
    def max_message_size_bytes(self) -> int:
        """Return max message size in bytes."""
        return self.max_message_size_mb * 1024 * 1024

    @property
    def max_storage_bytes(self) -> int:
        """Return max storage in bytes (0 = unlimited)."""
        return self.max_storage_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list."""
        if not self.cors_origins:
            return []
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    AIDEV-NOTE: This is cached to avoid re-parsing environment variables.
    For testing, you can create Settings instances directly.
    """
    return Settings()
