"""Pydantic models for database entities."""

from datetime import datetime

from pydantic import BaseModel, Field


class AttachmentCreate(BaseModel):
    """Model for creating an attachment."""

    id: str = Field(..., description="UUID of the attachment")
    message_id: str = Field(..., description="Parent message UUID")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field(..., description="MIME type")
    size_bytes: int = Field(..., ge=0, description="Attachment size in bytes")
    content: bytes = Field(..., description="Attachment binary content")


class Attachment(BaseModel):
    """Model for attachment metadata (without content)."""

    id: str = Field(..., description="UUID of the attachment")
    message_id: str = Field(..., description="Parent message UUID")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field(..., description="MIME type")
    size_bytes: int = Field(..., ge=0, description="Attachment size in bytes")


class AttachmentWithContent(Attachment):
    """Attachment model including binary content."""

    content: bytes = Field(..., description="Attachment binary content")


class MessageCreate(BaseModel):
    """Model for creating a message in the database."""

    id: str = Field(..., description="UUID of the message")
    received_at: datetime = Field(..., description="When the message was received")
    mail_from: str = Field(..., description="Envelope sender (MAIL FROM)")
    rcpt_to: list[str] = Field(..., description="Envelope recipients (RCPT TO)")
    subject: str = Field(default="", description="Parsed subject header")
    headers: dict[str, list[str]] = Field(
        default_factory=dict, description="All headers as dict"
    )
    body_text: str = Field(default="", description="Plain text body")
    body_html: str = Field(default="", description="HTML body")
    raw: bytes = Field(..., description="Raw message bytes")
    size_bytes: int = Field(..., ge=0, description="Message size in bytes")


class MessageSummary(BaseModel):
    """Summary of a message for list views."""

    id: str = Field(..., description="UUID of the message")
    received_at: datetime = Field(..., description="When the message was received")
    mail_from: str = Field(..., description="Envelope sender")
    rcpt_to: list[str] = Field(..., description="Envelope recipients")
    subject: str = Field(..., description="Subject header")
    size_bytes: int = Field(..., description="Message size in bytes")
    has_attachments: bool = Field(..., description="Whether message has attachments")


class Message(BaseModel):
    """Full message model."""

    id: str = Field(..., description="UUID of the message")
    received_at: datetime = Field(..., description="When the message was received")
    mail_from: str = Field(..., description="Envelope sender")
    rcpt_to: list[str] = Field(..., description="Envelope recipients")
    subject: str = Field(..., description="Subject header")
    headers: dict[str, list[str]] = Field(..., description="All headers")
    body_text: str = Field(..., description="Plain text body")
    body_html: str = Field(..., description="HTML body")
    size_bytes: int = Field(..., description="Message size in bytes")
    attachments: list[Attachment] = Field(
        default_factory=list, description="Message attachments"
    )


class MessageRaw(BaseModel):
    """Raw message content."""

    id: str = Field(..., description="UUID of the message")
    raw: bytes = Field(..., description="Raw message bytes")
