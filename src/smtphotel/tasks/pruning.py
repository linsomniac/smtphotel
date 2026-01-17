"""Background pruning task for message store management.

AIDEV-NOTE: This module implements a background task that periodically
prunes old messages based on configured limits (age, count, storage).
The task respects graceful shutdown and logs all pruning operations.
"""

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from smtphotel.config import Settings, get_settings

if TYPE_CHECKING:
    from smtphotel.storage.database import Database

logger = logging.getLogger(__name__)


class PruneTask:
    """Background task for periodic message pruning.

    AIDEV-NOTE: This task runs continuously and performs pruning at
    configurable intervals. It handles all three pruning strategies:
    - Age-based: Delete messages older than MAX_MESSAGE_AGE_HOURS
    - Count-based: Keep only MAX_MESSAGE_COUNT most recent messages
    - Storage-based: Delete oldest messages when over MAX_STORAGE_MB
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize pruning task with settings."""
        self.settings = settings or get_settings()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._database: Database | None = None

    def set_database(self, database: "Database") -> None:
        """Set the database instance to use for pruning."""
        self._database = database

    async def start(self, database: "Database | None" = None) -> None:
        """Start the background pruning task.

        Args:
            database: Optional database instance. If not provided,
                      will use the global database instance.
        """
        if database:
            self._database = database

        if self._task is not None:
            logger.warning("Prune task already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Prune task started (interval: %ds, max_age: %dh, max_count: %d, max_storage: %dMB)",
            self.settings.prune_interval_seconds,
            self.settings.max_message_age_hours,
            self.settings.max_message_count,
            self.settings.max_storage_mb,
        )

    async def stop(self) -> None:
        """Stop the background pruning task gracefully."""
        if self._task is None:
            return

        logger.info("Stopping prune task...")
        self._stop_event.set()

        # Wait for task to complete with timeout
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except TimeoutError:
            logger.warning("Prune task did not stop gracefully, cancelling...")
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        self._task = None
        logger.info("Prune task stopped")

    async def _run(self) -> None:
        """Main loop for the pruning task."""
        while not self._stop_event.is_set():
            try:
                await self._prune_once()
            except Exception:
                logger.exception("Error during pruning")

            # Wait for next interval or stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.settings.prune_interval_seconds,
                )
                # If we get here, stop was requested
                break
            except TimeoutError:
                # Normal timeout, continue to next prune
                pass

    async def _prune_once(self) -> None:
        """Perform a single pruning cycle.

        AIDEV-NOTE: This method runs all configured pruning strategies
        in order: age, count, then storage. Each strategy only runs if
        its configuration is non-zero.
        """
        database = self._database
        if database is None:
            # Get global database if not set
            from smtphotel.storage.database import get_database

            database = await get_database()
            self._database = database

        total_deleted = 0
        initial_size = await database.get_total_storage_bytes()

        # Age-based pruning
        if self.settings.max_message_age_hours > 0:
            deleted = await database.prune_by_age(self.settings.max_message_age_hours)
            total_deleted += deleted

        # Count-based pruning
        if self.settings.max_message_count > 0:
            deleted = await database.prune_by_count(self.settings.max_message_count)
            total_deleted += deleted

        # Storage-based pruning
        if self.settings.max_storage_bytes > 0:
            deleted = await database.prune_by_storage(self.settings.max_storage_bytes)
            total_deleted += deleted

        # Log results if anything was deleted
        if total_deleted > 0:
            final_size = await database.get_total_storage_bytes()
            space_freed = initial_size - final_size
            logger.info(
                "Prune cycle complete: deleted %d messages, freed %d bytes",
                total_deleted,
                space_freed,
            )

    @property
    def is_running(self) -> bool:
        """Check if the prune task is currently running."""
        return self._task is not None and not self._task.done()


# Global prune task instance
_prune_task: PruneTask | None = None


async def start_prune_task(database: "Database | None" = None) -> PruneTask:
    """Start the global prune task.

    AIDEV-NOTE: This function manages a singleton prune task instance.
    It's designed to be called during application startup.
    """
    global _prune_task
    if _prune_task is None:
        _prune_task = PruneTask()
    await _prune_task.start(database)
    return _prune_task


async def stop_prune_task() -> None:
    """Stop the global prune task.

    AIDEV-NOTE: Call this during application shutdown to ensure
    graceful cleanup of the background task.
    """
    global _prune_task
    if _prune_task is not None:
        await _prune_task.stop()
        _prune_task = None
