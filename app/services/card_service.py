import re
from typing import Optional
from sqlalchemy.orm import Session
from app.models.card import PhysicalCard, CardAlias


def resolve_card(
    db: Session, card_last4: Optional[str]
) -> tuple[Optional[PhysicalCard], str]:
    """
    Returns (physical_card, resolution_type)
    resolution_type: "exact" | "pattern" | "unresolved"
    """
    if not card_last4:
        return None, "unresolved"

    # 1. Exact alias match
    alias = db.query(CardAlias).filter(CardAlias.alias_last4 == card_last4).first()
    if alias:
        card = db.query(PhysicalCard).get(alias.physical_card_id)
        return card, "exact"

    # 2. Check physical cards directly
    card = db.query(PhysicalCard).filter(PhysicalCard.last4 == card_last4).first()
    if card:
        return card, "exact"

    # 3. Pattern match aliases
    aliases = db.query(CardAlias).filter(CardAlias.alias_pattern.isnot(None)).all()
    for a in aliases:
        if a.alias_pattern and re.search(a.alias_pattern, card_last4):
            card = db.query(PhysicalCard).get(a.physical_card_id)
            return card, "pattern"

    return None, "unresolved"
