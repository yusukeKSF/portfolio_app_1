from fastapi import APIRouter
from app.schemas import PurchaseRequest

router = APIRouter()

@router.post("/purchase")
def handle_purchase(data: PurchaseRequest):
    print("\n✅ 仕入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🏢 仕入先:", data.supplier)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "purchase 取引を正常に受信しました。"}