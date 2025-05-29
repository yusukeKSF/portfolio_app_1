from fastapi import APIRouter
from app.schemas import AssetPurchaseRequest

router = APIRouter()

@router.post("/asset_purchase")
def handle_asset(data: AssetPurchaseRequest):
    print("\n✅ 固定資産購入取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🖋 資産名:", data.asset_name)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "asset_purchase 取引を正常に受信しました。"}