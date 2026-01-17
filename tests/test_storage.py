"""Tests for database storage operations."""

from datetime import UTC, datetime, timedelta

from smtphotel.storage.database import Database
from smtphotel.storage.models import AttachmentCreate, MessageCreate
from tests.conftest import create_message


class TestDatabaseConnection:
    """Tests for database connection and initialization."""

    async def test_connect_creates_database(self, db: Database) -> None:
        """Test that connect creates the database file."""
        # db fixture already connected
        assert db._connection is not None

    async def test_disconnect_closes_connection(self, db: Database) -> None:
        """Test that disconnect closes the connection."""
        await db.disconnect()
        assert db._connection is None

    async def test_transaction_commits_on_success(self, db: Database) -> None:
        """Test that transaction commits on success."""
        async with db.transaction():
            pass  # No error
        # Should not raise

    async def test_schema_creates_tables(self, db: Database) -> None:
        """Test that schema creates required tables."""
        assert db._connection is not None
        async with db._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] async for row in cursor}

        assert "messages" in tables
        assert "attachments" in tables


class TestMessageStorage:
    """Tests for message storage operations."""

    async def test_store_message(
        self, db: Database, sample_message: MessageCreate
    ) -> None:
        """Test storing a message."""
        msg_id = await db.store_message(sample_message)
        assert msg_id == sample_message.id

    async def test_get_message(
        self, db: Database, sample_message: MessageCreate
    ) -> None:
        """Test retrieving a stored message."""
        await db.store_message(sample_message)
        message = await db.get_message(sample_message.id)

        assert message is not None
        assert message.id == sample_message.id
        assert message.mail_from == sample_message.mail_from
        assert message.rcpt_to == sample_message.rcpt_to
        assert message.subject == sample_message.subject
        assert message.body_text == sample_message.body_text

    async def test_get_message_not_found(self, db: Database) -> None:
        """Test retrieving a non-existent message."""
        message = await db.get_message("non-existent-id")
        assert message is None

    async def test_get_message_raw(
        self, db: Database, sample_message: MessageCreate
    ) -> None:
        """Test retrieving raw message content."""
        await db.store_message(sample_message)
        raw = await db.get_message_raw(sample_message.id)

        assert raw is not None
        assert raw.id == sample_message.id
        assert raw.raw == sample_message.raw

    async def test_get_messages_pagination(self, db: Database) -> None:
        """Test message list pagination."""
        # Create multiple messages
        for i in range(10):
            msg = create_message(subject=f"Message {i}")
            await db.store_message(msg)

        # Get first page
        messages, total = await db.get_messages(limit=3, offset=0)
        assert len(messages) == 3
        assert total == 10

        # Get second page
        messages, total = await db.get_messages(limit=3, offset=3)
        assert len(messages) == 3
        assert total == 10

    async def test_get_messages_search(self, db: Database) -> None:
        """Test message search."""
        msg1 = create_message(subject="Important message", mail_from="alice@test.com")
        msg2 = create_message(subject="Regular stuff", mail_from="bob@test.com")
        await db.store_message(msg1)
        await db.store_message(msg2)

        # Search by subject
        messages, total = await db.get_messages(search="Important")
        assert total == 1
        assert messages[0].subject == "Important message"

        # Search by sender
        messages, total = await db.get_messages(search="alice")
        assert total == 1
        assert messages[0].mail_from == "alice@test.com"

    async def test_get_messages_sort(self, db: Database) -> None:
        """Test message sorting."""
        msg1 = create_message(subject="AAA")
        msg2 = create_message(subject="ZZZ")
        await db.store_message(msg1)
        await db.store_message(msg2)

        # Sort by subject ascending
        messages, _ = await db.get_messages(sort_by="subject", sort_desc=False)
        assert messages[0].subject == "AAA"
        assert messages[1].subject == "ZZZ"

        # Sort by subject descending
        messages, _ = await db.get_messages(sort_by="subject", sort_desc=True)
        assert messages[0].subject == "ZZZ"
        assert messages[1].subject == "AAA"

    async def test_delete_message(
        self, db: Database, sample_message: MessageCreate
    ) -> None:
        """Test deleting a message."""
        await db.store_message(sample_message)
        deleted = await db.delete_message(sample_message.id)
        assert deleted is True

        message = await db.get_message(sample_message.id)
        assert message is None

    async def test_delete_message_not_found(self, db: Database) -> None:
        """Test deleting a non-existent message."""
        deleted = await db.delete_message("non-existent-id")
        assert deleted is False

    async def test_delete_all_messages(self, db: Database) -> None:
        """Test deleting all messages."""
        for i in range(5):
            msg = create_message(subject=f"Message {i}")
            await db.store_message(msg)

        count = await db.delete_all_messages()
        assert count == 5

        messages, total = await db.get_messages()
        assert total == 0


class TestAttachmentStorage:
    """Tests for attachment storage operations."""

    async def test_store_message_with_attachment(
        self,
        db: Database,
        sample_message: MessageCreate,
        sample_attachment: AttachmentCreate,
    ) -> None:
        """Test storing a message with attachment."""
        await db.store_message(sample_message, [sample_attachment])

        message = await db.get_message(sample_message.id)
        assert message is not None
        assert len(message.attachments) == 1
        assert message.attachments[0].filename == "test.txt"

    async def test_get_attachment(
        self,
        db: Database,
        sample_message: MessageCreate,
        sample_attachment: AttachmentCreate,
    ) -> None:
        """Test retrieving an attachment with content."""
        await db.store_message(sample_message, [sample_attachment])

        att = await db.get_attachment(sample_attachment.id)
        assert att is not None
        assert att.filename == "test.txt"
        assert att.content == b"Hello World!"

    async def test_get_attachment_not_found(self, db: Database) -> None:
        """Test retrieving a non-existent attachment."""
        att = await db.get_attachment("non-existent-id")
        assert att is None

    async def test_get_message_attachments(
        self,
        db: Database,
        sample_message: MessageCreate,
    ) -> None:
        """Test listing attachments for a message."""
        att1 = AttachmentCreate(
            id="att1",
            message_id=sample_message.id,
            filename="file1.txt",
            content_type="text/plain",
            size_bytes=5,
            content=b"hello",
        )
        att2 = AttachmentCreate(
            id="att2",
            message_id=sample_message.id,
            filename="file2.pdf",
            content_type="application/pdf",
            size_bytes=10,
            content=b"pdf-content",
        )
        await db.store_message(sample_message, [att1, att2])

        attachments = await db.get_message_attachments(sample_message.id)
        assert len(attachments) == 2
        filenames = {att.filename for att in attachments}
        assert filenames == {"file1.txt", "file2.pdf"}

    async def test_delete_message_cascades_to_attachments(
        self,
        db: Database,
        sample_message: MessageCreate,
        sample_attachment: AttachmentCreate,
    ) -> None:
        """Test that deleting a message also deletes attachments."""
        await db.store_message(sample_message, [sample_attachment])
        await db.delete_message(sample_message.id)

        att = await db.get_attachment(sample_attachment.id)
        assert att is None


class TestPruning:
    """Tests for message pruning operations."""

    async def test_prune_by_age(self, db: Database) -> None:
        """Test pruning messages by age."""
        # Create old message
        old_msg = create_message(
            subject="Old message",
            received_at=datetime.now(UTC) - timedelta(hours=25),
        )
        # Create recent message
        new_msg = create_message(
            subject="New message",
            received_at=datetime.now(UTC),
        )
        await db.store_message(old_msg)
        await db.store_message(new_msg)

        deleted = await db.prune_by_age(24)
        assert deleted == 1

        messages, total = await db.get_messages()
        assert total == 1
        assert messages[0].subject == "New message"

    async def test_prune_by_count(self, db: Database) -> None:
        """Test pruning messages by count."""
        # Create messages with different timestamps
        for i in range(5):
            msg = create_message(
                subject=f"Message {i}",
                received_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            await db.store_message(msg)

        # Keep only 2 most recent
        deleted = await db.prune_by_count(2)
        assert deleted == 3

        messages, total = await db.get_messages()
        assert total == 2

    async def test_prune_by_storage(self, db: Database) -> None:
        """Test pruning messages by storage limit."""
        # Create messages with known sizes
        for i in range(5):
            msg = create_message(
                subject=f"Message {i}",
                received_at=datetime.now(UTC) + timedelta(seconds=i),
            )
            await db.store_message(msg)

        # Get current storage
        storage = await db.get_total_storage_bytes()

        # Set limit to about half
        deleted = await db.prune_by_storage(storage // 2)
        assert deleted > 0

        new_storage = await db.get_total_storage_bytes()
        assert new_storage <= storage // 2

    async def test_prune_disabled_with_zero(self, db: Database) -> None:
        """Test that pruning is disabled when limit is 0."""
        msg = create_message()
        await db.store_message(msg)

        deleted_age = await db.prune_by_age(0)
        deleted_count = await db.prune_by_count(0)
        deleted_storage = await db.prune_by_storage(0)

        assert deleted_age == 0
        assert deleted_count == 0
        assert deleted_storage == 0

        count = await db.get_message_count()
        assert count == 1


class TestStatistics:
    """Tests for statistics operations."""

    async def test_get_message_count(self, db: Database) -> None:
        """Test getting message count."""
        count = await db.get_message_count()
        assert count == 0

        for _ in range(3):
            msg = create_message()
            await db.store_message(msg)

        count = await db.get_message_count()
        assert count == 3

    async def test_get_total_storage_bytes(
        self, db: Database, sample_message: MessageCreate
    ) -> None:
        """Test getting total storage bytes."""
        initial = await db.get_total_storage_bytes()
        assert initial == 0

        await db.store_message(sample_message)

        storage = await db.get_total_storage_bytes()
        assert storage == sample_message.size_bytes

    async def test_get_oldest_newest_message_time(self, db: Database) -> None:
        """Test getting oldest and newest message times."""
        # No messages
        oldest = await db.get_oldest_message_time()
        newest = await db.get_newest_message_time()
        assert oldest is None
        assert newest is None

        # Add messages with different times
        old_time = datetime.now(UTC) - timedelta(hours=10)
        new_time = datetime.now(UTC)

        old_msg = create_message(received_at=old_time)
        new_msg = create_message(received_at=new_time)
        await db.store_message(old_msg)
        await db.store_message(new_msg)

        oldest = await db.get_oldest_message_time()
        newest = await db.get_newest_message_time()
        assert oldest is not None
        assert newest is not None

    async def test_vacuum(self, db: Database, sample_message: MessageCreate) -> None:
        """Test database vacuum."""
        await db.store_message(sample_message)
        await db.delete_message(sample_message.id)

        # Should not raise
        await db.vacuum()

    async def test_integrity_check(self, db: Database) -> None:
        """Test database integrity check."""
        is_healthy = await db.integrity_check()
        assert is_healthy is True
