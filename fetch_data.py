"""
Fetch BTC-USD daily OHLCV from Coinbase Exchange public API (no key needed).
Saves to btc_daily.csv. Fallback: CryptoCompare / Bitstamp.
"""
import time, datetime as dt, sys
import requests, pandas as pd

OUT = "btc_daily.csv"
START = dt.datetime(2018, 6, 1, tzinfo=dt.timezone.utc)   # warm-up for 200D MA


def fetch_coinbase(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    rows = []
    cur = start
    while cur < end:
        nxt = min(cur + dt.timedelta(days=299), end)
        params = {"granularity": 86400,
                  "start": cur.isoformat(), "end": nxt.isoformat()}
        for attempt in range(5):
            r = requests.get(url, params=params, timeout=20,
                             headers={"User-Agent": "btc-quant/1.0"})
            if r.status_code == 200:
                break
            time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"coinbase failed {r.status_code}: {r.text[:200]}")
        data = r.json()  # [time, low, high, open, close, volume]
        rows.extend(data)
        cur = nxt + dt.timedelta(days=1)
        time.sleep(0.35)  # be polite (public rate limit ~10 req/s)
    df = pd.DataFrame(rows, columns=["ts", "low", "high", "open", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_localize(None)
    df = df.drop_duplicates("date").sort_values("date")
    return df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def fetch_bitstamp(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    url = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
    rows = []
    cur = int(start.timestamp())
    end_ts = int(end.timestamp())
    while cur < end_ts:
        r = requests.get(url, params={"step": 86400, "limit": 1000, "start": cur}, timeout=20)
        r.raise_for_status()
        data = r.json()["data"]["ohlc"]
        if not data:
            break
        rows.extend(data)
        cur = int(data[-1]["timestamp"]) + 86400
        time.sleep(0.5)
    df = pd.DataFrame(rows)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s")
    df = df.drop_duplicates("date").sort_values("date")
    return df[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


if __name__ == "__main__":
    now = dt.datetime.now(dt.timezone.utc)
    # last COMPLETE UTC daily candle = yesterday
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        df = fetch_coinbase(START, end)
        src = "coinbase"
    except Exception as e:
        print("coinbase failed:", e, "-> trying bitstamp", file=sys.stderr)
        df = fetch_bitstamp(START, end)
        src = "bitstamp"
    # drop today's incomplete candle if present
    df = df[df["date"] < pd.Timestamp(end).tz_localize(None)]
    df.to_csv(OUT, index=False)
    print(f"source={src} rows={len(df)} range={df['date'].min().date()} -> {df['date'].max().date()}")
    print(df.tail(3).to_string(index=False))
