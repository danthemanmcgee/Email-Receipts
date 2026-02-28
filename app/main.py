from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.routers import gmail, receipts, cards, jobs, health, auth, integrations
from app.routers import settings_router, upload
from app.database import engine
from app.models import receipt as receipt_models  # noqa: F401 - ensures models are registered
from app.models import card as card_models  # noqa: F401
from app.models import integration as integration_models  # noqa: F401
from app.models import setting as setting_models  # noqa: F401
from app.models import job as job_models  # noqa: F401
from app.models import user as user_models  # noqa: F401

app = FastAPI(title="Email Receipts", version="1.0.0")

# Include API routers
app.include_router(gmail.router, prefix="/gmail", tags=["gmail"])
app.include_router(receipts.router, prefix="/receipts", tags=["receipts"])
app.include_router(cards.router, prefix="/cards", tags=["cards"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(upload.router, prefix="/upload", tags=["upload"])

# Mount static files
app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

templates = Jinja2Templates(directory="app/ui/templates")


@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/", response_class=HTMLResponse)
async def ui_root(request: Request):
    return RedirectResponse(url="/ui/receipts")


@app.get("/ui/receipts", response_class=HTMLResponse)
async def ui_receipts(request: Request, status: str = "", skip: int = 0, limit: int = 50):
    from app.database import SessionLocal
    from app.models.receipt import Receipt, ReceiptStatus

    with SessionLocal() as db:
        q = db.query(Receipt)
        if status and status != "all":
            try:
                q = q.filter(Receipt.status == ReceiptStatus(status))
            except ValueError:
                pass
        total = q.count()
        items = (
            q.options(selectinload(Receipt.physical_card))
            .order_by(Receipt.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "receipts": items,
            "total": total,
            "status_filter": status,
            "statuses": [s.value for s in ReceiptStatus],
        },
    )


@app.get("/ui/receipts/{receipt_id}", response_class=HTMLResponse)
async def ui_receipt_detail(request: Request, receipt_id: int):
    from app.database import SessionLocal
    from app.models.receipt import Receipt

    with SessionLocal() as db:
        receipt = (
            db.query(Receipt)
            .options(
                selectinload(Receipt.physical_card),
                selectinload(Receipt.attachment_logs),
            )
            .filter(Receipt.id == receipt_id)
            .first()
        )
        if not receipt:
            return HTMLResponse("Receipt not found", status_code=404)
        cards_list = []
        from app.models.card import PhysicalCard
        cards_list = db.query(PhysicalCard).all()

    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "receipt": receipt, "cards": cards_list},
    )


@app.get("/ui/review", response_class=HTMLResponse)
async def ui_review(request: Request):
    from app.database import SessionLocal
    from app.models.receipt import Receipt, ReceiptStatus

    with SessionLocal() as db:
        items = (
            db.query(Receipt)
            .options(selectinload(Receipt.physical_card))
            .filter(Receipt.status == ReceiptStatus.needs_review)
            .order_by(Receipt.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        "review.html", {"request": request, "receipts": items}
    )


@app.get("/ui/upload", response_class=HTMLResponse)
async def ui_upload(request: Request):
    from app.database import SessionLocal
    from app.models.integration import GoogleConnection, ConnectionType
    from app.models.card import PhysicalCard

    with SessionLocal() as db:
        drive_conn = (
            db.query(GoogleConnection)
            .filter(
                GoogleConnection.connection_type == ConnectionType.drive,
                GoogleConnection.is_active.is_(True),
            )
            .first()
        )
        cards = db.query(PhysicalCard).order_by(PhysicalCard.display_name).all()

    from app.config import get_settings as _get_settings

    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "drive_connected": drive_conn is not None,
            "cards": cards,
            "max_size_mb": _get_settings().MAX_ATTACHMENT_SIZE_MB,
        },
    )


@app.get("/ui/settings", response_class=HTMLResponse)
async def ui_settings(request: Request):
    from app.database import SessionLocal
    from app.models.integration import GoogleConnection, ConnectionType
    from app.models.setting import AllowedSender
    from app.models.card import PhysicalCard
    from app.services.settings_service import get_drive_root_folder
    from sqlalchemy.orm import selectinload

    with SessionLocal() as db:
        gmail_conn = (
            db.query(GoogleConnection)
            .filter(
                GoogleConnection.connection_type == ConnectionType.gmail,
                GoogleConnection.is_active.is_(True),
            )
            .first()
        )
        drive_conn = (
            db.query(GoogleConnection)
            .filter(
                GoogleConnection.connection_type == ConnectionType.drive,
                GoogleConnection.is_active.is_(True),
            )
            .first()
        )
        allowed_senders = db.query(AllowedSender).order_by(AllowedSender.email).all()
        drive_root_folder = get_drive_root_folder(db)
        from app.services.settings_service import get_drive_root_folder_id
        drive_root_folder_id = get_drive_root_folder_id(db)
        cards = (
            db.query(PhysicalCard)
            .options(selectinload(PhysicalCard.aliases))
            .order_by(PhysicalCard.display_name)
            .all()
        )

    accounts_differ = (
        gmail_conn is not None
        and drive_conn is not None
        and gmail_conn.google_account_email != drive_conn.google_account_email
    )

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "gmail_conn": gmail_conn,
            "drive_conn": drive_conn,
            "accounts_differ": accounts_differ,
            "allowed_senders": allowed_senders,
            "drive_root_folder": drive_root_folder,
            "drive_root_folder_id": drive_root_folder_id,
            "google_api_key": get_settings().GOOGLE_API_KEY,
            "google_client_id": get_settings().GOOGLE_OAUTH_CLIENT_ID,
            "cards": cards,
        },
    )
