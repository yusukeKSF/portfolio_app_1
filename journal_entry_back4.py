# --- 減価償却費計算のロジックを追加 ---

import os
import re
import cv2
import io
import time
import json
import requests
from dotenv import load_dotenv
from google.cloud import vision
from openai import OpenAI
from datetime import datetime, timedelta
# Selenium を使用するための追加ライブラリ
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC

# .envから環境変数を読み込む
load_dotenv()

creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
openai_api_key = os.getenv("OPENAI_API_KEY_PROJECT_VISION")
openai_project_id = os.getenv("OPENAI_PROJECT_ID")
fastapi_base_url = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

if not creds_path or not os.path.exists(creds_path):
    print("❌ GOOGLE_APPLICATION_CREDENTIALS が設定されていないか、ファイルが存在しません。")
    exit()

if not openai_api_key or not openai_project_id:
    print("❌ OPENAI_API_KEY または OPENAI_PROJECT_ID が .env に設定されていません。")
    exit()

print(f"✅ 認証ファイルを確認済: {creds_path}")

# OCR関数（画像フレームを受け取り、テキスト抽出）
def extract_text_from_frame(frame):
    _, buffer = cv2.imencode('.png', frame)
    content = buffer.tobytes()
    image = vision.Image(content=content)
    client = vision.ImageAnnotatorClient()
    response = client.text_detection(image=image)
    texts = response.text_annotations
    return texts[0].description.strip() if texts else "[OCR結果なし]"
  
  # 数式を安全に評価する関数
def safe_eval_math_expression(expr):
    try:
        if re.fullmatch(r"[0-9\.\*\+\-\/\(\) ]+", expr):
            return eval(expr)
    except:
        pass
    return None
  
#   # OCR文から事業年度と初年度決算日を推定する関数（1月〜12月期にも対応）
# def extract_fiscal_dates_from_text(text):
#     pattern = r"(\d{4})年\s*(\d{1,2})月(\d{1,2})日\s*から\s*(\d{4})年\s*(\d{1,2})月(\d{1,2})日"
#     match = re.search(pattern, text)
#     if match:
#         start_year, start_month, start_day = int(match.group(1)), int(match.group(2)), int(match.group(3))
#         end_year, end_month, end_day = int(match.group(4)), int(match.group(5)), int(match.group(6))

#         # 初年度決算日（calc_closing_date）は取得日ベースで次年の決算日を仮定
#         if start_month == 1 and start_day == 1 and end_month == 12 and end_day == 31:
#             calc_closing_date = f"{start_year}-12-31"
#         else:
#             calc_closing_date = f"{start_year + 1}-03-31"

#         target_year = f"{end_year}-{end_month:02d}-{end_day:02d}"
#         return calc_closing_date, target_year
#     return None, None
  

# # GPTの出力に fiscal dates を補完する関数
# def merge_fiscal_dates_into_gpt(gpt_data: dict, ocr_text: str):
#     calc_closing_date, target_year = extract_fiscal_dates_from_text(ocr_text)
#     if gpt_data.get("type") == "depreciation":
#         if calc_closing_date:
#             gpt_data["closing_date"] = calc_closing_date
#             gpt_data["calc_closing_date"] = calc_closing_date
#         if target_year:
#             gpt_data["target_year"] = target_year
#     return gpt_data
  

# GPTプロンプト生成関数
def build_prompt(ocr_text: str) -> str:
    return f"""
あなたは簿記と財務会計に詳しい会計仕訳AIです。

出力はJSON形式でのみ返答してください。説明や解説は不要です。
次のOCR出力された日本語文を読み取り、以下の取引タイプを判定してください：
- "purchase"：通常の仕入取引
- "sales"：売上取引
- "depreciation"：期末の減価償却処理
- "supplies_purchase"：消耗品の購入（即時費用処理）
- "asset_purchase"：備品などの固定資産の購入（減価償却対象）
- 該当するものがなければ "type": "unknown"

【特別な指示】
以下のフィールドも必ず含めてください（特に減価償却取引の場合）：
- "calc_closing_date"：減価償却計算に用いる初年度の決算日（例：2025-03-31）
- "target_year"：事業年度末であり、減価償却費の表から抽出する対象（例：2028-03-31）
- "current_volume"：当期の実際活動量（※生産高比例法で使用）
- "total_volume"：予定の総活動量（※生産高比例法で使用）


仕入れ取引と備品の購入や消耗品の購入に関して、支払い方法の記述がない場合は、全額を現金で支払ったものとして処理してください。
また、減価償却において償却方法が「定率法」と記載されている場合は、必ず「200%定率法」として処理してください。
また、減価償却において償却方法が「定額法」と記載されている場合は、必ず「定額法」として処理してください。
また、減価償却において償却方法が「級数法」と記載されている場合は、必ず「級数法」として処理してください。
また、減価償却において償却方法が「生産高比例法」と記載されている場合は、必ず「生産高比例法」として処理してください。
数式は事前に評価し、"amount": 数値 として出力してください（例："amount": 120000）。

出力形式：
{{
  "type": "purchase"｜"sales"｜"depreciation"｜"supplies_purchase"｜"asset_purchase"｜"unknown",
  "date": "YYYY-MM-DD",
  "summary": "取引内容の説明",
  "supplier": "仕入先名（仕入時）",
  "customer": "顧客名（売上時）",
  "asset_name": "資産名（備品や減価償却対象の場合）",
  "acquisition_date": "YYYY-MM-DD",
  "closing_date": "YYYY-MM-DD",
  "method": "償却方法",
  "amount": "取得金額",
  "life": "耐用年数",
  "entries": [
    {{ "debit": "勘定科目", "credit": "勘定科目", "amount": 金額 }}
  ]
}}

OCR結果：
「{ocr_text}」
"""

# === GPTの出力（JSON）をFastAPIの /journal/{type} エンドポイント(FastAPI)に送信する関数 ===
# GPT呼び出し関数（OpenAI v1.10以降対応、project ID 指定）
def ask_gpt(prompt: str) -> str:
    client = OpenAI(api_key=openai_api_key, project=openai_project_id)
    chat_completion = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "あなたは簿記と財務会計に詳しい会計仕訳AIです。"},
            {"role": "user", "content": prompt}
        ]
    )
    return chat_completion.choices[0].message.content


# === 減価償却費をWebページ経由で自動計算するための関数  Selenium実装 === 
def calculate_depreciation_by_year(starting_date, closing_date, method, price, life, current_volume, total_volume, target_year=None):
    options = Options()
    # options.add_argument('--headless')  # 開発時はGUI確認も可能
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=options)
    driver.get("https://stylefunc287.xsrv.jp/php/dep.php")

    # ✅ 修正後（安定入力）
    starting_input = driver.find_element(By.ID, "startingDate")
    closing_input = driver.find_element(By.ID, "closingDate")
    driver.execute_script("arguments[0].value = arguments[1]", starting_input, starting_date) # JavaScript を使って値を直接設定する。　フォーマット依存を避ける。　今回アクセスするwebページの日付入力欄のフォーマットは自動入力だと誤入力を起こしてしまう。
    driver.execute_script("arguments[0].value = arguments[1]", closing_input, closing_date) # JavaScript を使って値を直接設定する
    Select(driver.find_element(By.ID, "cluculateMethod")).select_by_visible_text(method)
    driver.find_element(By.ID, "purchasePrice").send_keys(str(price))
    driver.find_element(By.ID, "usefulLife").send_keys(str(life))
    
    if method == "生産高比例法":
        driver.find_element(By.ID, "currentVolume").send_keys(str(current_volume))
        driver.find_element(By.ID, "totalVolume").send_keys(str(total_volume))
        
    driver.find_element(By.ID, "submit").click()
    time.sleep(2)

    # # ✅ ページ更新を待機（テーブルが読み込まれるのを確認 = URLが再掲示されるのを待つ）　必要であれば追加
    # try:
    #     WebDriverWait(driver, 3).until(
    #         EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.record tr"))
    #     )
    # except Exception as e:
    #     print("❌ テーブル読み込み失敗:", e)
    #     driver.quit()
    #     return None

    # ✅ 減価償却費を取得
    depreciation_value = None
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.record tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 3:
                year_text = cols[0].text.strip()
                value = cols[2].text.strip().replace(",", "")
                if (not target_year) or (target_year in year_text): # target_year の引数とこの1行を追加。　指定した事業年度の減価償却費を抽出することができるようになる。
                    depreciation_value = float(value)
                    print(f"✅ 対象年度 {year_text} の減価償却費: {depreciation_value}")
                    break
    except Exception as e:
        print("❌ 減価償却費取得失敗:", e)

    # # Selenium 用のデバッグ
    # if depreciation_value:
    #     print(f"🧮 Seleniumで取得した減価償却費: {depreciation_value}")
    # else:
    #     print("❌ 減価償却費が取得できませんでした。")
    # print("📄 ページURL（再読込後）:", driver.current_url)
    
    driver.quit()
    return depreciation_value



# === FastAPI に送信する関数 ===
def send_to_fastapi(type_: str, json_data: dict):
    endpoint = f"{fastapi_base_url}/journal/{type_}"
    try:
        response = requests.post(endpoint, json=json_data)
        response.raise_for_status()
        print(f"✅ FastAPIへ送信成功: {endpoint}")
        print("📨 レスポンス:", response.json())
    except requests.exceptions.RequestException as e:
        print(f"❌ FastAPI送信失敗: {e}")
        
# ---------------------------------------------------------
#                      関数定義ここまで
# ---------------------------------------------------------

#--------------------- メインループ開始 --------------------------

print("📷 カメラを起動中... (ESCキーで終了)")
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ カメラからフレームを取得できませんでした。")
        break

    height, width, _ = frame.shape
    # 中央90%の範囲を計算
    box_width = int(width * 0.9)
    box_height = int(height * 0.9)
    start_x = (width - box_width) // 2
    start_y = (height - box_height) // 2
    end_x = start_x + box_width
    end_y = start_y + box_height

    # 白枠の描画
    cv2.rectangle(frame, (start_x, start_y), (end_x, end_y), (255, 255, 255), 2)
    # フレームを表示
    cv2.imshow("Camera", frame)

    # キー操作を取得
    key = cv2.waitKey(1)

    # 's'キーでOCR→GPT処理
    if key == ord('s'):
        print("🔍 OCR 処理中...")
        cropped_frame = frame[start_y:end_y, start_x:end_x]
        ocr_text = extract_text_from_frame(cropped_frame)

        print("====================================")
        print("📄 OCR出力:")
        print(ocr_text)
        print("====================================")
        
        # 事業年度の推定と初年度減価償却費計算に係る決算日の推定

        if ocr_text and ocr_text != "[OCR結果なし]":
            prompt = build_prompt(ocr_text)
            gpt_result = ask_gpt(prompt)
            print("🧠 GPTによる取引分類:")
            print(gpt_result)
            
            try:
                # 数式部分の amount を処理する前置き
                gpt_result = re.sub(
                    r'("amount"\s*:\s*)([0-9\*\/\.\+\-\(\) ]+)',
                    lambda m: f'{m.group(1)}{safe_eval_math_expression(m.group(2))}',
                    gpt_result
                )

                # gpt_data = json.loads(gpt_result)
                result_json = json.loads(gpt_result)
                type_ = result_json.get("type", "unknown")
                # result_json = merge_fiscal_dates_into_gpt(gpt_data, ocr_text)
# ----------------------------------------------------------------------
                # 減価償却の場合に金額を自動取得
                if type_ == "depreciation":
                    dep = calculate_depreciation_by_year(
                        starting_date=result_json.get("acquisition_date"),
                        closing_date=result_json.get("calc_closing_date"),
                        method=result_json.get("method"),
                        price=result_json.get("amount"),
                        life=result_json.get("life"),
                        # target_year=result_json.get("closing_date")
                    )
                    if dep:
                        result_json["entries"][0]["amount"] = dep
                        
                        # seleniumデバッグ用出力
                        print(f"✅ 減価償却費を上書き: {result_json['entries'][0]['amount']}")


# ----------------------------------------------------------------------
                if type_ != "unknown":
                    send_to_fastapi(type_, result_json)
                else:
                    print("⚠️ GPTの分類結果が 'unknown' でした。FastAPIへは送信しません。")
            except json.JSONDecodeError:
                print("❌ GPTの出力がJSON形式ではありません。送信を中止します。")
        else:
            print("⚠️ OCR結果がありませんでした。")

    # ESCキーで終了
    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()
