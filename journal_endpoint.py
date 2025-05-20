from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

app = FastAPI()

# 共通仕訳エントリ
class Entry(BaseModel):
    debit: str
    credit: str
    amount: float

# 各種スキーマ
class DepreciationRequest(BaseModel):
    type: Literal["depreciation"]
    date: str  # 形式: YYYY-MM-DD
    summary: str
    asset_name: str
    acquisition_date: str  # 形式: YYYY-MM-DD
    closing_date: str  # 形式: YYYY-MM-DD
    method: str
    amount: float
    life: int
    target_year: Optional[str] = None  # 追加: 指定された年の減価償却費取得用
    entries: List[Entry]

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


@app.post("/journal/sales")
def handle_sales(data: SalesRequest):
    print("\n✅ 売上取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🧾 顧客名:", data.customer)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "sales 取引を正常に受信しました。"}

@app.post("/journal/purchase")
def handle_purchase(data: PurchaseRequest):
    print("\n✅ 仕入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🏢 仕入先:", data.supplier)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "purchase 取引を正常に受信しました。"}

@app.post("/journal/supplies_purchase")
def handle_supplies(data: SuppliesPurchaseRequest):
    print("\n✅ 消耗品購入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("📦 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "supplies_purchase 取引を正常に受信しました。"}

@app.post("/journal/asset_purchase")
def handle_asset(data: AssetPurchaseRequest):
    print("\n✅ 固定資産購入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🖋 資産名:", data.asset_name)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "asset_purchase 取引を正常に受信しました。"}

@app.post("/journal/depreciation")
def handle_depreciation(data: DepreciationRequest):
    print("\n✅ 減価償却リクエスト受信")
    print("📅 日付:", data.date)
    print("📝 概要:", data.summary)
    print("🧮 償却方法:", data.method)
    print("📦 取得額:", data.amount)
    print("📆 取得日:", data.acquisition_date)
    print("📆 決算日:", data.closing_date)
    print("🧾 耐用年数:", data.life)
    if data.target_year:
        print("🔍 対象年度:", data.target_year)

    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    total = sum(e.amount for e in data.entries)
    print(f"💰 合計減価償却費（エントリ合計）: {total}")
    return {"status": "success", "message": "depreciation 取引を正常に受信しました。"}
