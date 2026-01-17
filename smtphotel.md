# smtphotel - Development SMTP Server PRD

## Overview

**smtphotel** is a Docker-containerized development SMTP server that captures all incoming email without forwarding or generating bounces. It provides a web interface and REST API for viewing captured messages, making it ideal for development and testing environments.

## Core Principles

- **Never forward email** - All messages are captured locally
- **Never send bounces** - No bounce or double-bounce messages generated
- **Reject at SMTP time** - All mail rejection happens during SMTP transaction
- **Accept any address** - Server accepts mail to any recipient address
- **Simple and joyful** - Web interface should be intuitive and pleasant to use

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| SMTP Server | aiosmtpd |
| REST API | FastAPI |
| Database | SQLite |
| Frontend | Vanilla HTML/CSS/JS |
| Package Manager | uv |
| Linting/Formatting | ruff |
| Container | Docker |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Container                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │ SMTP Server │    │  REST API   │    │     Web     │  │
│  │   :2525     │───▶│   :8025     │◀───│  Interface  │  │
│  │  (aiosmtpd) │    │  (FastAPI)  │    │  (static)   │  │
│  └──────┬──────┘    └──────┬──────┘    └─────────────┘  │
│         │                  │                             │
│         └────────┬─────────┘                             │
│                  ▼                                       │
│         ┌───────────────┐                                │
│         │    SQLite     │                                │
│         │   Database    │                                │
│         └───────────────┘                                │
└─────────────────────────────────────────────────────────┘
```

## Configuration

Environment variables for configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_PORT` | 2525 | SMTP server port |
| `HTTP_PORT` | 8025 | HTTP server port (API + Web UI) |
| `DB_PATH` | `/data/smtphotel.db` | SQLite database path |
| `MAX_MESSAGE_AGE_HOURS` | 0 | Delete messages older than N hours (0 = disabled) |
| `MAX_MESSAGE_COUNT` | 0 | Keep only N most recent messages (0 = disabled) |
| `PRUNE_INTERVAL_SECONDS` | 300 | How often to run pruning (5 min default) |
| `MAX_MESSAGE_SIZE_MB` | 25 | Maximum message size in MB |
| `BIND_ADDRESS` | `127.0.0.1` | Bind address for SMTP and HTTP (use `0.0.0.0` to expose) |
| `MAX_STORAGE_MB` | 0 | Maximum total storage in MB (0 = unlimited) |
| `MAX_CONNECTIONS` | 100 | Maximum concurrent SMTP connections |
| `SMTP_TIMEOUT_SECONDS` | 60 | SMTP connection timeout |
| `RATE_LIMIT_PER_MINUTE` | 0 | Max messages per IP per minute (0 = disabled) |
| `CORS_ORIGINS` | `""` | Allowed CORS origins (empty = same-origin only) |

---

## Threat Model

### Intended Use Environment

smtphotel is designed **exclusively for development and testing environments**. It should:

- Run on developer machines or isolated CI/CD environments
- Be accessed only from trusted networks (localhost or private networks)
- Never be exposed to the public internet
- Never handle real/production email

### Trust Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRUSTED ZONE (localhost/private network)     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  Developer   │    │  Test Suite  │    │   CI/CD      │       │
│  │   Browser    │    │   (httpx)    │    │   Runner     │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             ▼                                   │
│                    ┌─────────────────┐                          │
│                    │   smtphotel     │                          │
│                    │  (SMTP + HTTP)  │                          │
│                    └─────────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
          ▲
          │ UNTRUSTED: Never expose ports externally
          │
    ┌─────┴─────┐
    │  Internet │
    └───────────┘
```

### Threat Mitigations

| Threat | Mitigation |
|--------|------------|
| Unauthorized access to emails | Bind to localhost by default; document reverse-proxy auth for shared envs |
| Cross-site data theft (CORS) | Restrict CORS to same-origin by default; require explicit allowlist |
| XSS via HTML email content | Strict iframe sandbox; CSP headers; no `allow-same-origin` |
| Disk exhaustion (DoS) | Configurable storage cap; message count/age limits; rate limiting |
| SMTP abuse | Connection limits; per-IP rate limiting; timeouts |
| Data leakage via logs | Avoid logging email bodies; log only metadata |

---

## Security Defaults

### Network Binding

- **Default bind: `127.0.0.1`** - Only accessible from localhost
- To expose to other machines, explicitly set `BIND_ADDRESS=0.0.0.0`
- Document that exposing requires additional protection (VPN, firewall, reverse proxy with auth)

### CORS Policy

- **Default: Same-origin only** - No cross-origin requests allowed
- To allow cross-origin (e.g., for separate frontend dev server), set `CORS_ORIGINS=http://localhost:3000`
- Never use `*` wildcard in shared environments

### HTML Email Rendering

The web UI must render HTML emails safely to prevent XSS:

- Render HTML in `<iframe>` with strict sandbox attributes:
  ```html
  <iframe sandbox="allow-popups allow-popups-to-escape-sandbox"
          srcdoc="..."
          csp="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:;">
  </iframe>
  ```
- **Never use `allow-same-origin`** - This would allow scripts to access the parent page
- **Never use `allow-scripts`** - Disable JavaScript execution entirely
- Set `X-Content-Type-Options: nosniff` on all responses
- Set `Content-Security-Policy` headers on the main application

### Input Sanitization

- All user-visible text (headers, subjects, addresses) must be HTML-escaped before rendering
- Use safe templating (auto-escaping) or explicit escaping functions
- Never render raw header values or body content outside the sandboxed iframe

### Sensitive Data Handling

- **Logs**: Only log message metadata (from, to, subject, size) - never log bodies
- **PII Warning**: Add startup banner warning that captured emails may contain sensitive data
- **Retention**: Encourage setting `MAX_MESSAGE_AGE_HOURS` to auto-delete old messages

---

## Implementation Phases

### Phase 1: Project Setup & Core Infrastructure

#### 1.1 Project Structure
- [X] Create project directory structure:
  ```
  smtphotel/
  ├── src/
  │   └── smtphotel/
  │       ├── __init__.py
  │       ├── main.py
  │       ├── config.py
  │       ├── smtp/
  │       │   ├── __init__.py
  │       │   └── server.py
  │       ├── api/
  │       │   ├── __init__.py
  │       │   ├── routes.py
  │       │   └── schemas.py
  │       ├── storage/
  │       │   ├── __init__.py
  │       │   ├── database.py
  │       │   └── models.py
  │       └── web/
  │           └── static/
  │               ├── index.html
  │               ├── style.css
  │               └── app.js
  ├── tests/
  │   ├── __init__.py
  │   ├── conftest.py
  │   ├── test_smtp.py
  │   ├── test_api.py
  │   └── test_storage.py
  ├── pyproject.toml
  ├── Dockerfile
  ├── docker-compose.yml
  └── README.md
  ```
- [X] Initialize git repository with `.gitignore`

#### 1.2 Python Project Configuration
- [X] Create `pyproject.toml` with uv-compatible configuration
- [X] Configure dependencies:
  - `aiosmtpd` - SMTP server
  - `fastapi` - REST API framework
  - `uvicorn` - ASGI server
  - `aiosqlite` - Async SQLite
  - `python-multipart` - Form/file handling
  - `pydantic` - Data validation
  - `pydantic-settings` - Configuration management
- [X] Configure dev dependencies:
  - `pytest` - Testing
  - `pytest-asyncio` - Async test support
  - `pytest-cov` - Coverage reporting
  - `httpx` - Async HTTP client for testing
  - `ruff` - Linting and formatting
- [X] Configure ruff in `pyproject.toml`:
  - Enable recommended rules
  - Set line length to 88
  - Configure import sorting

#### 1.3 Configuration Management
- [X] Create `config.py` with pydantic-settings
- [X] Define all environment variables with defaults
- [X] Add validation for configuration values
- [X] Create singleton configuration instance

#### 1.4 Database Schema
- [X] Create SQLite schema with tables:
  - `messages` - Store email messages
    - `id` (TEXT, PRIMARY KEY) - UUID
    - `received_at` (TIMESTAMP) - When message was received
    - `mail_from` (TEXT) - Envelope sender
    - `rcpt_to` (TEXT, JSON array) - Envelope recipients
    - `subject` (TEXT) - Parsed subject header
    - `headers` (TEXT, JSON) - All headers as JSON
    - `body_text` (TEXT) - Plain text body
    - `body_html` (TEXT) - HTML body
    - `raw` (BLOB) - Raw message bytes
    - `size_bytes` (INTEGER) - Message size
  - `attachments` - Store message attachments
    - `id` (TEXT, PRIMARY KEY) - UUID
    - `message_id` (TEXT, FK) - Parent message
    - `filename` (TEXT) - Original filename
    - `content_type` (TEXT) - MIME type
    - `size_bytes` (INTEGER) - Attachment size
    - `content` (BLOB) - Attachment data
- [X] Create database initialization function
- [X] Add indexes for common queries (received_at, mail_from, subject)
- [X] Enable WAL mode for better concurrency (`PRAGMA journal_mode=WAL`)
- [X] Configure busy timeout for concurrent access (`PRAGMA busy_timeout=5000`)
- [X] Add storage size tracking for `MAX_STORAGE_MB` enforcement

---

### Phase 2: SMTP Server

#### 2.1 SMTP Handler
- [X] Create custom SMTP handler class extending `aiosmtpd`
- [X] Implement `handle_RCPT` - Accept any recipient address
- [X] Implement `handle_DATA` - Parse and store message
- [X] Implement message size limits
- [X] Add logging for all SMTP transactions

#### 2.2 Message Parsing
- [X] Parse email using Python's `email` module
- [X] Extract envelope information (MAIL FROM, RCPT TO)
- [X] Extract and decode headers (handle encodings)
- [X] Extract plain text body (handle multipart)
- [X] Extract HTML body (handle multipart/alternative)
- [X] Extract attachments from multipart messages
- [X] Store raw message for complete fidelity

#### 2.3 SMTP Abuse Controls
- [X] Implement maximum concurrent connection limit (`MAX_CONNECTIONS`)
- [X] Add per-connection timeout (`SMTP_TIMEOUT_SECONDS`)
- [X] Implement per-IP rate limiting (`RATE_LIMIT_PER_MINUTE`)
- [X] Add per-session message limit (prevent single connection flooding)
- [X] Track and log connection metadata (IP, connection time, message count)

#### 2.4 SMTP Server Management
- [X] Create async SMTP server startup function
- [X] Configure server to listen on configurable address and port
- [X] Bind to `127.0.0.1` by default (require explicit opt-in for network exposure)
- [X] Implement graceful shutdown
- [X] Add health check endpoint support
- [X] Log startup banner with security warning about sensitive data

---

### Phase 3: REST API

#### 3.1 API Foundation
- [X] Create FastAPI application instance
- [X] Configure CORS with restrictive defaults:
  - Same-origin only by default (no CORS headers)
  - Allow explicit origin allowlist via `CORS_ORIGINS` env var
  - Never allow `*` wildcard - require explicit origins
- [X] Set security headers on all responses:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy` for main app pages
- [X] Mount static files directory for web UI
- [X] Add OpenAPI documentation customization
- [X] Create dependency for database session
- [X] Bind HTTP server to `BIND_ADDRESS` (default `127.0.0.1`)

#### 3.2 Message Endpoints
- [X] `GET /api/messages` - List messages
  - Query params: `limit`, `offset`, `search`, `sort`
  - Return paginated list with metadata
- [X] `GET /api/messages/{id}` - Get single message
  - Return full message with headers and bodies
- [X] `GET /api/messages/{id}/raw` - Get raw message
  - Return original message as `message/rfc822`
- [X] `GET /api/messages/{id}/attachments` - List attachments
  - Return attachment metadata
- [X] `GET /api/messages/{id}/attachments/{attachment_id}` - Download attachment
  - Return attachment with proper Content-Type
- [X] `DELETE /api/messages/{id}` - Delete single message
- [X] `DELETE /api/messages` - Delete all messages
  - Require confirmation query param

#### 3.3 Utility Endpoints
- [X] `GET /api/health` - Health check
  - Return server status, message count, database status
- [X] `GET /api/stats` - Statistics
  - Return message count, storage size, oldest/newest message
- [X] `POST /api/prune` - Trigger manual prune
  - Accept optional age/count parameters

#### 3.4 Pydantic Schemas
- [X] Create request/response schemas for all endpoints
- [X] Add proper validation and examples
- [X] Document all fields

---

### Phase 4: Web Interface

#### 4.1 Layout and Structure
- [X] Create responsive HTML layout
- [X] Design clean, modern CSS styling
- [X] Use CSS Grid/Flexbox for layout
- [X] Support light/dark theme (system preference)
- [X] Create mobile-friendly responsive design

#### 4.2 Message List View
- [X] Display message list with columns:
  - Received time (relative and absolute)
  - From address
  - To address(es)
  - Subject
  - Size
  - Attachment indicator
- [X] Implement infinite scroll or pagination
- [X] Add search/filter functionality
- [X] Add sort by column
- [X] Show empty state when no messages
- [X] Add "Delete All" button with confirmation

#### 4.3 Message Detail View
- [X] Create expandable/modal message detail view
- [X] Display headers in collapsible section (HTML-escaped)
- [X] Show plain text body with proper formatting (HTML-escaped, preserve whitespace)
- [X] Render HTML body in strictly sandboxed iframe:
  - Use `sandbox="allow-popups allow-popups-to-escape-sandbox"` only
  - **Never** use `allow-same-origin` or `allow-scripts`
  - Use `srcdoc` attribute to inject content
  - Set iframe-level CSP via `csp` attribute
- [X] Toggle between text/HTML views
- [X] List attachments with download links
- [X] Add "View Raw" button
- [X] Add "Delete" button
- [X] Ensure all dynamic content is properly escaped to prevent XSS

#### 4.4 User Experience
- [X] Add auto-refresh toggle for message list
- [X] Show toast notifications for actions
- [X] Add keyboard shortcuts (j/k navigation, r refresh, d delete)
- [X] Implement smooth animations/transitions
- [X] Add loading states for all async operations

---

### Phase 5: Message Store Management

#### 5.1 Pruning Logic
- [X] Implement age-based pruning function
- [X] Implement count-based pruning function
- [X] Create combined pruning logic respecting both limits
- [X] Delete associated attachments when pruning messages
- [X] Add logging for prune operations

#### 5.2 Background Pruning Task
- [X] Create async background task for periodic pruning
- [X] Respect `PRUNE_INTERVAL_SECONDS` configuration
- [X] Handle task cancellation on shutdown
- [X] Log prune results (count deleted, space freed)

#### 5.3 Database Maintenance
- [X] Add SQLite VACUUM support (manual trigger via API)
- [X] Implement database size reporting
- [X] Add integrity check endpoint

---

### Phase 6: Testing & Quality

#### 6.1 Test Infrastructure
- [X] Configure pytest with asyncio support
- [X] Create fixtures for:
  - Test database (in-memory SQLite)
  - Test SMTP client
  - Test HTTP client (httpx)
  - Sample email messages
- [X] Configure coverage reporting with pytest-cov

#### 6.2 SMTP Server Tests
- [X] Test accepting mail to any address
- [X] Test message size limits
- [X] Test multipart message parsing
- [X] Test attachment extraction
- [X] Test header decoding (various encodings)
- [X] Test malformed message handling
- [X] Test concurrent connections

#### 6.3 REST API Tests
- [X] Test all message endpoints (CRUD)
- [X] Test pagination and sorting
- [X] Test search functionality
- [X] Test attachment download
- [X] Test raw message retrieval
- [X] Test health and stats endpoints
- [X] Test prune endpoint
- [X] Test error responses

#### 6.4 Storage Tests
- [X] Test message storage and retrieval
- [X] Test attachment storage
- [X] Test age-based pruning
- [X] Test count-based pruning
- [X] Test database initialization
- [X] Test concurrent access

#### 6.5 Integration Tests
- [X] Test full flow: send email via SMTP → retrieve via API
- [X] Test pruning doesn't affect active retrievals
- [X] Test server startup and shutdown

#### 6.6 Code Quality
- [X] Configure ruff for linting
- [X] Configure ruff for formatting
- [ ] Add pre-commit hooks (optional)
- [X] Achieve minimum 80% code coverage
- [X] Add type hints to all functions
- [X] Run mypy for type checking

---

### Phase 7: Docker & Deployment

#### 7.1 Dockerfile
- [X] Create multi-stage Dockerfile
- [X] Use slim Python base image
- [X] Install uv in build stage
- [X] Copy only necessary files
- [X] Create non-root user for running
- [X] Expose SMTP and HTTP ports
- [X] Set up healthcheck
- [X] Configure proper signal handling

#### 7.2 Docker Compose
- [X] Create `docker-compose.yml` for easy local use
- [X] Configure volume for persistent data
- [X] Set sensible default environment variables
- [X] Add example compose file with all options documented

#### 7.3 Documentation
- [X] Write comprehensive README.md
  - Quick start guide
  - Configuration reference
  - API documentation link
  - Example usage with common frameworks
- [X] Add CHANGELOG.md
- [X] Add LICENSE file (choose appropriate license)

#### 7.4 Final Integration
- [X] Test complete Docker build
- [X] Test container startup and shutdown
- [X] Test data persistence across restarts
- [X] Test all features in containerized environment
- [X] Verify memory usage is reasonable
- [X] Test with realistic load

---

## API Reference

### Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/messages` | List all messages (paginated) |
| GET | `/api/messages/{id}` | Get message details |
| GET | `/api/messages/{id}/raw` | Get raw RFC822 message |
| GET | `/api/messages/{id}/attachments` | List message attachments |
| GET | `/api/messages/{id}/attachments/{aid}` | Download attachment |
| DELETE | `/api/messages/{id}` | Delete a message |
| DELETE | `/api/messages` | Delete all messages |

### Utility

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/stats` | Server statistics |
| POST | `/api/prune` | Trigger manual prune |

---

## Non-Functional Requirements

### Performance
- Handle at least 100 concurrent SMTP connections
- API response time < 100ms for list operations
- Support messages up to 25MB by default

### Security
- **Network isolation by default** - Bind to `127.0.0.1`; require explicit opt-in for network exposure
- **No authentication** - Development tool; trusted network assumed; document reverse-proxy auth for shared envs
- **Restrictive CORS** - Same-origin only by default; explicit allowlist required
- **Sandboxed HTML rendering** - Strict iframe sandbox; no scripts; no same-origin access
- **XSS prevention** - All dynamic content HTML-escaped; CSP headers set
- **No outbound connections** - Server never initiates external network requests
- **Abuse protection** - Connection limits, rate limiting, storage caps
- **Sensitive data awareness** - Startup warning; log only metadata; encourage retention limits

### Reliability
- Graceful handling of malformed emails
- Database corruption recovery
- Proper shutdown handling (no data loss)

---

## Future Considerations (Out of Scope)

These features are explicitly out of scope for initial implementation but may be considered later:

- [ ] WebSocket support for real-time message updates
- [ ] Email forwarding to external addresses
- [ ] SMTP authentication
- [ ] TLS/SSL support for SMTP
- [ ] Multiple mailbox/user support
- [ ] Email templates for testing
- [ ] Webhook notifications on new messages
- [ ] Prometheus metrics endpoint
- [ ] Kubernetes deployment manifests

---

## Success Criteria

The project is complete when:

1. All Phase 1-7 checklist items are marked complete
2. All tests pass with 80%+ code coverage
3. Docker container builds and runs successfully
4. A user can:
   - Send an email via SMTP to any address
   - View the email in the web interface
   - See headers, body (text and HTML), and attachments
   - Download attachments
   - Delete messages
   - Access messages via REST API for automated testing
5. Pruning works correctly based on configuration
6. The application handles edge cases gracefully
