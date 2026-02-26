import re
from datetime import date
from typing import Optional
from app.models.card import PhysicalCard


def build_drive_path(
    card: Optional[PhysicalCard],
    purchase_date: Optional[date],
    merchant: Optional[str],
    amount: Optional[float],
    currency: Optional[str],
    gmail_message_id: str,
    root_folder: str = "Receipts",
) -> tuple[str, str]:
    """Returns (folder_path, filename)"""
    if card:
        card_folder = sanitize_path_component(card.display_name)
    else:
        card_folder = "Unmapped_Card"

    if purchase_date:
        year = purchase_date.strftime("%Y")
        month = purchase_date.strftime("%Y-%m")
    else:
        from datetime import date as date_cls

        today = date_cls.today()
        year = today.strftime("%Y")
        month = today.strftime("%Y-%m")

    folder_path = f"{root_folder}/{card_folder}/{year}/{month}"

    date_str = purchase_date.strftime("%Y-%m-%d") if purchase_date else "0000-00-00"
    merchant_str = sanitize_path_component(merchant or "Unknown")
    amount_str = f"{amount:.2f}" if amount is not None else "0.00"
    currency_str = (currency or "USD").upper()

    filename = f"{date_str}_{merchant_str}_{amount_str}_{currency_str}_{gmail_message_id}.pdf"

    return folder_path, filename


def sanitize_path_component(s: str) -> str:
    """Remove/replace characters not safe for file/folder names."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:100]
