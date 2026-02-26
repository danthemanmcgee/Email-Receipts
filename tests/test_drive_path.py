import pytest
from datetime import date
from app.services.drive_service import build_drive_path, sanitize_path_component
from app.models.card import PhysicalCard


def make_card(display_name="Chase Sapphire"):
    card = PhysicalCard.__new__(PhysicalCard)
    card.id = 1
    card.display_name = display_name
    card.last4 = "1234"
    card.network = "Visa"
    return card


def test_drive_path_with_card():
    card = make_card("Chase Sapphire")
    folder, filename = build_drive_path(
        card=card,
        purchase_date=date(2024, 3, 15),
        merchant="Amazon",
        amount=29.99,
        currency="USD",
        gmail_message_id="abc123",
    )
    assert folder == "Receipts/Chase_Sapphire/2024/2024-03"
    assert filename == "2024-03-15_Amazon_29.99_USD_abc123.pdf"


def test_drive_path_without_card():
    folder, filename = build_drive_path(
        card=None,
        purchase_date=date(2024, 3, 15),
        merchant="Amazon",
        amount=29.99,
        currency="USD",
        gmail_message_id="abc123",
    )
    assert folder.startswith("Receipts/Unmapped_Card/")


def test_drive_path_custom_root():
    card = make_card("Amex Gold")
    folder, _ = build_drive_path(
        card=card,
        purchase_date=date(2024, 1, 1),
        merchant="Target",
        amount=50.00,
        currency="USD",
        gmail_message_id="xyz",
        root_folder="MyReceipts",
    )
    assert folder.startswith("MyReceipts/")


def test_sanitize_path_component():
    assert sanitize_path_component("Chase Sapphire") == "Chase_Sapphire"
    assert sanitize_path_component("Card/Name") == "Card_Name"
    assert "/" not in sanitize_path_component("a/b/c")


def test_filename_format():
    card = make_card("Visa")
    _, filename = build_drive_path(
        card=card,
        purchase_date=date(2024, 6, 1),
        merchant="Starbucks",
        amount=5.50,
        currency="USD",
        gmail_message_id="msg999",
    )
    parts = filename.replace(".pdf", "").split("_")
    assert parts[0] == "2024-06-01"
    assert "Starbucks" in filename
    assert "5.50" in filename
    assert "USD" in filename
    assert "msg999" in filename
