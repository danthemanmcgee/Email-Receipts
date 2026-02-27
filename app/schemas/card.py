from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class CardAliasBase(BaseModel):
    alias_last4: str
    alias_pattern: Optional[str] = None
    notes: Optional[str] = None


class CardAliasCreate(CardAliasBase):
    pass


class CardAliasResponse(CardAliasBase):
    id: int
    physical_card_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PhysicalCardBase(BaseModel):
    display_name: str
    last4: Optional[str] = None
    network: Optional[str] = None


class PhysicalCardCreate(PhysicalCardBase):
    pass


class PhysicalCardUpdate(BaseModel):
    display_name: Optional[str] = None
    last4: Optional[str] = None
    network: Optional[str] = None


class PhysicalCardResponse(PhysicalCardBase):
    id: int
    created_at: datetime
    aliases: List[CardAliasResponse] = []

    model_config = {"from_attributes": True}
