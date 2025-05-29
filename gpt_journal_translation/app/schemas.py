from pydantic import BaseModel
from typing import List, Optional, Literal

class Entry(BaseModel):
    debit: str
    credit: str
    amount: float

class SalesRequest(BaseModel):
    type: Literal["sales"]
    date: str
    summary: str
    customer: str
    amount: float
    entries: List[Entry]

class PurchaseRequest(BaseModel):
    type: Literal["purchase"]
    date: str
    summary: str
    supplier: str
    amount: float
    entries: List[Entry]

class SuppliesPurchaseRequest(BaseModel):
    type: Literal["supplies_purchase"]
    date: str
    summary: str
    supplier: Optional[str]
    amount: float
    entries: List[Entry]

class AssetPurchaseRequest(BaseModel):
    type: Literal["asset_purchase"]
    date: str
    summary: str
    asset_name: str
    amount: float
    entries: List[Entry]

class DepreciationRequest(BaseModel):
    type: Literal["depreciation"]
    date: str
    summary: str
    asset_name: str
    acquisition_date: str
    closing_date: str
    calc_closing_date: Optional[str] = None
    method: str
    amount: float
    life: int
    target_year: Optional[str] = None
    current_volume: Optional[float] = None
    total_volume: Optional[float] = None
    entries: List[Entry]