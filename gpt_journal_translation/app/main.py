from fastapi import FastAPI
from app.handlers import sales, purchase, depreciation, asset_purchase, supplies_purchase

app = FastAPI()

# ルーター登録
app.include_router(sales.router, prefix="/journal")
app.include_router(purchase.router, prefix="/journal")
app.include_router(depreciation.router, prefix="/journal")
app.include_router(asset_purchase.router, prefix="/journal")
app.include_router(supplies_purchase.router, prefix="/journal")