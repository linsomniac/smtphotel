"""Tests for REST API."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from smtphotel.config import Settings
from smtphotel.main import create_app
from smtphotel.storage.database import Database
from smtphotel.storage.models import AttachmentCreate, MessageCreate


@pytest.fixture
def api_settings(tmp_path: Path) -> Settings:
    """Create settings for API testing."""
    return Settings(
        SMTP_PORT=12527,
        HTTP_PORT=18027,
        DB_PATH=str(tmp_path / "api_test.db"),
        BIND_ADDRESS="127.0.0.1",
    )


@pytest_asyncio.fixture
async def db(api_settings: Settings) -> Database:
    """Create a test database instance."""
    database = Database(api_settings)
    await database.connect()
    yield database
    await database.disconnect()


@pytest_asyncio.fixture
async def client(api_settings: Settings, db: Database) -> AsyncClient:
    """Create an HTTP client for testing the API."""
    # Patch the global database instance directly
    import smtphotel.storage.database as db_module

    # Store original and set our test database
    original_db = db_module._db
    db_module._db = db

    app = create_app(api_settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore original
    db_module._db = original_db


def create_test_message(
    msg_id: str | None = None,
    subject: str = "Test Subject",
    mail_from: str = "sender@test.com",
    rcpt_to: list[str] | None = None,
) -> MessageCreate:
    """Create a test message."""
    if msg_id is None:
        msg_id = str(uuid4())
    if rcpt_to is None:
        rcpt_to = ["recipient@test.com"]

    raw = f"""From: {mail_from}
To: {", ".join(rcpt_to)}
Subject: {subject}

Test body
""".encode()

    return MessageCreate(
        id=msg_id,
        received_at=datetime.now(UTC),
        mail_from=mail_from,
        rcpt_to=rcpt_to,
        subject=subject,
        headers={
            "From": [mail_from],
            "To": rcpt_to,
            "Subject": [subject],
        },
        body_text="Test body",
        body_html="<p>Test body</p>",
        raw=raw,
        size_bytes=len(raw),
    )


class TestMessageEndpoints:
    """Tests for message API endpoints."""

    async def test_list_messages_empty(self, client: AsyncClient) -> None:
        """Test listing messages when empty."""
        response = await client.get("/api/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["total"] == 0

    async def test_list_messages(self, client: AsyncClient, db: Database) -> None:
        """Test listing messages."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.get("/api/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["messages"]) == 1
        assert data["messages"][0]["subject"] == "Test Subject"

    async def test_list_messages_pagination(
        self, client: AsyncClient, db: Database
    ) -> None:
        """Test message list pagination."""
        for i in range(5):
            msg = create_test_message(subject=f"Message {i}")
            await db.store_message(msg)

        response = await client.get("/api/messages?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["messages"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0

    async def test_list_messages_search(
        self, client: AsyncClient, db: Database
    ) -> None:
        """Test message list search."""
        msg1 = create_test_message(subject="Important message")
        msg2 = create_test_message(subject="Regular stuff")
        await db.store_message(msg1)
        await db.store_message(msg2)

        response = await client.get("/api/messages?search=Important")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["messages"][0]["subject"] == "Important message"

    async def test_get_message(self, client: AsyncClient, db: Database) -> None:
        """Test getting a single message."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.get(f"/api/messages/{msg.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == msg.id
        assert data["subject"] == msg.subject
        assert data["body_text"] == msg.body_text
        assert data["body_html"] == msg.body_html

    async def test_get_message_not_found(self, client: AsyncClient) -> None:
        """Test getting a non-existent message."""
        response = await client.get("/api/messages/non-existent-id")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_get_message_raw(self, client: AsyncClient, db: Database) -> None:
        """Test getting raw message."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.get(f"/api/messages/{msg.id}/raw")
        assert response.status_code == 200
        assert response.headers["content-type"] == "message/rfc822"
        assert b"From: sender@test.com" in response.content

    async def test_delete_message(self, client: AsyncClient, db: Database) -> None:
        """Test deleting a message."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.delete(f"/api/messages/{msg.id}")
        assert response.status_code == 204

        # Verify deleted
        response = await client.get(f"/api/messages/{msg.id}")
        assert response.status_code == 404

    async def test_delete_message_not_found(self, client: AsyncClient) -> None:
        """Test deleting a non-existent message."""
        response = await client.delete("/api/messages/non-existent-id")
        assert response.status_code == 404

    async def test_delete_all_messages_requires_confirm(
        self, client: AsyncClient, db: Database
    ) -> None:
        """Test that delete all requires confirmation."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.delete("/api/messages")
        assert response.status_code == 400

        # Message should still exist
        assert await db.get_message_count() == 1

    async def test_delete_all_messages(self, client: AsyncClient, db: Database) -> None:
        """Test deleting all messages."""
        for _ in range(3):
            msg = create_test_message()
            await db.store_message(msg)

        response = await client.delete("/api/messages?confirm=true")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 3

        assert await db.get_message_count() == 0


class TestAttachmentEndpoints:
    """Tests for attachment API endpoints."""

    async def test_list_attachments(self, client: AsyncClient, db: Database) -> None:
        """Test listing attachments for a message."""
        msg = create_test_message()
        att = AttachmentCreate(
            id=str(uuid4()),
            message_id=msg.id,
            filename="test.txt",
            content_type="text/plain",
            size_bytes=12,
            content=b"Hello World!",
        )
        await db.store_message(msg, [att])

        response = await client.get(f"/api/messages/{msg.id}/attachments")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["filename"] == "test.txt"

    async def test_download_attachment(self, client: AsyncClient, db: Database) -> None:
        """Test downloading an attachment."""
        msg = create_test_message()
        att = AttachmentCreate(
            id=str(uuid4()),
            message_id=msg.id,
            filename="test.txt",
            content_type="text/plain",
            size_bytes=12,
            content=b"Hello World!",
        )
        await db.store_message(msg, [att])

        response = await client.get(f"/api/messages/{msg.id}/attachments/{att.id}")
        assert response.status_code == 200
        assert response.content == b"Hello World!"
        assert "attachment" in response.headers.get("content-disposition", "")

    async def test_download_attachment_not_found(
        self, client: AsyncClient, db: Database
    ) -> None:
        """Test downloading a non-existent attachment."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.get(f"/api/messages/{msg.id}/attachments/non-existent")
        assert response.status_code == 404


class TestUtilityEndpoints:
    """Tests for utility API endpoints."""

    async def test_health_check(self, client: AsyncClient) -> None:
        """Test health check endpoint."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database_ok" in data
        assert data["database_ok"] is True

    async def test_stats(self, client: AsyncClient, db: Database) -> None:
        """Test stats endpoint."""
        msg = create_test_message()
        await db.store_message(msg)

        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["message_count"] == 1
        assert data["total_size_bytes"] > 0

    async def test_prune(self, client: AsyncClient, db: Database) -> None:
        """Test manual prune endpoint."""
        for _ in range(5):
            msg = create_test_message()
            await db.store_message(msg)

        response = await client.post("/api/prune", json={"max_count": 2})
        assert response.status_code == 200
        data = response.json()
        assert data["deleted_count"] == 3
        assert data["remaining_count"] == 2

    async def test_vacuum(self, client: AsyncClient) -> None:
        """Test vacuum endpoint."""
        response = await client.post("/api/vacuum")
        assert response.status_code == 204


class TestSecurityHeaders:
    """Tests for security headers."""

    async def test_security_headers_present(self, client: AsyncClient) -> None:
        """Test that security headers are set on responses."""
        response = await client.get("/api/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "Content-Security-Policy" in response.headers
