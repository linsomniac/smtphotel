# smtphotel

SMTP Hotel.  Your mail checks in, but it doesn't check out!

A lightweight development SMTP server that captures all incoming
email. Perfect for testing email functionality in development environments
without sending real emails.  Provides a web interface and REST API for
viewing/managing messages, perfect for integrating into testing.

## Features

- **REST API** - Programmatic access to all captured messages
- **Web interface** - Browse, search, and view captured emails
- **Captures all email** - Accepts mail to any recipient address
- **No forwarding** - Messages are stored locally, never sent externally
- **No bounces** - Never generates bounce or error messages
- **Automatic pruning** - Configure retention by age, count, or storage size
- **Docker ready** - Simple deployment with Docker or Docker Compose

## Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/smtphotel.git
cd smtphotel

# Start the server
docker compose up -d

# View logs
docker compose logs -f
```

### Using Docker

```bash
docker build -t smtphotel .
docker run -d -p 2525:2525 -p 8025:8025 -v smtphotel_data:/data smtphotel
```

### Using Python (Development)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Run the server
uv run python -m smtphotel.main
```

## Usage

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Web UI | http://localhost:8025 | Browse captured emails |
| API Docs | http://localhost:8025/api/docs | Interactive API documentation |
| SMTP Server | localhost:2525 | Send emails here |

### Sending Test Emails

Configure your application to use `localhost:2525` as the SMTP server. For example:

**Python (smtplib)**
```python
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg["Subject"] = "Test Email"
msg["From"] = "sender@example.com"
msg["To"] = "recipient@example.com"
msg.set_content("Hello from smtphotel!")

with smtplib.SMTP("localhost", 2525) as smtp:
    smtp.send_message(msg)
```

**Django**
```python
# settings.py
EMAIL_HOST = "localhost"
EMAIL_PORT = 2525
EMAIL_USE_TLS = False
```

**Node.js (Nodemailer)**
```javascript
const nodemailer = require('nodemailer');

const transporter = nodemailer.createTransport({
  host: 'localhost',
  port: 2525,
  secure: false,
});

await transporter.sendMail({
  from: 'sender@example.com',
  to: 'recipient@example.com',
  subject: 'Test Email',
  text: 'Hello from smtphotel!',
});
```

## Configuration

All configuration is done via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_PORT` | 2525 | SMTP server port |
| `HTTP_PORT` | 8025 | HTTP server port (API + Web UI) |
| `BIND_ADDRESS` | 127.0.0.1 | Bind address (use 0.0.0.0 to expose) |
| `DB_PATH` | /data/smtphotel.db | SQLite database path |
| `MAX_MESSAGE_AGE_HOURS` | 0 | Delete messages older than N hours (0 = disabled) |
| `MAX_MESSAGE_COUNT` | 0 | Keep only N most recent messages (0 = disabled) |
| `MAX_STORAGE_MB` | 0 | Maximum total storage in MB (0 = unlimited) |
| `PRUNE_INTERVAL_SECONDS` | 300 | How often to run pruning (5 minutes) |
| `MAX_MESSAGE_SIZE_MB` | 25 | Maximum message size in MB |
| `MAX_CONNECTIONS` | 100 | Maximum concurrent SMTP connections |
| `SMTP_TIMEOUT_SECONDS` | 60 | SMTP connection timeout |
| `RATE_LIMIT_PER_MINUTE` | 0 | Max messages per IP per minute (0 = disabled) |
| `CORS_ORIGINS` | | Allowed CORS origins (empty = same-origin only) |

## REST API

### Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/messages` | List all messages (paginated) |
| GET | `/api/messages/{id}` | Get message details |
| GET | `/api/messages/{id}/raw` | Get raw RFC822 message |
| GET | `/api/messages/{id}/attachments` | List message attachments |
| GET | `/api/messages/{id}/attachments/{aid}` | Download attachment |
| DELETE | `/api/messages/{id}` | Delete a message |
| DELETE | `/api/messages?confirm=true` | Delete all messages |

### Utility

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/stats` | Server statistics |
| POST | `/api/prune` | Trigger manual prune |
| POST | `/api/vacuum` | Reclaim database space |

### Example API Usage

```bash
# List recent messages
curl http://localhost:8025/api/messages

# Get a specific message
curl http://localhost:8025/api/messages/{message-id}

# Download raw message
curl http://localhost:8025/api/messages/{message-id}/raw

# Get server statistics
curl http://localhost:8025/api/stats

# Delete all messages
curl -X DELETE "http://localhost:8025/api/messages?confirm=true"
```

## Security

**smtphotel is designed for development use only.**

- By default, it binds to `127.0.0.1` (localhost only)
- Captured messages may contain sensitive data - treat them accordingly
- Never expose smtphotel to the public internet
- For shared development environments, use a reverse proxy with authentication

## Development

```bash
# Install dependencies (including dev)
uv sync

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=smtphotel

# Run linter
uv run ruff check src/ tests/

# Run type checker
uv run mypy src/

# Format code
uv run ruff format src/ tests/
```

## License

CC0 1.0 Universal - See LICENSE file for details.
