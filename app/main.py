from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.routers import gmail, receipts, cards, jobs, health
from app.database import engine
from app.models import receipt as receipt_models  # noqa: F401 - ensures models are registered
from app.models import card as card_models  # noqa: F401

app = FastAPI(title="Email Receipts", version="1.0.0")

# Include API routers
app.include_router(gmail.router, prefix="/gmail", tags=["gmail"])
app.include_router(receipts.router, prefix="/receipts", tags=["receipts"])
app.include_router(cards.router, prefix="/cards", tags=["cards"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(health.router, tags=["health"])

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
        items = q.order_by(Receipt.created_at.desc()).offset(skip).limit(limit).all()

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
        receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
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
            .filter(Receipt.status == ReceiptStatus.needs_review)
            .order_by(Receipt.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        "review.html", {"request": request, "receipts": items}
    )
