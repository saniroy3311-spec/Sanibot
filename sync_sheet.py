import sqlite3, os, json, glob
import gspread
from google.oauth2.service_account import Credentials

db_path = "/root/Sanibot/data/journal.db"
env_path = "/root/Sanibot/.env"
spreadsheet_id = "1PUdx_RO4R23a7yKGNtyhXU88xaWxt2x-mkjr-3Ge2bQ"

if not os.path.exists(db_path):
    print(f"Error: Database not found at {db_path}")
    exit(1)

# 1. Read trades from SQLite
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cur.fetchall()]

if not tables:
    print("No tables found in journal.db")
    exit(0)

tname = "trades" if "trades" in tables else tables[0]
cur.execute(f"SELECT * FROM {tname} ORDER BY rowid ASC")
rows = cur.fetchall()
conn.close()

print(f"Found {len(rows)} trades in local database.")

# 2. Locate Google Credentials
creds_dict = None
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("GSHEET_CREDENTIALS_JSON="):
                raw = line.split("=", 1).strip()
                if raw.startswith("{"):
                    try:
                        creds_dict = json.loads(raw)
                        print("Loaded credentials from .env")
                        break
                    except:
                        pass

if not creds_dict:
    json_files = glob.glob("/root/Sanibot/*.json") + glob.glob("/root/*.json")
    for jf in json_files:
        try:
            with open(jf) as f:
                data = json.load(f)
                if data.get("type") == "service_account" and "private_key" in data:
                    creds_dict = data
                    print(f"Found credentials in file: {jf}")
                    break
        except:
            pass

if not creds_dict:
    print("\n[!] Google Credentials not found.")
    print("Please paste your Google service account JSON into: /root/Sanibot/credentials.json")
    exit(1)

# 3. Connect to Google Sheets
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sh = gc.open_by_key(spreadsheet_id)

try:
    ws = sh.worksheet("BOT-V10")
except Exception:
    ws = sh.get_worksheet(0)

print(f"Connected to Google Sheet: '{sh.title}' | Tab: '{ws.title}'")

# 4. Sync only missing trades
existing_timestamps = ws.col_values(1)
added = 0

for r in rows:
    trade_key = str(r[0]) if str(r[0]).startswith("2026") else str(r)
    if trade_key not in existing_timestamps:
        ws.append_row([str(x) for x in r])
        print(f"-> Synced: {trade_key}")
        added += 1

print(f"\n>>> SUCCESS: Synced {added} missing trades to Google Sheet! <<<")
