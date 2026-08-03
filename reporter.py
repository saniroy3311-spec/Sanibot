import os, subprocess, pandas as pd

for path in ['c:/Users/sanir/Downloads/Sani/.env', 'c:/Users/sanir/Downloads/Sani/Bot-v10-main/.env']:
    if os.path.exists(path):
        with open(path, 'r') as f: lines = f.readlines()
        with open(path, 'w') as f:
            for line in lines:
                if line.startswith('TREND_ATR_MULT='): f.write('TREND_ATR_MULT=2.0\n')
                elif line.startswith('TREND_RR='): f.write('TREND_RR=1.5\n')
                elif line.startswith('ADX_TREND_TH='): f.write('ADX_TREND_TH=22\n')
                elif line.startswith('ENTRY_STRATEGY='): f.write('ENTRY_STRATEGY=rsi_bounce\n')
                elif line.startswith('POSITION_BTC_SIZE='): f.write('POSITION_BTC_SIZE=0.1\n')
                else: f.write(line)

print('Running backtest...')
subprocess.run(['python', 'backtest.py', '--csv', 'data/btc_30m_25mo.csv', '--out', 'bt_trades_fresh.csv'])

df = pd.read_csv('bt_trades_fresh.csv')
df['entry_dt'] = pd.to_datetime(df['entry_ts'], unit='ms')
df['year_month'] = df['entry_dt'].dt.to_period('M')

print('\n=== TOTAL SUMMARY (25 MONTHS) ===')
print('Total Trades:', len(df))
print('Wins:', (df['real_pl'] > 0).sum())
print('Losses:', (df['real_pl'] <= 0).sum())
print(f"Win Rate: {(df['real_pl'] > 0).mean() * 100:.2f}%")
print(f"Total Net PnL (USD): ${df['real_pl'].sum():,.2f}")
print(f"Max Win (USD): ${df['real_pl'].max():,.2f}")
print(f"Max Loss (USD): ${df['real_pl'].min():,.2f}")

print('\n=== EXIT REASON BREAKDOWN ===')
print(df.groupby('exit_reason').agg(Count=('trade_id', 'count'), PnL_USD=('real_pl', lambda x: f"${x.sum():,.2f}")))

print('\n=== SIGNAL TYPE BREAKDOWN ===')
print(df.groupby('signal_type').agg(Count=('trade_id', 'count'), PnL_USD=('real_pl', lambda x: f"${x.sum():,.2f}")))

monthly = df.groupby('year_month').agg(
    Trades=('trade_id', 'count'),
    Wins=('real_pl', lambda x: int((x > 0).sum())),
    Losses=('real_pl', lambda x: int((x <= 0).sum())),
    PnL_USD=('real_pl', 'sum')
)
monthly['Win_Rate'] = (monthly['Wins'] / monthly['Trades'] * 100).round(1).astype(str) + '%'
monthly['PnL_USD'] = monthly['PnL_USD'].apply(lambda x: f"${x:,.2f}")

print('\nMONTHLY_TABLE_START')
print(monthly[['Trades', 'Wins', 'Losses', 'Win_Rate', 'PnL_USD']].to_markdown())
print('MONTHLY_TABLE_END')
