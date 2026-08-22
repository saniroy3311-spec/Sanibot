import os, json, sqlite3
import gspread
from google.oauth2.service_account import Credentials

cred_path = "/root/Sanibot/credentials.json"
env_path = "/root/Sanibot/.env"
spreadsheet_id = "1PUdx_RO4R23a7yKGNtyhXU88xaWxt2x-mkjr-3Ge2bQ"
db_path = "/root/Sanibot/data/journal.db"

print("=" * 60)
print("     SANIBOT GOOGLE SHEETS SYNCHRONIZATION")
print("=" * 60)

# 1. Verify credentials.json
if not os.path.exists(cred_path):
    print(f"[FAIL] Credentials file not found at: {cred_path}")
    exit(1)

with open(cred_path) as f:
    cred_data = json.load(f)

client_email = cred_data.get("client_email", "Unknown")
print(f"[1/4] Loaded credentials for: {client_email}")

# 2. Connect to Google Sheets
scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
try:
    creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    print(f"[2/4] Connected to Google Sheet: '{sh.title}'")
    
    all_tabs = [ws.title for ws in sh.worksheets()]
    target_tab = "BOT-V10" if "BOT-V10" in all_tabs else all_tabs[0]
    ws = sh.worksheet(target_tab)
    print(f"[3/4] Active logging tab: '{ws.title}'")
except gspread.exceptions.APIError as e:
    print(f"\n[ERROR] Permission Denied (403).")
    print(f"--> Please ensure you have SHARED your Google Sheet with:")
    print(f"    {client_email} as EDITOR!")
    exit(1)
except Exception as e:
    print(f"[ERROR] Failed connecting to Google Sheets: {e}")
    exit(1)

# 3. Read trades from journal.db
if not os.path.exists(db_path):
    print(f"[FAIL] journal.db not found at: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cur.fetchall()]
tname = "trades" if "trades" in tables else tables[0]
cur.execute(f"SELECT * FROM {tname} ORDER BY rowid ASC")
rows = cur.fetchall()
conn.close()

print(f"[4/4] Read {len(rows)} trades from local database.")

# 4. Sync only missing rows
existing_col1 = ws.col_values(1)
added = 0

for r in rows:
    trade_id_or_time = str(r[0]) if str(r[0]).startswith("2026") else str(r) if len(r) > 1 else str(r[0])
    if trade_id_or_time not in existing_col1:
        row_values = [str(x) for x in r]
        ws.append_row(row_values)
        print(f"  -> Appended trade: {trade_id_or_time}")
        added += 1

print("=" * 60)
print(f"SUCCESS: Synchronized {added} missing trades to Google Sheet!")
print("=" * 60)
