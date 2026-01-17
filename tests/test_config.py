"""Tests for configuration management."""

import pytest
from pydantic import ValidationError

from smtphotel.config import Settings, get_settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        settings = Settings()
        assert settings.smtp_port == 2525
        assert settings.http_port == 8025
        assert settings.bind_address == "127.0.0.1"
        assert settings.db_path == "/data/smtphotel.db"
        assert settings.max_message_age_hours == 0
        assert settings.max_message_count == 0
        assert settings.prune_interval_seconds == 300
        assert settings.max_message_size_mb == 25
        assert settings.max_connections == 100
        assert settings.smtp_timeout_seconds == 60
        assert settings.rate_limit_per_minute == 0
        assert settings.cors_origins == ""

    def test_env_vars_override_defaults(self) -> None:
        """Test that environment variables override defaults."""
        settings = Settings(
            SMTP_PORT=1025,
            HTTP_PORT=8080,
            BIND_ADDRESS="0.0.0.0",
            DB_PATH="/tmp/test.db",
        )
        assert settings.smtp_port == 1025
        assert settings.http_port == 8080
        assert settings.bind_address == "0.0.0.0"
        assert settings.db_path == "/tmp/test.db"

    def test_max_message_size_bytes(self) -> None:
        """Test max_message_size_bytes property."""
        settings = Settings(MAX_MESSAGE_SIZE_MB=10)
        assert settings.max_message_size_bytes == 10 * 1024 * 1024

    def test_max_storage_bytes(self) -> None:
        """Test max_storage_bytes property."""
        settings = Settings(MAX_STORAGE_MB=100)
        assert settings.max_storage_bytes == 100 * 1024 * 1024

    def test_cors_origins_list_empty(self) -> None:
        """Test cors_origins_list with empty string."""
        settings = Settings(CORS_ORIGINS="")
        assert settings.cors_origins_list == []

    def test_cors_origins_list_single(self) -> None:
        """Test cors_origins_list with single origin."""
        settings = Settings(CORS_ORIGINS="http://localhost:3000")
        assert settings.cors_origins_list == ["http://localhost:3000"]

    def test_cors_origins_list_multiple(self) -> None:
        """Test cors_origins_list with multiple origins."""
        settings = Settings(CORS_ORIGINS="http://localhost:3000, http://localhost:8080")
        assert settings.cors_origins_list == [
            "http://localhost:3000",
            "http://localhost:8080",
        ]

    def test_cors_wildcard_rejected(self) -> None:
        """Test that wildcard CORS origin is rejected."""
        with pytest.raises(ValidationError, match="Wildcard CORS origins"):
            Settings(CORS_ORIGINS="*")

    def test_port_validation(self) -> None:
        """Test port validation."""
        with pytest.raises(ValidationError):
            Settings(SMTP_PORT=0)
        with pytest.raises(ValidationError):
            Settings(SMTP_PORT=70000)

    def test_empty_bind_address_defaults(self) -> None:
        """Test empty bind address defaults to localhost."""
        settings = Settings(BIND_ADDRESS="")
        assert settings.bind_address == "127.0.0.1"

    def test_get_settings_cached(self) -> None:
        """Test that get_settings returns cached instance."""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
