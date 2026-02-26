import pytest
from unittest.mock import MagicMock
from app.services.card_service import resolve_card
from app.models.card import PhysicalCard, CardAlias


def make_db_with_card_and_alias(last4="1234", alias_last4="5678"):
    """Create a mock DB session with a physical card and alias."""
    db = MagicMock()
    card = PhysicalCard.__new__(PhysicalCard)
    card.id = 1
    card.display_name = "Chase Sapphire"
    card.last4 = last4

    alias = CardAlias.__new__(CardAlias)
    alias.id = 1
    alias.physical_card_id = 1
    alias.alias_last4 = alias_last4
    alias.alias_pattern = None

    def query_side_effect(model):
        mock_q = MagicMock()
        if model == CardAlias:
            mock_q.filter.return_value.first.return_value = alias
            mock_q.filter.return_value.all.return_value = [alias]
        elif model == PhysicalCard:
            mock_q.filter.return_value.first.return_value = None
            mock_q.get.return_value = card
        return mock_q

    db.query.side_effect = query_side_effect
    return db, card, alias


def test_resolve_exact_alias():
    db, card, alias = make_db_with_card_and_alias(alias_last4="5678")
    resolved_card, resolution_type = resolve_card(db, "5678")
    assert resolved_card is not None
    assert resolved_card.display_name == "Chase Sapphire"
    assert resolution_type == "exact"


def test_resolve_no_card_last4():
    db = MagicMock()
    resolved_card, resolution_type = resolve_card(db, None)
    assert resolved_card is None
    assert resolution_type == "unresolved"


def test_resolve_unresolved():
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value.first.return_value = None
    mock_q.filter.return_value.all.return_value = []
    db.query.return_value = mock_q

    resolved_card, resolution_type = resolve_card(db, "9999")
    assert resolved_card is None
    assert resolution_type == "unresolved"
