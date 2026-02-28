import re
from typing import Optional
from sqlalchemy.orm import Session
from app.models.card import PhysicalCard, CardAlias


def resolve_card(
    db: Session, card_last4: Optional[str], user_id: Optional[int] = None
) -> tuple[Optional[PhysicalCard], str]:
    """
    Returns (physical_card, resolution_type)
    resolution_type: "exact" | "pattern" | "unresolved"

    When user_id is provided, only cards belonging to that user are considered.
    """
    if not card_last4:
        return None, "unresolved"

    # Build alias and card queries, scoped to user when provided
    alias_q = db.query(CardAlias)
    card_q = db.query(PhysicalCard)
    if user_id is not None:
        alias_q = alias_q.join(
            PhysicalCard, CardAlias.physical_card_id == PhysicalCard.id
        ).filter(PhysicalCard.user_id == user_id)
        card_q = card_q.filter(PhysicalCard.user_id == user_id)

    # 1. Exact alias match
    alias = alias_q.filter(CardAlias.alias_last4 == card_last4).first()
    if alias:
        if user_id is not None:
            card = card_q.filter(PhysicalCard.id == alias.physical_card_id).first()
        else:
            card = db.query(PhysicalCard).get(alias.physical_card_id)
        return card, "exact"

    # 2. Check physical cards directly
    card = card_q.filter(PhysicalCard.last4 == card_last4).first()
    if card:
        return card, "exact"

    # 3. Pattern match aliases
    aliases = alias_q.filter(CardAlias.alias_pattern.isnot(None)).all()
    for a in aliases:
        if a.alias_pattern and re.search(a.alias_pattern, card_last4):
            if user_id is not None:
                card = card_q.filter(PhysicalCard.id == a.physical_card_id).first()
            else:
                card = db.query(PhysicalCard).get(a.physical_card_id)
            return card, "pattern"

    return None, "unresolved"
