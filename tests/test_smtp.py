"""Tests for SMTP server."""

import asyncio
import smtplib
from email.message import EmailMessage
from pathlib import Path

import pytest
import pytest_asyncio

from smtphotel.config import Settings
from smtphotel.smtp.server import (
    ConnectionTracker,
    RateLimiter,
    SMTPServer,
    decode_header_value,
    parse_email,
)
from smtphotel.storage.database import Database


class TestRateLimiter:
    """Tests for rate limiter."""

    def test_allows_under_limit(self) -> None:
        """Test that requests under limit are allowed."""
        limiter = RateLimiter(limit_per_minute=5)
        for _ in range(5):
            assert limiter.is_allowed("192.168.1.1")

    def test_blocks_over_limit(self) -> None:
        """Test that requests over limit are blocked."""
        limiter = RateLimiter(limit_per_minute=3)
        for _ in range(3):
            assert limiter.is_allowed("192.168.1.1")
        assert not limiter.is_allowed("192.168.1.1")

    def test_separate_limits_per_ip(self) -> None:
        """Test that different IPs have separate limits."""
        limiter = RateLimiter(limit_per_minute=2)
        assert limiter.is_allowed("192.168.1.1")
        assert limiter.is_allowed("192.168.1.1")
        assert not limiter.is_allowed("192.168.1.1")
        # Different IP should still be allowed
        assert limiter.is_allowed("192.168.1.2")

    def test_disabled_when_limit_zero(self) -> None:
        """Test that rate limiting is disabled when limit is 0."""
        limiter = RateLimiter(limit_per_minute=0)
        for _ in range(100):
            assert limiter.is_allowed("192.168.1.1")

    def test_cleanup_removes_old_entries(self) -> None:
        """Test that cleanup removes empty IP entries."""
        limiter = RateLimiter(limit_per_minute=5)
        limiter.is_allowed("192.168.1.1")
        limiter.is_allowed("192.168.1.2")
        assert "192.168.1.1" in limiter._timestamps
        assert "192.168.1.2" in limiter._timestamps

        # Clear timestamps manually to simulate time passing
        limiter._timestamps["192.168.1.1"] = []
        limiter.cleanup()

        assert "192.168.1.1" not in limiter._timestamps
        assert "192.168.1.2" in limiter._timestamps


class TestConnectionTracker:
    """Tests for connection tracker."""

    async def test_allows_under_limit(self) -> None:
        """Test that connections under limit are allowed."""
        tracker = ConnectionTracker(max_connections=3)
        assert await tracker.acquire()
        assert await tracker.acquire()
        assert await tracker.acquire()
        assert tracker.current_count == 3

    async def test_blocks_over_limit(self) -> None:
        """Test that connections over limit are blocked."""
        tracker = ConnectionTracker(max_connections=2)
        assert await tracker.acquire()
        assert await tracker.acquire()
        assert not await tracker.acquire()
        assert tracker.current_count == 2

    async def test_release_allows_new_connections(self) -> None:
        """Test that releasing allows new connections."""
        tracker = ConnectionTracker(max_connections=1)
        assert await tracker.acquire()
        assert not await tracker.acquire()
        await tracker.release()
        assert await tracker.acquire()

    async def test_release_doesnt_go_negative(self) -> None:
        """Test that release doesn't make count negative."""
        tracker = ConnectionTracker(max_connections=5)
        await tracker.release()
        await tracker.release()
        assert tracker.current_count == 0


class TestHeaderDecoding:
    """Tests for email header decoding."""

    def test_plain_ascii(self) -> None:
        """Test decoding plain ASCII header."""
        assert decode_header_value("Test Subject") == "Test Subject"

    def test_none_value(self) -> None:
        """Test decoding None returns empty string."""
        assert decode_header_value(None) == ""

    def test_empty_value(self) -> None:
        """Test decoding empty string returns empty string."""
        assert decode_header_value("") == ""

    def test_encoded_utf8(self) -> None:
        """Test decoding UTF-8 encoded header."""
        encoded = "=?utf-8?Q?Caf=C3=A9?="
        assert decode_header_value(encoded) == "Café"

    def test_encoded_base64(self) -> None:
        """Test decoding base64 encoded header."""
        encoded = "=?utf-8?b?SGVsbG8gV29ybGQ=?="
        assert decode_header_value(encoded) == "Hello World"


class TestEmailParsing:
    """Tests for email parsing."""

    def test_parse_simple_email(self) -> None:
        """Test parsing a simple text email."""
        from aiosmtpd.smtp import Envelope

        raw = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Subject
Content-Type: text/plain; charset=utf-8

This is the body.
"""
        envelope = Envelope()
        envelope.mail_from = "sender@example.com"
        envelope.rcpt_tos = ["recipient@example.com"]

        message, attachments = parse_email(raw, envelope)

        assert message.mail_from == "sender@example.com"
        assert message.rcpt_to == ["recipient@example.com"]
        assert message.subject == "Test Subject"
        assert "This is the body." in message.body_text
        assert message.body_html == ""
        assert len(attachments) == 0

    def test_parse_html_email(self) -> None:
        """Test parsing an HTML email."""
        from aiosmtpd.smtp import Envelope

        raw = b"""From: sender@example.com
To: recipient@example.com
Subject: HTML Test
Content-Type: text/html; charset=utf-8

<html><body><h1>Hello</h1></body></html>
"""
        envelope = Envelope()
        envelope.mail_from = "sender@example.com"
        envelope.rcpt_tos = ["recipient@example.com"]

        message, attachments = parse_email(raw, envelope)

        assert message.body_text == ""
        assert "<h1>Hello</h1>" in message.body_html

    def test_parse_multipart_email(self) -> None:
        """Test parsing a multipart email."""
        from aiosmtpd.smtp import Envelope

        raw = b"""From: sender@example.com
To: recipient@example.com
Subject: Multipart Test
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Plain text version
--boundary123
Content-Type: text/html; charset=utf-8

<html><body>HTML version</body></html>
--boundary123--
"""
        envelope = Envelope()
        envelope.mail_from = "sender@example.com"
        envelope.rcpt_tos = ["recipient@example.com"]

        message, attachments = parse_email(raw, envelope)

        assert "Plain text version" in message.body_text
        assert "HTML version" in message.body_html

    def test_parse_email_with_attachment(self) -> None:
        """Test parsing an email with attachment."""
        from aiosmtpd.smtp import Envelope

        raw = b"""From: sender@example.com
To: recipient@example.com
Subject: Attachment Test
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Body text
--boundary123
Content-Type: text/plain; name="test.txt"
Content-Disposition: attachment; filename="test.txt"

File content here
--boundary123--
"""
        envelope = Envelope()
        envelope.mail_from = "sender@example.com"
        envelope.rcpt_tos = ["recipient@example.com"]

        message, attachments = parse_email(raw, envelope)

        assert len(attachments) == 1
        assert attachments[0].filename == "test.txt"
        assert b"File content here" in attachments[0].content


@pytest_asyncio.fixture
async def smtp_test_settings(tmp_path: Path) -> Settings:
    """Create settings for SMTP testing with free port."""
    return Settings(
        SMTP_PORT=12525,
        HTTP_PORT=18025,
        DB_PATH=str(tmp_path / "test.db"),
        BIND_ADDRESS="127.0.0.1",
        MAX_MESSAGE_SIZE_MB=1,
        RATE_LIMIT_PER_MINUTE=0,
        MAX_CONNECTIONS=10,
        SMTP_TIMEOUT_SECONDS=30,
    )


@pytest_asyncio.fixture
async def smtp_server(smtp_test_settings: Settings) -> SMTPServer:
    """Create and start an SMTP server for testing."""
    from smtphotel.storage.database import Database

    db = Database(smtp_test_settings)
    await db.connect()

    server = SMTPServer(smtp_test_settings)
    await server.start(db)

    yield server

    await server.stop()
    await db.disconnect()


class TestSMTPServerIntegration:
    """Integration tests for SMTP server."""

    async def test_server_starts_and_stops(self, smtp_test_settings: Settings) -> None:
        """Test that server starts and stops correctly."""
        db = Database(smtp_test_settings)
        await db.connect()

        server = SMTPServer(smtp_test_settings)
        assert not server.is_running

        await server.start(db)
        assert server.is_running

        await server.stop()
        assert not server.is_running

        await db.disconnect()

    async def test_accept_simple_email(self, smtp_server: SMTPServer) -> None:
        """Test accepting a simple email via SMTP."""
        # Send email via smtplib
        msg = EmailMessage()
        msg["From"] = "sender@test.com"
        msg["To"] = "recipient@test.com"
        msg["Subject"] = "Test Email"
        msg.set_content("This is a test email.")

        with smtplib.SMTP("127.0.0.1", 12525) as client:
            client.send_message(msg)

        # Give a moment for processing
        await asyncio.sleep(0.1)

        # Verify message was stored
        assert smtp_server._handler is not None
        db = smtp_server._handler.database
        messages, total = await db.get_messages()
        assert total == 1
        assert messages[0].subject == "Test Email"

    async def test_accept_any_recipient(self, smtp_server: SMTPServer) -> None:
        """Test that server accepts any recipient address."""
        msg = EmailMessage()
        msg["From"] = "sender@test.com"
        msg["To"] = "anyone@anywhere.nonexistent"
        msg["Subject"] = "Any Recipient Test"
        msg.set_content("Test body")

        with smtplib.SMTP("127.0.0.1", 12525) as client:
            client.send_message(msg)

        await asyncio.sleep(0.1)

        assert smtp_server._handler is not None
        db = smtp_server._handler.database
        messages, total = await db.get_messages()
        assert total == 1

    async def test_reject_oversized_message(self, tmp_path: Path) -> None:
        """Test that oversized messages are rejected."""
        # Create server with tiny size limit
        small_settings = Settings(
            SMTP_PORT=12526,
            HTTP_PORT=18026,
            DB_PATH=str(tmp_path / "tiny.db"),
            BIND_ADDRESS="127.0.0.1",
            MAX_MESSAGE_SIZE_MB=1,  # 1MB limit
        )

        db = Database(small_settings)
        await db.connect()

        server = SMTPServer(small_settings)
        await server.start(db)

        try:
            msg = EmailMessage()
            msg["From"] = "sender@test.com"
            msg["To"] = "recipient@test.com"
            msg["Subject"] = "Large Email"
            # Create message larger than 1MB
            large_body = "X" * (1024 * 1024 + 1000)
            msg.set_content(large_body)

            with (
                pytest.raises(smtplib.SMTPDataError),
                smtplib.SMTP("127.0.0.1", 12526) as client,
            ):
                client.send_message(msg)

        finally:
            await server.stop()
            await db.disconnect()

    async def test_multiple_recipients(self, smtp_server: SMTPServer) -> None:
        """Test email with multiple recipients."""
        with smtplib.SMTP("127.0.0.1", 12525) as client:
            client.sendmail(
                "sender@test.com",
                ["recipient1@test.com", "recipient2@test.com"],
                """\
From: sender@test.com
To: recipient1@test.com, recipient2@test.com
Subject: Multiple Recipients

Body text
""",
            )

        await asyncio.sleep(0.1)

        assert smtp_server._handler is not None
        db = smtp_server._handler.database
        messages, total = await db.get_messages()
        assert total == 1
        assert len(messages[0].rcpt_to) == 2
