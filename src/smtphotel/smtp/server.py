"""SMTP server implementation using aiosmtpd.

AIDEV-NOTE: This SMTP server captures all incoming email without forwarding.
It never sends bounces - all rejection happens at SMTP time.
Key security features:
- Message size limits (MAX_MESSAGE_SIZE_MB)
- Connection limits (MAX_CONNECTIONS)
- Rate limiting per IP (RATE_LIMIT_PER_MINUTE)
- Connection timeouts (SMTP_TIMEOUT_SECONDS)
"""

import asyncio
import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy as email_policy
from email.header import decode_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from time import monotonic
from uuid import uuid4

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session

from smtphotel.config import Settings, get_settings
from smtphotel.storage.database import Database, get_database
from smtphotel.storage.models import AttachmentCreate, MessageCreate

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Simple in-memory rate limiter per IP address.

    AIDEV-NOTE: This rate limiter uses a sliding window approach.
    It tracks message timestamps per IP and cleans up old entries.
    """

    limit_per_minute: int
    _timestamps: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def is_allowed(self, ip: str) -> bool:
        """Check if IP is allowed to send a message."""
        if self.limit_per_minute <= 0:
            return True

        now = monotonic()
        window_start = now - 60.0

        # Clean old timestamps
        self._timestamps[ip] = [ts for ts in self._timestamps[ip] if ts > window_start]

        # Check limit
        if len(self._timestamps[ip]) >= self.limit_per_minute:
            return False

        # Record this request
        self._timestamps[ip].append(now)
        return True

    def cleanup(self) -> None:
        """Remove old entries from rate limiter."""
        now = monotonic()
        window_start = now - 60.0
        to_delete = []
        for ip, timestamps in self._timestamps.items():
            self._timestamps[ip] = [ts for ts in timestamps if ts > window_start]
            if not self._timestamps[ip]:
                to_delete.append(ip)
        for ip in to_delete:
            del self._timestamps[ip]


@dataclass
class ConnectionTracker:
    """Track active SMTP connections.

    AIDEV-NOTE: Used to enforce MAX_CONNECTIONS limit.
    """

    max_connections: int
    _count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> bool:
        """Try to acquire a connection slot. Returns False if limit reached."""
        async with self._lock:
            if self._count >= self.max_connections:
                return False
            self._count += 1
            return True

    async def release(self) -> None:
        """Release a connection slot."""
        async with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def current_count(self) -> int:
        """Get current connection count."""
        return self._count


def decode_header_value(value: str | None) -> str:
    """Decode an email header value handling various encodings.

    AIDEV-NOTE: Email headers can be encoded in various ways (quoted-printable, base64, etc.)
    This function handles those encodings and returns a plain string.
    """
    if not value:
        return ""

    try:
        parts = decode_header(value)
        decoded_parts = []
        for data, charset in parts:
            if isinstance(data, bytes):
                charset = charset or "utf-8"
                try:
                    decoded_parts.append(data.decode(charset, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    decoded_parts.append(data.decode("utf-8", errors="replace"))
            else:
                decoded_parts.append(data)
        return "".join(decoded_parts)
    except Exception:
        # If decoding fails, return the original value
        return str(value)


def extract_email_parts(
    msg: Message | EmailMessage,
) -> tuple[str, str, list[tuple[str, str, int, bytes]]]:
    """Extract text body, HTML body, and attachments from an email message.

    Returns:
        Tuple of (body_text, body_html, attachments)
        where attachments is a list of (filename, content_type, size, content)
    """
    body_text = ""
    body_html = ""
    attachments: list[tuple[str, str, int, bytes]] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip multipart containers
            if part.is_multipart():
                continue

            # Check if it's an attachment
            if "attachment" in content_disposition or (
                content_type not in ("text/plain", "text/html")
                and "inline" not in content_disposition
            ):
                filename = part.get_filename() or "attachment"
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    attachments.append((filename, content_type, len(payload), payload))
            elif content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body_text = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body_text = payload.decode("utf-8", errors="replace")
            elif content_type == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body_html = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body_html = payload.decode("utf-8", errors="replace")
    else:
        # Non-multipart message
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = payload.decode("utf-8", errors="replace")

            if content_type == "text/html":
                body_html = text
            else:
                body_text = text

    return body_text, body_html, attachments


def parse_email(
    raw_data: bytes, envelope: Envelope
) -> tuple[MessageCreate, list[AttachmentCreate]]:
    """Parse raw email data into MessageCreate and AttachmentCreate objects.

    AIDEV-NOTE: This function handles various edge cases in email parsing:
    - Encoded headers
    - Multipart messages
    - Various character encodings
    - Malformed emails (graceful degradation)
    """
    parser = BytesParser(policy=email_policy.default)
    msg = parser.parsebytes(raw_data)
    msg_id = str(uuid4())
    received_at = datetime.now(UTC)

    # Extract headers as dict
    headers: dict[str, list[str]] = {}
    for key in msg:
        if key in headers:
            headers[key].append(decode_header_value(msg[key]))
        else:
            headers[key] = [decode_header_value(msg[key])]

    # Get subject
    subject = decode_header_value(msg.get("Subject", ""))

    # Extract body and attachments
    body_text, body_html, raw_attachments = extract_email_parts(msg)

    # Create message
    message = MessageCreate(
        id=msg_id,
        received_at=received_at,
        mail_from=envelope.mail_from or "",
        rcpt_to=list(envelope.rcpt_tos),
        subject=subject,
        headers=headers,
        body_text=body_text,
        body_html=body_html,
        raw=raw_data,
        size_bytes=len(raw_data),
    )

    # Create attachments
    attachments = [
        AttachmentCreate(
            id=str(uuid4()),
            message_id=msg_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size,
            content=content,
        )
        for filename, content_type, size, content in raw_attachments
    ]

    return message, attachments


class SMTPHandler:
    """Custom SMTP handler that captures all email.

    AIDEV-NOTE: This handler:
    - Accepts mail to any address
    - Never forwards or bounces
    - Stores all messages in the database
    - Enforces size and rate limits
    """

    def __init__(
        self,
        settings: Settings,
        database: Database,
        rate_limiter: RateLimiter,
        connection_tracker: ConnectionTracker,
    ) -> None:
        self.settings = settings
        self.database = database
        self.rate_limiter = rate_limiter
        self.connection_tracker = connection_tracker

    async def handle_RCPT(
        self,
        _server: SMTP,
        _session: Session,
        envelope: Envelope,
        address: str,
        _rcpt_options: list[str],
    ) -> str:
        """Accept any recipient address.

        AIDEV-NOTE: This is a development mail server - we accept all addresses.
        """
        envelope.rcpt_tos.append(address)
        logger.debug("Accepted recipient: %s", address)
        return "250 OK"

    async def handle_DATA(
        self, _server: SMTP, session: Session, envelope: Envelope
    ) -> str:
        """Handle incoming email data."""
        peer = session.peer
        peer_ip = peer[0] if peer else "unknown"

        # Check connection limit
        # AIDEV-NOTE: Ideally this would be done at connection time, but aiosmtpd's
        # architecture makes that complex. Checking at DATA time still limits abuse.
        if not await self.connection_tracker.acquire():
            logger.warning(
                "Connection limit reached (%d), rejecting from %s",
                self.connection_tracker.max_connections,
                peer_ip,
            )
            return "421 Too many connections, try again later"

        try:
            return await self._process_data(envelope, peer_ip)
        finally:
            await self.connection_tracker.release()

    async def _process_data(self, envelope: Envelope, peer_ip: str) -> str:
        """Process email data (internal helper)."""
        # Check rate limit
        if not self.rate_limiter.is_allowed(peer_ip):
            logger.warning("Rate limit exceeded for %s", peer_ip)
            return "450 Rate limit exceeded, try again later"

        # Check message size
        content = envelope.content
        if not content:
            return "554 Message rejected: empty message"

        # Ensure we have bytes
        raw_data = content if isinstance(content, bytes) else content.encode("utf-8")

        if len(raw_data) > self.settings.max_message_size_bytes:
            logger.warning(
                "Message too large from %s: %d bytes (limit: %d)",
                peer_ip,
                len(raw_data),
                self.settings.max_message_size_bytes,
            )
            return f"552 Message too large (max {self.settings.max_message_size_mb}MB)"

        try:
            # Parse and store the message
            message, attachments = parse_email(raw_data, envelope)
            await self.database.store_message(message, attachments)

            # Log metadata only (not body for privacy)
            logger.info(
                "Received message: from=%s, to=%s, subject=%s, size=%d, attachments=%d",
                message.mail_from,
                message.rcpt_to,
                message.subject[:50] + "..."
                if len(message.subject) > 50
                else message.subject,
                message.size_bytes,
                len(attachments),
            )

            return "250 Message accepted"

        except Exception as e:
            logger.exception("Error processing message from %s: %s", peer_ip, e)
            return "451 Temporary error, please retry"


class SMTPServer:
    """SMTP server manager.

    AIDEV-NOTE: This class manages the aiosmtpd controller and provides
    startup/shutdown lifecycle management.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._controller: Controller | None = None
        self._rate_limiter = RateLimiter(self.settings.rate_limit_per_minute)
        self._connection_tracker = ConnectionTracker(self.settings.max_connections)
        self._handler: SMTPHandler | None = None
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self, database: Database | None = None) -> None:
        """Start the SMTP server."""
        if database is None:
            database = await get_database()

        self._handler = SMTPHandler(
            self.settings,
            database,
            self._rate_limiter,
            self._connection_tracker,
        )

        # Create controller with timeout
        # AIDEV-NOTE: Connection tracking is handled in SMTPHandler.handle_DATA for now
        # since aiosmtpd's factory mechanism has compatibility issues.
        self._controller = Controller(
            self._handler,
            hostname=self.settings.bind_address,
            port=self.settings.smtp_port,
            server_kwargs={
                "timeout": self.settings.smtp_timeout_seconds,
            },
        )

        self._controller.start()

        # Start cleanup task for rate limiter
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            "SMTP server started on %s:%d",
            self.settings.bind_address,
            self.settings.smtp_port,
        )

    async def _cleanup_loop(self) -> None:
        """Periodically clean up rate limiter entries."""
        while True:
            try:
                await asyncio.sleep(60)
                self._rate_limiter.cleanup()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in cleanup loop")

    async def stop(self) -> None:
        """Stop the SMTP server."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

        if self._controller:
            self._controller.stop()
            self._controller = None
            logger.info("SMTP server stopped")

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._controller is not None

    @property
    def connection_count(self) -> int:
        """Get current connection count."""
        return self._connection_tracker.current_count


# Global SMTP server instance
# AIDEV-NOTE: This global is initialized once by run_servers() in main.py.
# Health check and other code paths should only call get_smtp_server() AFTER
# the server has been started, which is guaranteed by the startup order.
_smtp_server: SMTPServer | None = None


async def get_smtp_server(settings: Settings | None = None) -> SMTPServer:
    """Get or create the global SMTP server instance.

    Args:
        settings: Optional settings. Required on first call to create the instance.
                  If the instance already exists, this parameter is ignored.

    Returns:
        The global SMTP server instance.

    Raises:
        RuntimeError: If called for the first time without settings.

    Note:
        The instance is created once during startup by run_servers() in main.py.
        Subsequent calls (e.g., from health check) return the existing instance.
    """
    global _smtp_server
    if _smtp_server is None:
        if settings is None:
            raise RuntimeError(
                "SMTP server not initialized. Call get_smtp_server(settings) first "
                "during startup, or ensure run_servers() has been called."
            )
        _smtp_server = SMTPServer(settings)
    return _smtp_server


async def stop_smtp_server() -> None:
    """Stop the global SMTP server instance."""
    global _smtp_server
    if _smtp_server is not None:
        await _smtp_server.stop()
        _smtp_server = None
