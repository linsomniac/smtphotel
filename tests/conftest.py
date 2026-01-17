"""Pytest configuration and fixtures for smtphotel tests.

AIDEV-NOTE: This provides fixtures for testing with in-memory SQLite,
test SMTP client, and sample email messages.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from smtphotel.config import Settings
from smtphotel.storage.database import Database
from smtphotel.storage.models import AttachmentCreate, MessageCreate


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Create settings for testing with temp database."""
    return Settings(
        SMTP_PORT=12525,
        HTTP_PORT=18025,
        DB_PATH=str(tmp_path / "test.db"),
        BIND_ADDRESS="127.0.0.1",
        MAX_MESSAGE_AGE_HOURS=0,
        MAX_MESSAGE_COUNT=0,
        MAX_MESSAGE_SIZE_MB=10,
        RATE_LIMIT_PER_MINUTE=0,
        CORS_ORIGINS="",
    )


@pytest_asyncio.fixture
async def db(test_settings: Settings) -> AsyncGenerator[Database, None]:
    """Create a test database instance."""
    database = Database(test_settings)
    await database.connect()
    yield database
    await database.disconnect()


@pytest.fixture
def sample_message() -> MessageCreate:
    """Create a sample message for testing."""
    msg_id = str(uuid4())
    raw_content = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Content-Type: text/plain; charset=utf-8

This is the body of the test email.
"""
    return MessageCreate(
        id=msg_id,
        received_at=datetime.now(UTC),
        mail_from="sender@example.com",
        rcpt_to=["recipient@example.com"],
        subject="Test Subject",
        headers={
            "From": ["sender@example.com"],
            "To": ["recipient@example.com"],
            "Subject": ["Test Subject"],
            "Content-Type": ["text/plain; charset=utf-8"],
        },
        body_text="This is the body of the test email.",
        body_html="",
        raw=raw_content,
        size_bytes=len(raw_content),
    )


@pytest.fixture
def sample_html_message() -> MessageCreate:
    """Create a sample message with HTML body for testing."""
    msg_id = str(uuid4())
    raw_content = b"""From: sender@example.com
To: recipient@example.com
Subject: HTML Test
Content-Type: multipart/alternative; boundary="boundary"

--boundary
Content-Type: text/plain; charset=utf-8

Plain text version
--boundary
Content-Type: text/html; charset=utf-8

<html><body><h1>HTML Version</h1></body></html>
--boundary--
"""
    return MessageCreate(
        id=msg_id,
        received_at=datetime.now(UTC),
        mail_from="sender@example.com",
        rcpt_to=["recipient@example.com", "other@example.com"],
        subject="HTML Test",
        headers={
            "From": ["sender@example.com"],
            "To": ["recipient@example.com"],
            "Subject": ["HTML Test"],
            "Content-Type": ['multipart/alternative; boundary="boundary"'],
        },
        body_text="Plain text version",
        body_html="<html><body><h1>HTML Version</h1></body></html>",
        raw=raw_content,
        size_bytes=len(raw_content),
    )


@pytest.fixture
def sample_attachment(sample_message: MessageCreate) -> AttachmentCreate:
    """Create a sample attachment for testing."""
    return AttachmentCreate(
        id=str(uuid4()),
        message_id=sample_message.id,
        filename="test.txt",
        content_type="text/plain",
        size_bytes=12,
        content=b"Hello World!",
    )


def create_message(
    msg_id: str | None = None,
    mail_from: str = "test@example.com",
    rcpt_to: list[str] | None = None,
    subject: str = "Test Subject",
    body_text: str = "Test body",
    body_html: str = "",
    received_at: datetime | None = None,
) -> MessageCreate:
    """Helper to create a message with custom fields."""
    if msg_id is None:
        msg_id = str(uuid4())
    if rcpt_to is None:
        rcpt_to = ["recipient@example.com"]
    if received_at is None:
        received_at = datetime.now(UTC)

    raw_content = f"""From: {mail_from}
To: {", ".join(rcpt_to)}
Subject: {subject}

{body_text}
""".encode()

    return MessageCreate(
        id=msg_id,
        received_at=received_at,
        mail_from=mail_from,
        rcpt_to=rcpt_to,
        subject=subject,
        headers={
            "From": [mail_from],
            "To": rcpt_to,
            "Subject": [subject],
        },
        body_text=body_text,
        body_html=body_html,
        raw=raw_content,
        size_bytes=len(raw_content),
    )
