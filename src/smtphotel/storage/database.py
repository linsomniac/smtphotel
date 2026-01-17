"""Database initialization and operations.

AIDEV-NOTE: This module uses aiosqlite for async database operations.
The database is configured with WAL mode for better concurrency and
busy_timeout to handle concurrent access gracefully.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from smtphotel.config import Settings, get_settings
from smtphotel.storage.models import (
    Attachment,
    AttachmentCreate,
    AttachmentWithContent,
    Message,
    MessageCreate,
    MessageRaw,
    MessageSummary,
)

logger = logging.getLogger(__name__)

# SQL schema for database initialization
SCHEMA = """
-- Messages table
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    received_at TIMESTAMP NOT NULL,
    mail_from TEXT NOT NULL,
    rcpt_to TEXT NOT NULL,  -- JSON array
    subject TEXT NOT NULL DEFAULT '',
    headers TEXT NOT NULL DEFAULT '{}',  -- JSON object
    body_text TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    raw BLOB NOT NULL,
    size_bytes INTEGER NOT NULL
);

-- Attachments table
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_mail_from ON messages(mail_from);
CREATE INDEX IF NOT EXISTS idx_messages_subject ON messages(subject);
CREATE INDEX IF NOT EXISTS idx_attachments_message_id ON attachments(message_id);
"""


class Database:
    """Async database interface for smtphotel.

    AIDEV-NOTE: This class manages the SQLite connection pool and provides
    high-level operations for message and attachment storage.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize database with settings."""
        self.settings = settings or get_settings()
        self._db_path = self.settings.db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Initialize database connection and schema."""
        # Ensure directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._connection = await aiosqlite.connect(self._db_path)
        self._connection.row_factory = aiosqlite.Row

        # Configure SQLite for better concurrency
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA busy_timeout=5000")
        await self._connection.execute("PRAGMA foreign_keys=ON")

        # Initialize schema
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()

        logger.info("Database initialized at %s", self._db_path)

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager for database transactions."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        try:
            yield self._connection
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise

    # Message operations

    async def store_message(
        self, message: MessageCreate, attachments: list[AttachmentCreate] | None = None
    ) -> str:
        """Store a message and its attachments.

        Returns the message ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self.transaction():
            await self._connection.execute(
                """
                INSERT INTO messages (id, received_at, mail_from, rcpt_to, subject,
                                      headers, body_text, body_html, raw, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.received_at.isoformat(),
                    message.mail_from,
                    json.dumps(message.rcpt_to),
                    message.subject,
                    json.dumps(message.headers),
                    message.body_text,
                    message.body_html,
                    message.raw,
                    message.size_bytes,
                ),
            )

            if attachments:
                for att in attachments:
                    await self._connection.execute(
                        """
                        INSERT INTO attachments (id, message_id, filename,
                                                 content_type, size_bytes, content)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            att.id,
                            att.message_id,
                            att.filename,
                            att.content_type,
                            att.size_bytes,
                            att.content,
                        ),
                    )

        logger.info(
            "Stored message %s from %s (%d bytes, %d attachments)",
            message.id,
            message.mail_from,
            message.size_bytes,
            len(attachments) if attachments else 0,
        )
        return message.id

    async def get_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        sort_by: str = "received_at",
        sort_desc: bool = True,
    ) -> tuple[list[MessageSummary], int]:
        """Get paginated list of messages.

        Returns tuple of (messages, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Validate sort column to prevent SQL injection
        allowed_sort = {"received_at", "mail_from", "subject", "size_bytes"}
        if sort_by not in allowed_sort:
            sort_by = "received_at"

        sort_order = "DESC" if sort_desc else "ASC"

        # Build query with optional search
        base_query = "FROM messages m"
        params: list[str | int] = []

        if search:
            base_query += """
                WHERE m.mail_from LIKE ?
                OR m.subject LIKE ?
                OR EXISTS (SELECT 1 FROM json_each(m.rcpt_to) WHERE value LIKE ?)
            """
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        # Get total count
        count_query = f"SELECT COUNT(*) {base_query}"
        async with self._connection.execute(count_query, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        # Get messages with attachment indicator
        # AIDEV-NOTE: We use a subquery to check for attachments to avoid JOIN complexity
        select_query = f"""
            SELECT m.id, m.received_at, m.mail_from, m.rcpt_to, m.subject, m.size_bytes,
                   EXISTS(SELECT 1 FROM attachments a WHERE a.message_id = m.id) as has_attachments
            {base_query}
            ORDER BY m.{sort_by} {sort_order}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        messages = []
        async with self._connection.execute(select_query, params) as cursor:
            async for row in cursor:
                messages.append(
                    MessageSummary(
                        id=row["id"],
                        received_at=row["received_at"],
                        mail_from=row["mail_from"],
                        rcpt_to=json.loads(row["rcpt_to"]),
                        subject=row["subject"],
                        size_bytes=row["size_bytes"],
                        has_attachments=bool(row["has_attachments"]),
                    )
                )

        return messages, total

    async def get_message(self, message_id: str) -> Message | None:
        """Get a single message with its attachments."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            """
            SELECT id, received_at, mail_from, rcpt_to, subject,
                   headers, body_text, body_html, size_bytes
            FROM messages WHERE id = ?
            """,
            (message_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

            # Get attachments
            attachments = []
            async with self._connection.execute(
                """
                SELECT id, message_id, filename, content_type, size_bytes
                FROM attachments WHERE message_id = ?
                """,
                (message_id,),
            ) as att_cursor:
                async for att_row in att_cursor:
                    attachments.append(
                        Attachment(
                            id=att_row["id"],
                            message_id=att_row["message_id"],
                            filename=att_row["filename"],
                            content_type=att_row["content_type"],
                            size_bytes=att_row["size_bytes"],
                        )
                    )

            return Message(
                id=row["id"],
                received_at=row["received_at"],
                mail_from=row["mail_from"],
                rcpt_to=json.loads(row["rcpt_to"]),
                subject=row["subject"],
                headers=json.loads(row["headers"]),
                body_text=row["body_text"],
                body_html=row["body_html"],
                size_bytes=row["size_bytes"],
                attachments=attachments,
            )

    async def get_message_raw(self, message_id: str) -> MessageRaw | None:
        """Get raw message content."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            "SELECT id, raw FROM messages WHERE id = ?",
            (message_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return MessageRaw(id=row["id"], raw=row["raw"])

    async def get_attachment(self, attachment_id: str) -> AttachmentWithContent | None:
        """Get attachment with content."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            """
            SELECT id, message_id, filename, content_type, size_bytes, content
            FROM attachments WHERE id = ?
            """,
            (attachment_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return AttachmentWithContent(
                id=row["id"],
                message_id=row["message_id"],
                filename=row["filename"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                content=row["content"],
            )

    async def get_message_attachments(self, message_id: str) -> list[Attachment]:
        """Get all attachments for a message (metadata only)."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        attachments = []
        async with self._connection.execute(
            """
            SELECT id, message_id, filename, content_type, size_bytes
            FROM attachments WHERE message_id = ?
            """,
            (message_id,),
        ) as cursor:
            async for row in cursor:
                attachments.append(
                    Attachment(
                        id=row["id"],
                        message_id=row["message_id"],
                        filename=row["filename"],
                        content_type=row["content_type"],
                        size_bytes=row["size_bytes"],
                    )
                )
        return attachments

    async def delete_message(self, message_id: str) -> bool:
        """Delete a message and its attachments.

        Returns True if message was deleted, False if not found.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self.transaction():
            # Attachments are deleted via CASCADE
            cursor = await self._connection.execute(
                "DELETE FROM messages WHERE id = ?",
                (message_id,),
            )
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Deleted message %s", message_id)
        return deleted

    async def delete_all_messages(self) -> int:
        """Delete all messages and attachments.

        Returns count of deleted messages.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self.transaction():
            # Get count first
            async with self._connection.execute(
                "SELECT COUNT(*) FROM messages"
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

            # Delete all (attachments cascade)
            await self._connection.execute("DELETE FROM messages")

        logger.info("Deleted all messages (%d total)", count)
        return count

    # Pruning operations

    async def prune_by_age(self, max_age_hours: int) -> int:
        """Delete messages older than max_age_hours.

        Returns count of deleted messages.
        """
        if not self._connection or max_age_hours <= 0:
            return 0

        async with self.transaction():
            cursor = await self._connection.execute(
                """
                DELETE FROM messages
                WHERE datetime(received_at) < datetime('now', ? || ' hours')
                """,
                (f"-{max_age_hours}",),
            )
            deleted = cursor.rowcount

        if deleted > 0:
            logger.info(
                "Pruned %d messages older than %d hours", deleted, max_age_hours
            )
        return deleted

    async def prune_by_count(self, max_count: int) -> int:
        """Keep only the most recent max_count messages.

        Returns count of deleted messages.
        """
        if not self._connection or max_count <= 0:
            return 0

        async with self.transaction():
            # Delete messages beyond the limit, keeping the most recent
            cursor = await self._connection.execute(
                """
                DELETE FROM messages WHERE id NOT IN (
                    SELECT id FROM messages ORDER BY received_at DESC LIMIT ?
                )
                """,
                (max_count,),
            )
            deleted = cursor.rowcount

        if deleted > 0:
            logger.info(
                "Pruned %d messages to maintain max count of %d", deleted, max_count
            )
        return deleted

    async def prune_by_storage(self, max_storage_bytes: int) -> int:
        """Delete oldest messages to stay under storage limit.

        Returns count of deleted messages.
        """
        if not self._connection or max_storage_bytes <= 0:
            return 0

        # Get current storage usage
        current_size = await self.get_total_storage_bytes()
        if current_size <= max_storage_bytes:
            return 0

        deleted = 0
        async with self.transaction():
            # Delete oldest messages until under limit
            while current_size > max_storage_bytes:
                # Get oldest message
                async with self._connection.execute(
                    "SELECT id, size_bytes FROM messages ORDER BY received_at ASC LIMIT 1"
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        break

                    await self._connection.execute(
                        "DELETE FROM messages WHERE id = ?", (row["id"],)
                    )
                    current_size -= row["size_bytes"]
                    deleted += 1

        if deleted > 0:
            logger.info(
                "Pruned %d messages to maintain storage limit of %d bytes",
                deleted,
                max_storage_bytes,
            )
        return deleted

    # Statistics operations

    async def get_message_count(self) -> int:
        """Get total number of messages."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute("SELECT COUNT(*) FROM messages") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_total_storage_bytes(self) -> int:
        """Get total storage used by messages and attachments."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            """
            SELECT COALESCE(SUM(size_bytes), 0) +
                   (SELECT COALESCE(SUM(size_bytes), 0) FROM attachments)
            FROM messages
            """
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_oldest_message_time(self) -> str | None:
        """Get timestamp of oldest message."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            "SELECT received_at FROM messages ORDER BY received_at ASC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["received_at"] if row else None

    async def get_newest_message_time(self) -> str | None:
        """Get timestamp of newest message."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute(
            "SELECT received_at FROM messages ORDER BY received_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["received_at"] if row else None

    async def vacuum(self) -> None:
        """Run VACUUM to reclaim disk space."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        await self._connection.execute("VACUUM")
        logger.info("Database vacuumed")

    async def integrity_check(self) -> bool:
        """Run integrity check on database.

        Returns True if database is healthy.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._connection.execute("PRAGMA integrity_check") as cursor:
            row = await cursor.fetchone()
            is_ok = row[0] == "ok" if row else False
            if not is_ok:
                logger.error(
                    "Database integrity check failed: %s", row[0] if row else "unknown"
                )
            return is_ok


# Global database instance
_db: Database | None = None


async def get_database() -> Database:
    """Get or create the global database instance.

    AIDEV-NOTE: This is the main entry point for database access.
    The database is lazily initialized on first access.
    """
    global _db
    if _db is None:
        _db = Database()
        await _db.connect()
    return _db


async def close_database() -> None:
    """Close the global database instance."""
    global _db
    if _db is not None:
        await _db.disconnect()
        _db = None
