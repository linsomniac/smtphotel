"""REST API routes for smtphotel.

AIDEV-NOTE: This module implements the REST API for accessing captured messages.
All routes are prefixed with /api and include proper security headers.
"""

import logging
import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from smtphotel.api.schemas import (
    AttachmentResponse,
    DeleteAllResponse,
    ErrorResponse,
    HealthResponse,
    MessageListResponse,
    MessageResponse,
    MessageSummaryResponse,
    PruneRequest,
    PruneResponse,
    StatsResponse,
)
from smtphotel.storage.database import Database, get_database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["API"])


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent header injection.

    AIDEV-NOTE: This function prevents CRLF injection and path traversal in
    Content-Disposition headers. It strips dangerous characters and limits length.
    """
    if not filename:
        return "attachment"

    # Remove path separators and null bytes
    filename = filename.replace("/", "_").replace("\\", "_").replace("\x00", "")

    # Remove CR/LF to prevent header injection
    filename = filename.replace("\r", "").replace("\n", "")

    # Remove leading/trailing whitespace and dots (prevent hidden files)
    filename = filename.strip(" .")

    # Limit length to prevent issues
    if len(filename) > 200:
        # Preserve extension if present
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            ext = ext[:10]  # Limit extension length too
            filename = name[: 200 - len(ext) - 1] + "." + ext
        else:
            filename = filename[:200]

    return filename or "attachment"


def build_content_disposition(filename: str) -> str:
    """Build a safe Content-Disposition header with RFC 5987 encoding.

    AIDEV-NOTE: Uses both simple filename and filename* (RFC 5987) for compatibility.
    The filename* form handles non-ASCII characters properly.
    """
    safe_filename = sanitize_filename(filename)

    # For ASCII-safe filename, use simple form
    # For filename*, use RFC 5987 percent-encoding
    ascii_safe = re.sub(r"[^\x20-\x7E]", "_", safe_filename)

    # RFC 5987 encoded version for full Unicode support
    encoded = quote(safe_filename, safe="")

    return f"attachment; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"


async def get_db() -> Database:
    """Dependency to get database instance."""
    return await get_database()


# Message endpoints


@router.get(
    "/messages",
    response_model=MessageListResponse,
    summary="List messages",
    description="Get a paginated list of captured messages with optional filtering.",
)
async def list_messages(
    db: Annotated[Database, Depends(get_db)],
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Maximum number of messages to return")
    ] = 50,
    offset: Annotated[int, Query(ge=0, description="Number of messages to skip")] = 0,
    search: Annotated[
        str | None, Query(description="Search term for from/to/subject")
    ] = None,
    sort_by: Annotated[
        Literal["received_at", "mail_from", "subject", "size_bytes"],
        Query(description="Field to sort by"),
    ] = "received_at",
    sort_desc: Annotated[bool, Query(description="Sort in descending order")] = True,
) -> MessageListResponse:
    """List all captured messages with pagination and filtering."""
    messages, total = await db.get_messages(
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_desc=sort_desc,
    )

    return MessageListResponse(
        messages=[
            MessageSummaryResponse(
                id=m.id,
                received_at=m.received_at,
                mail_from=m.mail_from,
                rcpt_to=m.rcpt_to,
                subject=m.subject,
                size_bytes=m.size_bytes,
                has_attachments=m.has_attachments,
            )
            for m in messages
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/messages/{message_id}",
    response_model=MessageResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get message details",
    description="Get full details of a single message including headers and body.",
)
async def get_message(
    message_id: str,
    db: Annotated[Database, Depends(get_db)],
) -> MessageResponse:
    """Get a single message with full details."""
    message = await db.get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    return MessageResponse(
        id=message.id,
        received_at=message.received_at,
        mail_from=message.mail_from,
        rcpt_to=message.rcpt_to,
        subject=message.subject,
        headers=message.headers,
        body_text=message.body_text,
        body_html=message.body_html,
        size_bytes=message.size_bytes,
        attachments=[
            AttachmentResponse(
                id=a.id,
                message_id=a.message_id,
                filename=a.filename,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
            )
            for a in message.attachments
        ],
    )


@router.get(
    "/messages/{message_id}/raw",
    responses={
        200: {
            "content": {"message/rfc822": {}},
            "description": "Raw RFC822 message",
        },
        404: {"model": ErrorResponse},
    },
    summary="Get raw message",
    description="Get the original raw RFC822 message as received.",
)
async def get_message_raw(
    message_id: str,
    db: Annotated[Database, Depends(get_db)],
) -> Response:
    """Get the raw RFC822 message."""
    raw = await db.get_message_raw(message_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Message not found")

    return Response(
        content=raw.raw,
        media_type="message/rfc822",
        headers={
            "Content-Disposition": f'attachment; filename="{message_id}.eml"',
        },
    )


@router.get(
    "/messages/{message_id}/attachments",
    response_model=list[AttachmentResponse],
    responses={404: {"model": ErrorResponse}},
    summary="List message attachments",
    description="Get a list of attachments for a message.",
)
async def list_attachments(
    message_id: str,
    db: Annotated[Database, Depends(get_db)],
) -> list[AttachmentResponse]:
    """List attachments for a message."""
    # Verify message exists
    message = await db.get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    attachments = await db.get_message_attachments(message_id)
    return [
        AttachmentResponse(
            id=a.id,
            message_id=a.message_id,
            filename=a.filename,
            content_type=a.content_type,
            size_bytes=a.size_bytes,
        )
        for a in attachments
    ]


@router.get(
    "/messages/{message_id}/attachments/{attachment_id}",
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Attachment content",
        },
        404: {"model": ErrorResponse},
    },
    summary="Download attachment",
    description="Download an attachment by ID.",
)
async def download_attachment(
    message_id: str,
    attachment_id: str,
    db: Annotated[Database, Depends(get_db)],
) -> Response:
    """Download an attachment."""
    attachment = await db.get_attachment(attachment_id)
    if not attachment or attachment.message_id != message_id:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return Response(
        content=attachment.content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": build_content_disposition(attachment.filename),
        },
    )


@router.delete(
    "/messages/{message_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
    summary="Delete message",
    description="Delete a single message and its attachments.",
)
async def delete_message(
    message_id: str,
    db: Annotated[Database, Depends(get_db)],
) -> Response:
    """Delete a single message."""
    deleted = await db.delete_message(message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")

    return Response(status_code=204)


@router.delete(
    "/messages",
    response_model=DeleteAllResponse,
    summary="Delete all messages",
    description="Delete all messages. Requires confirmation parameter.",
)
async def delete_all_messages(
    db: Annotated[Database, Depends(get_db)],
    confirm: Annotated[
        bool, Query(description="Must be true to confirm deletion")
    ] = False,
) -> DeleteAllResponse:
    """Delete all messages. Requires confirmation."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true to delete all messages",
        )

    count = await db.delete_all_messages()
    logger.info("Deleted all messages: %d", count)
    return DeleteAllResponse(deleted_count=count)


# Utility endpoints


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check server health status.",
)
async def health_check(
    db: Annotated[Database, Depends(get_db)],
) -> HealthResponse:
    """Check server health."""
    from smtphotel.smtp.server import get_smtp_server

    try:
        db_ok = await db.integrity_check()
        message_count = await db.get_message_count()
    except Exception:
        db_ok = False
        message_count = 0

    try:
        smtp_server = await get_smtp_server()
        smtp_running = smtp_server.is_running
    except Exception:
        smtp_running = False

    status = "healthy" if db_ok and smtp_running else "degraded"

    return HealthResponse(
        status=status,
        message_count=message_count,
        database_ok=db_ok,
        smtp_running=smtp_running,
    )


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Server statistics",
    description="Get server statistics including message count and storage usage.",
)
async def get_stats(
    db: Annotated[Database, Depends(get_db)],
) -> StatsResponse:
    """Get server statistics."""
    message_count = await db.get_message_count()
    total_size = await db.get_total_storage_bytes()
    oldest = await db.get_oldest_message_time()
    newest = await db.get_newest_message_time()

    return StatsResponse(
        message_count=message_count,
        total_size_bytes=total_size,
        oldest_message=datetime.fromisoformat(oldest) if oldest else None,
        newest_message=datetime.fromisoformat(newest) if newest else None,
    )


@router.post(
    "/prune",
    response_model=PruneResponse,
    summary="Prune messages",
    description="Manually trigger message pruning by age or count.",
)
async def prune_messages(
    db: Annotated[Database, Depends(get_db)],
    request: PruneRequest | None = None,
) -> PruneResponse:
    """Manually trigger message pruning."""
    deleted = 0

    if request:
        if request.max_age_hours:
            deleted += await db.prune_by_age(request.max_age_hours)
        if request.max_count:
            deleted += await db.prune_by_count(request.max_count)

    remaining = await db.get_message_count()

    logger.info("Manual prune: deleted %d messages, %d remaining", deleted, remaining)
    return PruneResponse(deleted_count=deleted, remaining_count=remaining)


@router.post(
    "/vacuum",
    status_code=204,
    summary="Vacuum database",
    description="Run SQLite VACUUM to reclaim disk space.",
)
async def vacuum_database(
    db: Annotated[Database, Depends(get_db)],
) -> Response:
    """Run database vacuum."""
    await db.vacuum()
    logger.info("Database vacuumed")
    return Response(status_code=204)
