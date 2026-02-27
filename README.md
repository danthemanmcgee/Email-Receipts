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
- **Independent Gmail and Drive Google accounts** — read from inbox A, store in Drive B

## Quick Start (Docker)

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env — set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, APP_SECRET_KEY
```

### 2. Start services

```bash
docker compose up --build
```

The app will be available at http://localhost:8000

- **UI**: http://localhost:8000/ui
- **Settings**: http://localhost:8000/ui/settings
- **API Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health

### 3. Run database migrations

```bash
docker compose exec app alembic upgrade head
```

### 4. Connect Google accounts

Open http://localhost:8000/ui/settings and connect both accounts:

| Card | Account | What it does |
|------|---------|--------------|
| 📬 Gmail Connection | Your source inbox (e.g. `receipts@gmail.com`) | Reads forwarded purchase emails |
| 📁 Drive Connection | Your storage account (e.g. `storage@gmail.com`) | Uploads canonical receipt PDFs |

Gmail and Drive **may be the same account or different accounts** — this is fully supported.

## Google OAuth Setup

### 1. Enable APIs in Google Cloud Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Gmail API** and **Google Drive API**
4. Navigate to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth 2.0 Client ID**
6. Choose **Web application** type
7. Add `http://localhost:8000/auth/google/callback` to **Authorised redirect URIs**
8. Copy the **Client ID** and **Client Secret** into your `.env`:

```env
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/auth/google/callback
APP_SECRET_KEY=generate-a-strong-random-string
```

### 2. Connect accounts via UI

1. Open http://localhost:8000/ui/settings
2. Click **Connect Gmail** — sign in with your *source inbox* account
3. Click **Connect Drive** — sign in with your *storage Drive* account
4. Both connections are saved independently in the database

### 3. OAuth scopes used

| Connection | Scopes |
|-----------|--------|
| Gmail | `gmail.readonly`, `gmail.modify`, `openid`, `userinfo.email` |
| Drive | `drive.file`, `openid`, `userinfo.email` |

Tokens are stored per-connection in the `google_connections` table and refreshed automatically.

### Connecting Gmail and Drive to different Google accounts

This is the primary use case:

1. **Connect Gmail** with account A (your forwarding inbox)
2. **Connect Drive** with account B (your file storage)

The Settings page will show an informational notice when the two connected emails differ — this is normal and expected.

## Gmail Label Setup

Create these labels in Gmail for best results:
- `receipt/new` — tag incoming receipts
- `receipt/processed` — applied automatically after successful processing
- `receipt/needs-review` — applied for low-confidence or missing-Drive receipts
- `receipt/failed` — applied on processing errors

## Running Sync & Cleanup Manually

```bash
# Trigger Gmail sync (requires Gmail connection)
curl -X POST http://localhost:8000/gmail/sync

# Check integration status
curl http://localhost:8000/integrations/google/status

# Trigger cleanup
curl -X POST http://localhost:8000/jobs/cleanup
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/gmail/sync` | Trigger Gmail sync (503 if Gmail not connected) |
| `GET` | `/receipts` | List receipts (filters: status, date_from, date_to) |
| `GET` | `/receipts/{id}` | Get receipt detail |
| `POST` | `/receipts/{id}/reprocess` | Reprocess a receipt |
| `POST` | `/receipts/{id}/resolve-card` | Assign card to receipt |
| `GET` | `/cards` | List physical cards |
| `POST` | `/cards` | Create physical card |
| `POST` | `/cards/{id}/aliases` | Add card alias |
| `POST` | `/jobs/cleanup` | Run retention cleanup |
| `GET` | `/health` | Health check |
| `GET` | `/integrations/google/status` | Gmail + Drive connection status |
| `GET` | `/auth/google/gmail/start` | Begin Gmail OAuth flow |
| `GET` | `/auth/google/drive/start` | Begin Drive OAuth flow |
| `GET` | `/auth/google/callback` | OAuth callback (both flows) |

## Architecture

```
Gmail API (account A) → Celery Worker → PostgreSQL
                            ↓
            Attachment Scoring (PDF selection)
                            ↓
            Text/PDF Extraction (regex)
                            ↓
            Card Resolution (alias lookup)
                            ↓
       Google Drive Upload (account B)
                            ↓
            FastAPI + Jinja2 UI
```

### Components

- **FastAPI** — REST API + Jinja2 template UI
- **Celery + Redis** — Async task queue for Gmail polling and processing
- **PostgreSQL** — Receipt storage with Alembic migrations
- **Gmail API** — Email fetching and labeling (separate OAuth connection)
- **Google Drive API** — PDF file storage (separate OAuth connection)
- **PyPDF2** — PDF text extraction

### Processing Pipeline

1. `sync_gmail` task polls Gmail for new messages using the **gmail** connection
2. Each new message queues a `process_receipt_task`
3. Task fetches email, scores PDF attachments, selects best PDF
4. Extracts merchant/date/amount/card via regex
5. Resolves card using alias table
6. Uploads canonical PDF to Drive using the **drive** connection
   - If Drive is not connected: receipt is marked `needs_review` with reason `drive_not_connected`
7. Sets status to `processed` (confidence ≥ threshold) or `needs_review`

## Troubleshooting

### Gmail sync returns 503 "gmail_not_connected"

The Gmail OAuth connection has not been set up.

1. Ensure `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` are set in `.env`
2. Run `docker compose restart app`
3. Visit http://localhost:8000/ui/settings and click **Connect Gmail**

### Receipts land in needs-review with "drive_not_connected"

The Drive OAuth connection has not been set up or has expired.

1. Visit http://localhost:8000/ui/settings and click **Connect Drive** (or **Reconnect Drive**)
2. After reconnecting, use `POST /receipts/{id}/reprocess` to reprocess the affected receipts

### Drive upload fails — "Drive root folder not accessible"

The configured Drive root folder ID is invalid or inaccessible. Common causes:

- **Wrong folder ID** — the ID belongs to a different account or has been deleted.
  Find a valid folder ID from your Drive URL: `https://drive.google.com/drive/folders/<FOLDER_ID>`
- **Account mismatch** — the Drive connection is authenticated as account B but the folder was shared with account A. Make sure the folder is **owned by or explicitly shared with** the Drive-connected account.
- **Missing sharing** — if you share a folder with the Drive account, the account must accept the share.

The worker logs a detailed message when this happens, for example:
```
ERROR Drive root folder 'xyz...' is not accessible (check folder ID, account ownership, and sharing): <HttpError 404 ...>
```

**How to obtain a valid Drive folder ID:**

1. Open [Google Drive](https://drive.google.com/) as the Drive-connected account.
2. Navigate to or create the folder where receipts should be stored.
3. The folder ID appears in the browser URL after `/folders/`: `https://drive.google.com/drive/folders/<FOLDER_ID>`
4. Paste that ID into the **Drive root folder** field on the Settings page.

### Gmail label conflicts (409)

Label creation is idempotent — if a `409 Conflict` is returned by the Gmail API (e.g., the label already exists from a previous run), the worker re-fetches the existing label and continues without error.

### Both accounts show "Not connected" after restart

OAuth tokens are stored in the database and persist across restarts automatically.
If tokens are lost, reconnect via the Settings page.

### "Token exchange failed" during OAuth

- Ensure the redirect URI in Google Cloud Console exactly matches `GOOGLE_OAUTH_REDIRECT_URI` in `.env`
- Ensure the OAuth app is not in "Testing" mode with restricted test users (or add your account as a test user)

### Migrating from single-connection setup

If you previously used a `token.json` file with combined Gmail + Drive scopes, the app will continue to use that file as a fallback until you connect accounts via the Settings page. Once you connect via Settings, the DB tokens take priority.

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
| `GOOGLE_OAUTH_CLIENT_ID` | — | OAuth client ID (web app type) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | — | OAuth client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | http://localhost:8000/auth/google/callback | OAuth redirect URI |
| `APP_SECRET_KEY` | change-me | Secret key for OAuth state signing |
| `GMAIL_CREDENTIALS_FILE` | /secrets/credentials.json | Legacy file-based OAuth credentials |
| `GMAIL_TOKEN_FILE` | /secrets/token.json | Legacy file-based OAuth token (fallback) |
| `GMAIL_POLL_INTERVAL_SECONDS` | 300 | Polling interval |
| `DRIVE_ROOT_FOLDER` | Receipts | Drive folder root |
| `CONFIDENCE_THRESHOLD` | 0.75 | Min confidence for auto-process |
| `RETENTION_DAYS_PROCESSED` | 45 | Days to keep processed receipts |
| `RETENTION_DAYS_REVIEW` | 90 | Days to keep review/failed receipts |
| `MAX_ATTACHMENT_SIZE_MB` | 25 | Max PDF attachment size |

