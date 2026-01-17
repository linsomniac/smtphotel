# Changelog

All notable changes to smtphotel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-01-16

### Added

- Initial release of smtphotel development SMTP server
- **SMTP Server**
  - Accept email to any recipient address
  - Configurable message size limits (default 25MB)
  - Per-IP rate limiting
  - Maximum concurrent connection limits
  - Connection timeout handling
  - Never forwards email or generates bounces
- **REST API**
  - List messages with pagination, search, and sorting
  - Get message details with headers and body content
  - Download raw RFC822 messages
  - List and download attachments
  - Delete individual messages or all messages
  - Health check endpoint
  - Statistics endpoint (message count, storage size, oldest/newest message)
  - Manual prune trigger
  - Database vacuum endpoint
  - Security headers on all responses (X-Content-Type-Options, X-Frame-Options, CSP)
  - Restrictive CORS (same-origin only by default)
- **Web Interface**
  - Responsive design with light/dark theme support
  - Message list with columns for received time, from, to, subject, size, attachment indicator
  - Pagination for message list
  - Search and filter functionality
  - Sort by column
  - Message detail view with expandable headers
  - Plain text and HTML body views (HTML rendered in sandboxed iframe)
  - Attachment list with download links
  - View raw message
  - Delete individual messages or all messages
  - Auto-refresh toggle
  - Toast notifications
  - Keyboard shortcuts (j/k navigation, r refresh, d delete)
  - Loading states for async operations
- **Storage**
  - SQLite database with WAL mode for better concurrency
  - Store message headers, plain text body, HTML body, and raw message
  - Store attachments with original filename and MIME type
  - Age-based pruning (configurable MAX_MESSAGE_AGE_HOURS)
  - Count-based pruning (configurable MAX_MESSAGE_COUNT)
  - Storage-based pruning (configurable MAX_STORAGE_MB)
  - Background pruning task with configurable interval
  - Database integrity checking
- **Docker Support**
  - Multi-stage Dockerfile with slim Python base image
  - Non-root user for security
  - Healthcheck configuration
  - Docker Compose file for easy deployment
  - Volume support for persistent data
- **Security**
  - Localhost binding by default (127.0.0.1)
  - No authentication (development tool for trusted networks)
  - Sandboxed iframe for HTML email rendering (no scripts, no same-origin)
  - XSS prevention with HTML escaping
  - Input validation on all endpoints
  - Startup warning about sensitive data in captured emails

### Security

- Bound to localhost by default to prevent accidental exposure
- HTML emails rendered in strict sandbox to prevent XSS attacks
- Rate limiting to prevent abuse
- Connection limits to prevent resource exhaustion
