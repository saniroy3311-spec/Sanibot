import pandas as pd

df = pd.read_csv('bt_trades_fresh2.csv')
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
