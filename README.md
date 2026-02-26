# Email Receipts

A local-first MVP web service for automated receipt processing from Gmail.

## Overview

Email Receipts polls your Gmail inbox for receipt emails, extracts key data (merchant, date, amount, card), organizes PDFs in Google Drive, and provides a web UI for review and management.

**Key features:**
- Gmail polling with Celery workers
- PDF attachment scoring and selection
- Text/PDF data extraction via regex
- Card alias resolution
- Google Drive file organization
- Needs-review queue for low-confidence extractions
- Bootstrap 5 admin UI

## Quick Start (Docker)

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env if needed
```

### 2. Add Google credentials (optional for local testing)

```bash
mkdir -p secrets
# Place your credentials.json in secrets/
```

### 3. Start services

```bash
docker compose up --build
```

The app will be available at http://localhost:8000

- **UI**: http://localhost:8000/ui
- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health

### 4. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

## Google OAuth Setup

### Enable APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Gmail API** and **Google Drive API**
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download `credentials.json` → place in `./secrets/credentials.json`

### Authorize

On first run, the worker will attempt to open a browser for OAuth. For headless servers:

```bash
# Run locally first to generate token.json
python -c "
from app.services.gmail_service import build_gmail_service
build_gmail_service('secrets/credentials.json', 'secrets/token.json')
"
# Then copy secrets/token.json to your server
```

## Gmail Label Setup

Create these labels in Gmail for best results:
- `receipt/new` — tag incoming receipts
- `receipt/processed` — applied automatically
- `receipt/needs-review` — applied for low-confidence
- `receipt/failed` — applied on error

## Running Sync & Cleanup Manually

```bash
# Trigger Gmail sync
curl -X POST http://localhost:8000/gmail/sync

# Trigger cleanup
curl -X POST http://localhost:8000/jobs/cleanup
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gmail/sync` | Trigger Gmail sync |
| `GET` | `/receipts` | List receipts (filters: status, date_from, date_to) |
| `GET` | `/receipts/{id}` | Get receipt detail |
| `POST` | `/receipts/{id}/reprocess` | Reprocess a receipt |
| `POST` | `/receipts/{id}/resolve-card` | Assign card to receipt |
| `GET` | `/cards` | List physical cards |
| `POST` | `/cards` | Create physical card |
| `POST` | `/cards/{id}/aliases` | Add card alias |
| `POST` | `/jobs/cleanup` | Run retention cleanup |
| `GET` | `/health` | Health check |

## Architecture

```
Gmail API → Celery Worker → PostgreSQL
                ↓
    Attachment Scoring (PDF selection)
                ↓
    Text/PDF Extraction (regex)
                ↓
    Card Resolution (alias lookup)
                ↓
    Google Drive Upload
                ↓
    FastAPI + Jinja2 UI
```

### Components

- **FastAPI** — REST API + Jinja2 template UI
- **Celery + Redis** — Async task queue for Gmail polling and processing
- **PostgreSQL** — Receipt storage with Alembic migrations
- **Gmail API** — Email fetching and labeling
- **Google Drive API** — PDF file storage
- **PyPDF2** — PDF text extraction

### Processing Pipeline

1. `sync_gmail` task polls Gmail for new messages
2. Each new message queues a `process_receipt_task`
3. Task fetches email, scores PDF attachments, selects best PDF
4. Extracts merchant/date/amount/card via regex
5. Resolves card using alias table
6. Sets status to `processed` (confidence ≥ threshold) or `needs_review`

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## Configuration

See `.env.example` for all environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | postgres://... | PostgreSQL connection |
| `REDIS_URL` | redis://... | Redis connection |
| `GMAIL_CREDENTIALS_FILE` | /secrets/credentials.json | OAuth credentials |
| `GMAIL_TOKEN_FILE` | /secrets/token.json | OAuth token |
| `GMAIL_POLL_INTERVAL_SECONDS` | 300 | Polling interval |
| `DRIVE_ROOT_FOLDER` | Receipts | Drive folder root |
| `CONFIDENCE_THRESHOLD` | 0.75 | Min confidence for auto-process |
| `RETENTION_DAYS_PROCESSED` | 45 | Days to keep processed receipts |
| `RETENTION_DAYS_REVIEW` | 90 | Days to keep review/failed receipts |
| `MAX_ATTACHMENT_SIZE_MB` | 25 | Max PDF attachment size |
