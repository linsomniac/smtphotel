---
name: fastapi-dev
description: FastAPI endpoint development with Pydantic validation, proper error handling, and OpenAPI documentation. Use when creating or modifying API endpoints, routers, or schemas.
allowed-tools: Read, Edit, Bash, Grep, Glob
---

# FastAPI Development Standards

This skill guides development of FastAPI endpoints for the E-Signature Platform API.

## Endpoint Implementation Checklist

1. **Pydantic Models**: Always define request/response schemas in `app/schemas/`
2. **Error Handling**: Use error codes from esig-design.md Error Code Catalog
3. **Authentication**: Use `get_current_user` dependency for protected routes
4. **Validation**: Implement constraints from esig-design.md (e.g., name 1-255 chars)
5. **Idempotency**: Create endpoints accept `Idempotency-Key` header
6. **Tests**: Write success, validation error, and auth error test cases

## Error Response Format

All errors must follow the standard format from esig-design.md:

```python
from fastapi import HTTPException

# Standard error response
raise HTTPException(
    status_code=404,
    detail={
        "error": {
            "code": "ENVELOPE_NOT_FOUND",
            "message": "Envelope does not exist",
            "details": {}
        }
    }
)
```

## Error Code Reference (esig-design.md)

| Code | HTTP Status | Use Case |
|------|-------------|----------|
| `AUTH_INVALID_CREDENTIALS` | 401 | Wrong email/password |
| `AUTH_TOKEN_EXPIRED` | 401 | Access token expired |
| `AUTH_TOKEN_INVALID` | 401 | Malformed token |
| `AUTH_REFRESH_TOKEN_INVALID` | 401 | Bad refresh token |
| `AUTH_EMAIL_NOT_VERIFIED` | 403 | Email verification required |
| `ENVELOPE_NOT_FOUND` | 404 | Envelope doesn't exist |
| `ENVELOPE_NOT_OWNED` | 403 | Can't access others' envelope |
| `ENVELOPE_INVALID_STATE` | 403 | Action not allowed in current state |
| `DOCUMENT_NOT_FOUND` | 404 | Document doesn't exist |
| `RECIPIENT_NOT_FOUND` | 404 | Recipient doesn't exist |
| `RECIPIENT_NOT_AUTHORIZED` | 403 | Invalid signing token |
| `SIGNING_ORDER_VIOLATION` | 403 | Not recipient's turn |
| `VALIDATION_ERROR` | 422 | Request body validation failed |
| `FILE_TOO_LARGE` | 413 | File exceeds size limit |
| `FILE_TYPE_INVALID` | 422 | File type not allowed |
| `REQUIRED_FIELDS_MISSING` | 422 | Required fields not filled |

## Authentication Patterns

```python
from app.dependencies import get_current_user, get_db
from app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession

# Protected endpoint (any authenticated user)
@router.get("/envelopes")
async def list_envelopes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ...

# Optional auth (for public signing endpoints)
@router.get("/signing/{token}")
async def get_signing_session(
    token: str,
    db: AsyncSession = Depends(get_db)
):
    # Validate signing token instead of JWT
    ...
```

## Pagination Pattern

Use cursor-based pagination:

```python
from app.schemas.common import PaginatedResponse

@router.get("/envelopes", response_model=PaginatedResponse[EnvelopeListItem])
async def list_envelopes(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Decode cursor, query with limit+1, encode next_cursor
    ...
    return {
        "items": envelopes[:limit],
        "next_cursor": encode_cursor(envelopes[limit].id) if len(envelopes) > limit else None
    }
```

## Idempotency Pattern

```python
from app.utils.idempotency import check_idempotency, store_idempotency

@router.post("/envelopes")
async def create_envelope(
    envelope_data: EnvelopeCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check for existing response
    if idempotency_key:
        cached = await check_idempotency(db, idempotency_key, user.id)
        if cached:
            return cached

    # Process request
    envelope = await create_envelope_impl(db, user.id, envelope_data)

    # Store for idempotency
    if idempotency_key:
        await store_idempotency(db, idempotency_key, user.id, envelope)

    return envelope
```

## Validation Constraints (from esig-design.md)

| Field | Constraint |
|-------|------------|
| `email` | Valid format, max 255 chars |
| `name` (user/recipient) | 1-100 chars |
| `name` (envelope) | 1-255 chars |
| `message` | max 10000 chars |
| `x_percent`, `y_percent` | 0-100 |
| `width_percent`, `height_percent` | 0-100 |
| File size (PDF) | max 10MB |
| File size (signature image) | max 500KB |

## After Implementation

Run these commands after creating/modifying endpoints:

```bash
# Format code
ruff format backend/

# Type check
uv run mypy app/

# Run tests for the module
uv run pytest tests/test_<module>.py -v
```

## File Organization

```
app/
├── routers/<resource>.py    # Endpoint definitions
├── schemas/<resource>.py    # Pydantic models
├── models/<resource>.py     # SQLAlchemy models
└── services/<resource>.py   # Business logic (if complex)
```
