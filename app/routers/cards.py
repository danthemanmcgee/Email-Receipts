from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.card import PhysicalCard, CardAlias
from app.models.user import User
from app.schemas.card import PhysicalCardCreate, PhysicalCardUpdate, PhysicalCardResponse, CardAliasCreate, CardAliasResponse
from app.services.auth_service import get_current_user
from typing import List

router = APIRouter()


@router.get("", response_model=List[PhysicalCardResponse])
def list_cards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(PhysicalCard).filter(PhysicalCard.user_id == current_user.id).all()


@router.post("", response_model=PhysicalCardResponse, status_code=201)
def create_card(
    card: PhysicalCardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(PhysicalCard).filter(
        PhysicalCard.display_name == card.display_name,
        PhysicalCard.user_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Card with that display name already exists")
    db_card = PhysicalCard(**card.model_dump(), user_id=current_user.id)
    db.add(db_card)
    db.commit()
    db.refresh(db_card)
    return db_card


@router.put("/{card_id}", response_model=PhysicalCardResponse)
def update_card(
    card_id: int,
    card: PhysicalCardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_card = db.query(PhysicalCard).filter(
        PhysicalCard.id == card_id, PhysicalCard.user_id == current_user.id
    ).first()
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    update_data = card.model_dump(exclude_unset=True)
    if "display_name" in update_data and update_data["display_name"] != db_card.display_name:
        conflict = db.query(PhysicalCard).filter(
            PhysicalCard.display_name == update_data["display_name"],
            PhysicalCard.user_id == current_user.id,
            PhysicalCard.id != card_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Card with that display name already exists")
    for key, value in update_data.items():
        setattr(db_card, key, value)
    db.commit()
    db.refresh(db_card)
    return db_card


@router.delete("/{card_id}", status_code=204)
def delete_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_card = db.query(PhysicalCard).filter(
        PhysicalCard.id == card_id, PhysicalCard.user_id == current_user.id
    ).first()
    if not db_card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(db_card)
    db.commit()


@router.post("/{card_id}/aliases", response_model=CardAliasResponse, status_code=201)
def add_alias(
    card_id: int,
    alias: CardAliasCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    card = db.query(PhysicalCard).filter(
        PhysicalCard.id == card_id, PhysicalCard.user_id == current_user.id
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db_alias = CardAlias(physical_card_id=card_id, **alias.model_dump())
    db.add(db_alias)
    db.commit()
    db.refresh(db_alias)
    return db_alias


@router.delete("/{card_id}/aliases/{alias_id}", status_code=204)
def delete_alias(
    card_id: int,
    alias_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_alias = db.query(CardAlias).filter(
        CardAlias.id == alias_id, CardAlias.physical_card_id == card_id
    ).first()
    if not db_alias:
        raise HTTPException(status_code=404, detail="Alias not found")
    # Verify the card belongs to the current user
    card = db.query(PhysicalCard).filter(
        PhysicalCard.id == card_id, PhysicalCard.user_id == current_user.id
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    db.delete(db_alias)
    db.commit()
