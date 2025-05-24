# --- カメラに映った範囲からOCR処理 から スプレッドシートへの入力までのベース ---

import os
import cv2
import io
import time
import json
import re
import requests
import gspread
from dotenv import load_dotenv
from google.cloud import vision
from openai import OpenAI
# Selenium を使用するための追加ライブラリ
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from collections import defaultdict # スプレッドシート入力時の重複した科目について合算して表示
# from googleapiclient.errors import HttpError 　 デバッグ用


# .envから環境変数を読み込む
load_dotenv()

creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
openai_api_key = os.getenv("OPENAI_API_KEY_PROJECT_VISION")
openai_project_id = os.getenv("OPENAI_PROJECT_ID")
fastapi_base_url = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

# スプレッドシートへのアドレス設定
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
FOLDER_ID = os.getenv("FOLDER_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # スプレッドシートID（URLの中の文字列）
SPREADSHEET_TITLE = "Journal"    # 任意のスプレッドシート名（タイトル）
SHEET_NAME = os.getenv("SHEET_NAME", "シート1")  # 任意のシート名、なければ"Sheet1"
# 認証スコープ
SCOPES= ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]



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
# プロンプトで対応したため現在は使用しない。
# def safe_eval_math_expression(expr):
#     try:
#         if re.fullmatch(r"[0-9\.\*\+\-/\(\) ]+", expr):
#             return eval(expr)
#     except:
#         pass
#     return None


# 会計期間パターン（MM-DD）の抽出（start/endのみ）
def extract_fiscal_mmdd_period(text):
    pattern = r"(\d{1,2})月(\d{1,2})日から(\d{1,2})月(\d{1,2})日"
    match = re.search(pattern, text)
    if match:
        start = f"{int(match.group(1)):02d}-{int(match.group(2)):02d}"
        end = f"{int(match.group(3)):02d}-{int(match.group(4)):02d}"
        return start, end
    return None, None

# 初年度の決算日を導出
def derive_calc_closing_date(acquisition_date: str, fiscal_end_mmdd: str) -> str:
    try:
        acq_date = datetime.strptime(acquisition_date, "%Y-%m-%d")
        fiscal_month, fiscal_day = map(int, fiscal_end_mmdd.split("-"))
        closing_year = acq_date.year

        # 資産取得月が決算月より後 → 翌年度の決算日
        if acq_date.month > fiscal_month or (acq_date.month == fiscal_month and acq_date.day > fiscal_day):
            closing_year += 1

        return f"{closing_year}-{fiscal_month:02d}-{fiscal_day:02d}"
    except Exception as e:
        print(f"❌ calc_closing_date推定失敗: {e}")
        return None

# 減価償却費を自動取得する関数（復元）
def calculate_depreciation_by_year(starting_date, calc_closing_date, method, price, life, target_year, current_volume=None, total_volume=None):
    try:
        options = Options()
        # options.add_argument("--headless") #コメントアウトすることで開発段階にGUI確認を可能にすることができる 
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(options=options)
        driver.get("https://stylefunc287.xsrv.jp/php/dep.php")

        starting_input = driver.find_element(By.ID, "startingDate")
        closing_input = driver.find_element(By.ID, "closingDate")
        driver.execute_script("arguments[0].value = arguments[1]", starting_input, starting_date) # JavaScript を使って値を直接設定する。　フォーマット依存を避ける。　今回アクセスするwebページの日付入力欄のフォーマットは自動入力だと誤入力を起こしてしまう。
        driver.execute_script("arguments[0].value = arguments[1]", closing_input, calc_closing_date)
        Select(driver.find_element(By.ID, "cluculateMethod")).select_by_visible_text(method)
        driver.find_element(By.ID, "purchasePrice").send_keys(str(price))
        driver.find_element(By.ID, "usefulLife").send_keys(str(life))

        if method == "生産高比例法":
            driver.find_element(By.ID, "currentVolume").send_keys(str(current_volume or ""))
            driver.find_element(By.ID, "totalVolume").send_keys(str(total_volume or ""))

        driver.find_element(By.ID, "submit").click()
        time.sleep(2)

        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.record tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 3 and cols[0].text.strip() == target_year:
                value = cols[2].text.replace(",", "")
                driver.quit()
                return float(value)

        driver.quit()
        return None
    except Exception as e:
        print(f"❌ 減価償却費取得エラー: {e}")
        return None

# GPT→FastAPIデータ変換に fiscal dates を補完
def merge_fiscal_dates_into_gpt(gpt_data: dict, ocr_text: str):
    _, fiscal_end = extract_fiscal_mmdd_period(ocr_text)
    if gpt_data.get("type") == "depreciation":
        acquisition_date = gpt_data.get("acquisition_date")
        if acquisition_date and fiscal_end:
            gpt_data["calc_closing_date"] = derive_calc_closing_date(acquisition_date, fiscal_end)

        # closing_date（当期末）と target_year（当期）を抽出
        fiscal_year_match = re.search(r"(\d{4})年.*?(\d{4})年(\d{1,2})月(\d{1,2})日", ocr_text)
        if fiscal_year_match:
            _, year, month, day = fiscal_year_match.groups()
            gpt_data["closing_date"] = f"{year}-{int(month):02d}-{int(day):02d}"
            gpt_data["target_year"] = gpt_data["closing_date"]


        # entries が存在し、amount が "未計算" であれば初期値代入
        if "entries" in gpt_data and isinstance(gpt_data["entries"], list):
            for entry in gpt_data["entries"]:
                if entry.get("amount") == "未計算":
                    entry["amount"] = 0.0

    return gpt_data

# === GPTプロンプト生成関数 ===
def build_prompt(ocr_text: str) -> str:
    return f"""
あなたは会計仕訳AIです。

出力はJSON形式でのみ返答してください。説明や解説は不要です。
次のOCR出力された日本語文を読み取り、以下の取引タイプを判定してください：
- "purchase"：通常の仕入取引
- "sales"：売上取引
- "depreciation"：期末の減価償却処理
- "supplies_purchase"：消耗品の購入（即時費用処理）
- "asset_purchase"：備品などの固定資産の購入（減価償却対象）
- 資産の購入（type: asset_purchase）に該当する場合、"asset_name" を必ず含めてください。
- 該当するものがなければ "type": "unknown"

【補足指示】
- 「〇〇を仕入れた」とある場合は type を "purchase" とし、 "debit" を "仕入" にしてください。
- 「〇〇を購入した」とある場合且つ type が "purchase" に該当しない時は、消耗品か流動資産か固定資産かを文脈から判断し、 type を "supplies_purchase" または "asset_purchase" にしてください。
- 「代金は翌月支払う」「未払いである」「掛け払いである」などの文言がある場合、 purchase 以外(supplies_purchase, asset_purchase)では credit に "未払金" を使用してください。
- 「代金は翌月支払う」「未払いである」「掛け払いである」などの文言がある場合で purchase に該当する取引の場合は、credit に "買掛金"を使用してください。

仕入、消耗品、備品やその他の購入に関して、支払い方法の記述がない場合は、全額を現金預金で支払ったものとして処理してください。
売上、資産の売却に関して、受け取り方法の記述がない場合は、全額を現金預金で受け取ったものとして処理してください。
減価償却の仕訳では、「減価償却費」が借方（debit）、「減価償却累計額」が貸方（credit）に基本的に入るようにしてください。


出力形式（以下のJSON形式で出力してください）：
{{
  "type": "purchase"｜"sales"｜"depreciation"｜"supplies_purchase"｜"asset_purchase"｜"unknown",
  "date": "YYYY-MM-DD",
  "summary": "取引内容の説明（例：○○を販売、購入など）",
  "supplier": "仕入先名（仕入時）",
  "customer": "顧客名（売上時）",
  "asset_name": "資産名（備品や減価償却対象の場合）",
  "acquisition_date": "取得日",
  "calc_closing_date": "決算日",
  "method": "償却方法",
  "amount": "取得金額",
  "life": "耐用年数",
  "target_year": "事業年度(至)",
  "entries": [
    {{ "debit": "勘定科目", "credit": "勘定科目", "amount": 0 }}
  ]
}}

対象の取引が減価償却に関するものである場合、以下のルールに従ってください:
- `type`: 必ず `"depreciation"` を指定してください。
- `date`: 回答の基準日を `"YYYY-MM-DD"` 形式で記入してください（例：問題文の期末日など）。
- `date` は仕訳を記録する基準日です。通常は `target_year` と同じで構いません。
- `summary`: 「〇〇の減価償却」といった内容を簡潔に記述してください。
- `asset_name`: 減価償却対象となる資産の名称（例：「機械」「車両運搬具」など）。
- `life` は耐用年数を年単位の整数で記入してください。たとえば「5年」であれば 5。
- `acquisition_date`: 資産の取得日を記入（例：2022-10-01）。
- `calc_closing_date`: 資産を取得した初年度の決算日を記入（例：2023-03-31）。これは減価償却費を正しく計算するために使用します。
- `target_year`: テーブルから抽出したい事業年度の決算日（例：2025-03-31）。これは何年度の減価償却費かを特定するために使用します。
- `closing_date`: FastAPI仕様により必須です。`calc_closing_date` と同じ値を設定してください。
- `method`: 減価償却方法（例：定額法、200%定率法、級数法など）。ただし「定率法」とあれば `"200%定率法"` に変換してください。
- `amount`: 資産の取得原価（数値）。
- `life`: 耐用年数（整数）。
- `entries`: 金額は `"amount": 0` などで仮設定してください。後でシステムが自動計算します。

注意事項：
- `calc_closing_date` は資産を取得した初年度の決算日でフォームに入力する決算日です（通常は取得日の年 + 会計年度末）。
- `target_year` はテーブルから減価償却費を取得したい年度の決算日です（例：2025-03-31）。
- `entries` の `amount` は後で計算されるので必ず `0` にしてください。
- 金額は半角数値で、カンマ区切りは使用しないでください。
- 出力は JSON のみで返してください（説明や注釈なし）。
- 入力文の中に資産を取得した日付が不明であるが、「前年」「昨年」などの表現がある場合は、`target_year` を基準として年を補完してください。

【特別な指示】
以下のフィールドも必ず含めてください（全取引共通および特に減価償却取引の場合）
- "summary": 取引内容を簡潔に要約した説明文（例：「○○を販売した」「備品を購入した」）
- "calc_closing_date"：減価償却計算に用いる初年度の決算日（例：2025-03-31）
- "target_year"：事業年度末であり、減価償却費の表から抽出する対象（例：2028-03-31）

また、減価償却において償却方法が「定率法」と記載されている場合は、必ず「200%定率法」として処理してください。
また、減価償却において償却方法が「定額法」と記載されている場合は、必ず「定額法」として処理してください。
また、減価償却において償却方法が「級数法」と記載されている場合は、必ず「級数法」として処理してください。
また、減価償却において償却方法が「生産高比例法」と記載されている場合は、必ず「生産高比例法」として処理してください。
数式は事前に評価し、"amount": 数値 として出力してください（例："amount": 120000）。


以下の形式で JSON を出力してください：
例:

{{
  "type": "depreciation",
  "date": "仕訳作成日 (YYYY-MM-DD)",
  "summary": "取引の要約（簡潔に）",
  "asset_name": "減価償却の対象資産の名称",
  "acquisition_date": "取得日 (YYYY-MM-DD)",
  "calc_closing_date": "減価償却初年度の決算日 (YYYY-MM-DD)",
  "method": "償却方法（例: 定額法、200%定率法、級数法 など）",
  "amount": 取得原価（数値）,
  "life": 耐用年数（整数）,
  "target_year": "今回取得したい減価償却費の対象年度末 (YYYY-MM-DD)",
  "entries": [
    {{
      "debit": "減価償却費",
      "credit": "減価償却累計額",
      "amount": 0
    }}
  ]
}}

OCR結果：
「{ocr_text}」
"""

# GPT API 呼び出し
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

# FastAPI送信関数
def send_to_fastapi(type_: str, data: dict):
    try:
        url = f"{fastapi_base_url}/journal/{type_}"
        response = requests.post(url, json=data)
        if response.status_code == 200:
            print(f"✅ FastAPIへ送信成功: {url}")
            print(f"📨 レスポンス: {response.json()}")
        else:
            print(f"❌ FastAPIエラー: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ FastAPI送信失敗: {e}")


# ==========通過したデータをスプレッドシートへ転記する ==========

def append_multi_entry_transaction(entry: dict):
    """
    ==============================
    📘 スプレッドシート表示ルール（仕訳出力方針）
    ==============================

    - 複数の借方・貸方がある場合も「上から詰めて」表示
    - 金額と勘定科目は同じ行に表示
    - 空白行は作らない
    - 日付と摘要（summary）は1行目にのみ表示
    - 出力された取引範囲には罫線（上下左右＆内部線）を付与

    entry の構造:
    {
        "date": "2025-05-22",
        "debit_entries": [{"account": "通信費", "amount": 3000}],
        "credit_entries": [{"account": "現金", "amount": 3000}],
        "summary": "通信費の支払い"
    }
    """

    try:
        # 認証スコープ
        SCOPES= ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        try:
            # 🔑 新しい Credentials を使った認証処理
            credentials = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
            client = gspread.authorize(credentials)
            
            # デバッグ用
            try:
                spreadsheet = client.open(SPREADSHEET_TITLE)  # ここは「ファイル名」
                print(f"✅ スプレッドシート『{spreadsheet.title}』を開きました")

                worksheets = spreadsheet.worksheets()
                print("📄 含まれているワークシート名一覧:")
                for ws in worksheets:
                    print(" -", ws.title)

            except Exception as e:
                print("❌ スプレッドシートのタイトル名が一致していないか、認証に失敗しています")
                print("📄 エラー内容:", e)

            
            # シート取得 書き込み操作用
            gsheet = client.open(SPREADSHEET_TITLE).worksheet("仕訳帳")

        except Exception as e:
            print(f"❌ gsheet の初期化に失敗しました（シート名誤りまたは認証エラー）: {e}")
            return
        
        # Google Sheets API クライアント（罫線など高機能操作用）
        service = build("sheets", "v4", credentials=credentials)
        spreadsheet_info = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        spreadsheet_id = SPREADSHEET_ID
        sheet_id = spreadsheet_info["sheets"][0]["properties"]["sheetId"]  # "sheetId" は変数ではなく、Google APIが付与しているID


        print("✅ 仕訳データをスプレッドシートに追加しました。")
    
    except Exception as e:
        print(f"❌ スプレッドシートの追加に失敗しました: {e}")


    # 複数明細を行データに変換 　出力行数 = 最大明細数（借方 or 貸方）
    num_rows = max(len(entry["debit_entries"]), len(entry["credit_entries"]))
    values = []

    for i in range(num_rows):
        debit = entry["debit_entries"][i] if i < len(entry["debit_entries"]) else {"account": "", "amount": ""}
        credit = entry["credit_entries"][i] if i < len(entry["credit_entries"]) else {"account": "", "amount": ""}

        row = [
            entry["date"] if i == 0 else "",
            debit["account"],
            debit["amount"],
            credit["account"],
            credit["amount"],
            entry["summary"] if i == 0 else ""
        ]
        values.append(row)

    # 現在の最終行取得（1-indexed）
    start_row = len(gsheet.get_all_values()) + 1
    gsheet.append_rows(values, value_input_option="USER_ENTERED")

    # 罫線リクエスト設定
    border_request = {
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": start_row - 1,
                "endRowIndex": start_row - 1 + num_rows,
                "startColumnIndex": 0,
                "endColumnIndex": 6
            },
            "top":    {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
            "bottom": {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
            "left":   {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
            "right":  {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
            "innerHorizontal": {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
            "innerVertical":   {"style": "SOLID", "width": 1, "color": {"red": 0, "green": 0, "blue": 0}},
        }
    }

    # Sheets APIで罫線を生成
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [border_request]}
    ).execute()

    print(f"✅ {num_rows}行の複合仕訳を追加し、罫線を設定しました。")
    
    
# 重複した勘定科目を合算表示する。　貸借別々の場合は合算しない。
def convert_gpt_entries_to_transaction(entry_data: dict) -> dict:
    """
    GPT出力からスプレッドシート用の合算済み仕訳構造に変換。
    同一勘定科目は金額を合算する。
    """
    debit_summary = defaultdict(int)
    credit_summary = defaultdict(int)

    # ❌ 現在の実装では、借方（debit）と貸方（credit）に同じ勘定科目がある場合でも、相殺（差し引き表示）はされません。
    for e in entry_data.get("entries", []):
        debit_summary[e["debit"]] += int(e["amount"])
        credit_summary[e["credit"]] += int(e["amount"])

    # 合算結果をリスト化（辞書形式で返す）
    debit_entries = [{"account": k, "amount": v} for k, v in debit_summary.items()]
    credit_entries = [{"account": k, "amount": v} for k, v in credit_summary.items()]

    return {
        "date": entry_data.get("date"),
        "debit_entries": debit_entries,
        "credit_entries": credit_entries,
        "summary": entry_data.get("summary", "")
    }

# ======================================================

# GPTプロンプト生成関数
# GPTの出力に fiscal dates を補完する関数
# OCR→GPT→日付補完→送信まで一括実行する関数
def process_ocr_and_send(frame):
    ocr_text = extract_text_from_frame(frame)
    print("====================================")
    print("📄 OCR出力:")
    print(ocr_text)
    print("====================================")

    prompt = build_prompt(ocr_text)
    gpt_result = ask_gpt(prompt)
    print("🧠 GPTによる取引分類:")
    print(gpt_result)

    try:
        gpt_data = json.loads(gpt_result)
    except json.JSONDecodeError as e:
        print("❌ GPTの出力がJSON形式ではありません。送信を中止します。")
        return

    gpt_data = merge_fiscal_dates_into_gpt(gpt_data, ocr_text)

    if gpt_data.get("type") == "depreciation":
        dep = calculate_depreciation_by_year(
            starting_date=gpt_data.get("acquisition_date"),
            calc_closing_date=gpt_data.get("calc_closing_date"),
            method=gpt_data.get("method"),
            price=gpt_data.get("amount"),
            life=gpt_data.get("life"),
            target_year=gpt_data.get("target_year"),
            current_volume=gpt_data.get("current_volume"),
            total_volume=gpt_data.get("total_volume")
        )
        if dep:
            gpt_data["closing_date"] = gpt_data.get("calc_closing_date")  # FastAPIに送るために closing_date を追加
            print(f"✅ 減価償却費を上書き: {dep}")
            if gpt_data["entries"]:
                gpt_data["entries"][0]["amount"] = dep
            else:
                gpt_data["entries"] = [{
                    "debit": "減価償却費",
                    "credit": "減価償却累計額",
                    "amount": dep
                }]
        else:
            print("❌ 減価償却費が取得できませんでした。")

    send_to_fastapi(gpt_data.get("type"), gpt_data)

# ====================================================
    # スプレッドシートへの記録
    # try:
        # entry = gpt_data["entries"][0]
        # append_multi_entry_transaction({  # リスト構造で管理
        #     "date": gpt_data.get("date"),
        #     "debit_entries": [{"account": entry["debit"], "amount": int(entry["amount"])}],
        #     "credit_entries": [{"account": entry["credit"], "amount": int(entry["amount"])}],
        #     "summary": gpt_data.get("summary", "")
        # })
        
    #  -------------- ↓ 修正後 --------------------------------------
    #     debit_entries = []
    #     credit_entries = []

    #     for e in gpt_data["entries"]:
    #         debit_entries.append({"account": e["debit"], "amount": int(e["amount"])})
    #         credit_entries.append({"account": e["credit"], "amount": int(e["amount"])})

    #     append_multi_entry_transaction({
    #         "date": gpt_data.get("date"),
    #         "debit_entries": debit_entries,
    #         "credit_entries": credit_entries,
    #         "summary": gpt_data.get("summary", "")
    #     })

    # except Exception as e:
    #     print(f"⚠️ スプレッドシートへの書き込みに失敗しました: {e}")
    
    #  -------------- ↓ 修正後 --------------------------------------

    # process_ocr_and_send 内の呼び出し部分で使用
    # try:
    #     transaction = convert_gpt_entries_to_transaction(gpt_data)
    #     append_multi_entry_transaction(transaction)
    # except Exception as e:
    #     print(f"⚠️ スプレッドシートへの書き込みに失敗しました: {e}")
    
    #  -------------- ↓ 修正後 --------------------------------------
    # スプレッドシートへ入力前に確認を行う
        
    # 仕訳構造を変換    
    transaction = convert_gpt_entries_to_transaction(gpt_data)
    
    # JSONプレビューを表示（任意）
    import pprint
    print("\n📄 スプレッドシートに記入予定の仕訳:")
    pprint.pprint(transaction)

    # ✅ ユーザーに確認を取る
    user_input = input("📌 この内容をスプレッドシートに記入しますか？ [Y/N]: ").strip().lower()

    if user_input == "y":
        try:
            append_multi_entry_transaction(transaction)
        except Exception as e:
            print(f"⚠️ スプレッドシートへの書き込みに失敗しました: {e}")
    else:
        print("🛑 スプレッドシートへの記入はキャンセルされました。")

# ====================================================


# === メインループ ===
# カメラ起動・白枠描画・キー操作ループを統合
print("📷 カメラを起動中... (ESCキーで終了、's'キーで処理実行)")

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ カメラからフレームを取得できませんでした。")
        break

    height, width, _ = frame.shape
    # 中央90%の範囲を計算
    box_width = int(width * 0.8)  # ←ここを変更することで撮影する範囲を設定できる
    box_height = int(height * 0.8)
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
        cropped_frame = frame[start_y:end_y, start_x:end_x]
        process_ocr_and_send(cropped_frame)

    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()

