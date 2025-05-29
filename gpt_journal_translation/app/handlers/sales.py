from fastapi import APIRouter
from app.schemas import SalesRequest

router = APIRouter()

@router.post("/sales")    # @app.post → @router.post  元々あった /journal も削除
def handle_sales(data: SalesRequest):
    print("\n✅ 売上取引リクエスト受信")
    print("📅 日付:", data.date)
    print("🧾 顧客名:", data.customer)
    print("📝 概要:", data.summary)
    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    return {"status": "success", "message": "sales 取引を正常に受信しました。"}