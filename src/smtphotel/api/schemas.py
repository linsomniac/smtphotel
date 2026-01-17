"""Pydantic schemas for API request/response validation.

AIDEV-NOTE: These schemas are separate from storage models to allow
API-specific validation and documentation.
"""

from datetime import datetime

from pydantic import BaseModel, Field

# Response models for messages


class AttachmentResponse(BaseModel):
    """Attachment metadata in API responses."""

    id: str = Field(..., description="Attachment UUID")
    message_id: str = Field(..., description="Parent message UUID")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field(..., description="MIME type")
    size_bytes: int = Field(..., ge=0, description="Attachment size in bytes")

    model_config = {"from_attributes": True}


class MessageSummaryResponse(BaseModel):
    """Summary of a message for list views."""

    id: str = Field(..., description="Message UUID")
    received_at: datetime = Field(..., description="When the message was received")
    mail_from: str = Field(..., description="Envelope sender")
    rcpt_to: list[str] = Field(..., description="Envelope recipients")
    subject: str = Field(..., description="Subject header")
    size_bytes: int = Field(..., ge=0, description="Message size in bytes")
    has_attachments: bool = Field(..., description="Whether message has attachments")

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """Full message response including body and attachments."""

    id: str = Field(..., description="Message UUID")
    received_at: datetime = Field(..., description="When the message was received")
    mail_from: str = Field(..., description="Envelope sender")
    rcpt_to: list[str] = Field(..., description="Envelope recipients")
    subject: str = Field(..., description="Subject header")
    headers: dict[str, list[str]] = Field(..., description="All message headers")
    body_text: str = Field(..., description="Plain text body")
    body_html: str = Field(..., description="HTML body")
    size_bytes: int = Field(..., ge=0, description="Message size in bytes")
    attachments: list[AttachmentResponse] = Field(
        default_factory=list, description="Message attachments"
    )

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    """Paginated list of messages."""

    messages: list[MessageSummaryResponse] = Field(..., description="List of messages")
    total: int = Field(..., ge=0, description="Total count of messages")
    limit: int = Field(..., ge=1, description="Page size")
    offset: int = Field(..., ge=0, description="Page offset")


# Response models for utility endpoints


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Server status")
    message_count: int = Field(..., ge=0, description="Number of messages stored")
    database_ok: bool = Field(..., description="Database health status")
    smtp_running: bool = Field(..., description="SMTP server status")


class StatsResponse(BaseModel):
    """Server statistics response."""

    message_count: int = Field(..., ge=0, description="Total number of messages")
    total_size_bytes: int = Field(..., ge=0, description="Total storage used")
    oldest_message: datetime | None = Field(
        None, description="Timestamp of oldest message"
    )
    newest_message: datetime | None = Field(
        None, description="Timestamp of newest message"
    )


class PruneRequest(BaseModel):
    """Request body for manual prune operation."""

    max_age_hours: int | None = Field(
        None, ge=1, description="Delete messages older than this many hours"
    )
    max_count: int | None = Field(
        None, ge=1, description="Keep only this many most recent messages"
    )


class PruneResponse(BaseModel):
    """Response from prune operation."""

    deleted_count: int = Field(..., ge=0, description="Number of messages deleted")
    remaining_count: int = Field(..., ge=0, description="Number of messages remaining")


class DeleteAllResponse(BaseModel):
    """Response from delete all operation."""

    deleted_count: int = Field(..., ge=0, description="Number of messages deleted")


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str = Field(..., description="Error message")
