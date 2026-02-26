from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.card import PhysicalCard, CardAlias
from app.schemas.card import PhysicalCardCreate, PhysicalCardResponse, CardAliasCreate, CardAliasResponse
from typing import List

router = APIRouter()


@router.get("", response_model=List[PhysicalCardResponse])
def list_cards(db: Session = Depends(get_db)):
    return db.query(PhysicalCard).all()


@router.post("", response_model=PhysicalCardResponse, status_code=201)
def create_card(card: PhysicalCardCreate, db: Session = Depends(get_db)):
    existing = db.query(PhysicalCard).filter(PhysicalCard.display_name == card.display_name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Card with that display name already exists")
    db_card = PhysicalCard(**card.model_dump())
    db.add(db_card)
    db.commit()
    db.refresh(db_card)
    return db_card


@router.post("/{card_id}/aliases", response_model=CardAliasResponse, status_code=201)
def add_alias(card_id: int, alias: CardAliasCreate, db: Session = Depends(get_db)):
    card = db.query(PhysicalCard).filter(PhysicalCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db_alias = CardAlias(physical_card_id=card_id, **alias.model_dump())
    db.add(db_alias)
    db.commit()
    db.refresh(db_alias)
    return db_alias
