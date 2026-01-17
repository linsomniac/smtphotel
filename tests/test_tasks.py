"""Tests for background tasks.

AIDEV-NOTE: Tests for the pruning background task. Uses mocked database
and short intervals to test task behavior.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from smtphotel.config import Settings
from smtphotel.tasks.pruning import PruneTask


class TestPruneTask:
    """Tests for the PruneTask class."""

    @pytest.fixture
    def settings(self, monkeypatch: pytest.MonkeyPatch) -> Settings:
        """Create test settings with short prune interval."""
        monkeypatch.setenv("PRUNE_INTERVAL_SECONDS", "10")  # Minimum allowed
        monkeypatch.setenv("MAX_MESSAGE_AGE_HOURS", "24")
        monkeypatch.setenv("MAX_MESSAGE_COUNT", "100")
        monkeypatch.setenv("MAX_STORAGE_MB", "10")
        return Settings()

    @pytest.fixture
    def mock_database(self) -> AsyncMock:
        """Create a mock database for testing."""
        mock = AsyncMock()
        mock.get_total_storage_bytes.return_value = 1000
        mock.prune_by_age.return_value = 0
        mock.prune_by_count.return_value = 0
        mock.prune_by_storage.return_value = 0
        return mock

    @pytest.mark.asyncio
    async def test_task_starts_and_stops(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that prune task can start and stop cleanly."""
        task = PruneTask(settings)
        await task.start(mock_database)

        assert task.is_running

        await task.stop()

        assert not task.is_running

    @pytest.mark.asyncio
    async def test_task_prunes_by_age(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that prune task calls prune_by_age."""
        mock_database.prune_by_age.return_value = 5

        task = PruneTask(settings)
        task.set_database(mock_database)

        # Call _prune_once directly
        await task._prune_once()

        mock_database.prune_by_age.assert_called_once_with(24)

    @pytest.mark.asyncio
    async def test_task_prunes_by_count(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that prune task calls prune_by_count."""
        mock_database.prune_by_count.return_value = 3

        task = PruneTask(settings)
        task.set_database(mock_database)

        await task._prune_once()

        mock_database.prune_by_count.assert_called_once_with(100)

    @pytest.mark.asyncio
    async def test_task_prunes_by_storage(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that prune task calls prune_by_storage."""
        mock_database.prune_by_storage.return_value = 2

        task = PruneTask(settings)
        task.set_database(mock_database)

        await task._prune_once()

        # 10 MB = 10 * 1024 * 1024 bytes
        mock_database.prune_by_storage.assert_called_once_with(10 * 1024 * 1024)

    @pytest.mark.asyncio
    async def test_task_skips_disabled_pruning(
        self, monkeypatch: pytest.MonkeyPatch, mock_database: AsyncMock
    ) -> None:
        """Test that prune task skips disabled pruning strategies."""
        monkeypatch.setenv("PRUNE_INTERVAL_SECONDS", "10")
        monkeypatch.setenv("MAX_MESSAGE_AGE_HOURS", "0")  # Disabled
        monkeypatch.setenv("MAX_MESSAGE_COUNT", "0")  # Disabled
        monkeypatch.setenv("MAX_STORAGE_MB", "0")  # Disabled
        settings = Settings()

        task = PruneTask(settings)
        task.set_database(mock_database)

        await task._prune_once()

        mock_database.prune_by_age.assert_not_called()
        mock_database.prune_by_count.assert_not_called()
        mock_database.prune_by_storage.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_handles_errors(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that prune task continues running after errors."""
        mock_database.prune_by_age.side_effect = Exception("Test error")

        task = PruneTask(settings)
        await task.start(mock_database)

        # Wait for one cycle - the error should not crash the task
        await asyncio.sleep(0.1)

        # Task should still be running despite the error
        assert task.is_running

        await task.stop()

    @pytest.mark.asyncio
    async def test_task_logs_results(
        self,
        settings: Settings,
        mock_database: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that prune task logs when messages are deleted."""
        mock_database.prune_by_age.return_value = 5
        mock_database.get_total_storage_bytes.side_effect = [
            1000,
            500,
        ]  # Before and after

        task = PruneTask(settings)
        task.set_database(mock_database)

        with caplog.at_level("INFO"):
            await task._prune_once()

        assert "deleted 5 messages" in caplog.text
        assert "freed 500 bytes" in caplog.text

    @pytest.mark.asyncio
    async def test_multiple_starts_ignored(
        self, settings: Settings, mock_database: AsyncMock
    ) -> None:
        """Test that starting an already running task is ignored."""
        task = PruneTask(settings)
        await task.start(mock_database)

        # Try to start again
        await task.start(mock_database)

        # Should still have only one task
        assert task.is_running

        await task.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, settings: Settings) -> None:
        """Test that stopping without starting is safe."""
        task = PruneTask(settings)

        # Should not raise
        await task.stop()

        assert not task.is_running


class TestPruneTaskGlobalFunctions:
    """Tests for the global start/stop functions."""

    @pytest.mark.asyncio
    async def test_start_and_stop_prune_task(self) -> None:
        """Test global start/stop functions."""
        from smtphotel.tasks.pruning import start_prune_task, stop_prune_task

        mock_db = AsyncMock()
        mock_db.get_total_storage_bytes.return_value = 0
        mock_db.prune_by_age.return_value = 0
        mock_db.prune_by_count.return_value = 0
        mock_db.prune_by_storage.return_value = 0

        task = await start_prune_task(mock_db)

        assert task.is_running

        await stop_prune_task()

        assert not task.is_running
