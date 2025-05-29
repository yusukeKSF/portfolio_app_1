from fastapi import APIRouter
from app.schemas import DepreciationRequest

router = APIRouter()

@router.post("/depreciation")
def handle_depreciation(data: DepreciationRequest):
    print("\n✅ 減価償却リクエスト受信")
    print("📅 日付:", data.date)
    print("📝 概要:", data.summary)
    print("🧮 償却方法:", data.method)
    print("📦 取得額:", data.amount)
    print("📆 取得日:", data.acquisition_date)
    print("📆 決算日:", data.closing_date)
    if data.calc_closing_date:
        print("📆 初年度決算日:", data.calc_closing_date)
    print("🧾 耐用年数:", data.life)
    if data.target_year:
        print("🔍 対象年度:", data.target_year)

    for entry in data.entries:
        print(f"  借方: {entry.debit}, 貸方: {entry.credit}, 金額: {entry.amount}")
    total = sum(e.amount for e in data.entries)
    print(f"💰 合計減価償却費（エントリ合計）: {total}")
    return {"status": "success", "message": "depreciation 取引を正常に受信しました。"}