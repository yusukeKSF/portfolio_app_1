from fastapi import APIRouter
from app.schemas import SuppliesPurchaseRequest
                                        # ↑
router = APIRouter()                    # ここの名前を同じにする。
                        # ↓ ルートURL     #
@router.post("/supplies_purchase")      # ↓
def handle_supplies(data: SuppliesPurchaseRequest):
    print("\n✅ 消耗品購入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("📦 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "supplies_purchase 取引を正常に受信しました。"}