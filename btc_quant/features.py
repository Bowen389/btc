"""Indicator + candlestick-pattern feature engineering for daily BTC bars."""
import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy().reset_index(drop=True)
    c, o, h, l, v = d.close, d.open, d.high, d.low, d.volume
    d["ret"] = c.pct_change()
    d["logret"] = np.log(c).diff()

    # --- trend ---
    for n in (10, 20, 50, 100, 200):
        d[f"sma{n}"] = c.rolling(n).mean()
    for n in (12, 21, 26, 55):
        d[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    d["macd"] = d.ema12 - d.ema26
    d["macd_sig"] = d.macd.ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d.macd - d.macd_sig
    d["dist200"] = c / d.sma200 - 1
    d["dist50"] = c / d.sma50 - 1
    d["sma200_slope"] = d.sma200.pct_change(20)
    d["above200"] = (c > d.sma200).astype(int)
    d["golden"] = (d.sma50 > d.sma200).astype(int)

    # --- momentum ---
    for n in (5, 10, 20, 60, 120):
        d[f"mom{n}"] = c.pct_change(n)
    d["rsi14"] = rsi(c, 14)
    d["rsi2"] = rsi(c, 2)

    # --- volatility ---
    d["atr14"] = atr(d, 14)
    d["atrp"] = d.atr14 / c
    d["vol20"] = d.logret.rolling(20).std() * np.sqrt(365)
    d["vol60"] = d.logret.rolling(60).std() * np.sqrt(365)
    mid = c.rolling(20).mean(); sd = c.rolling(20).std()
    d["bb_up"], d["bb_lo"] = mid + 2 * sd, mid - 2 * sd
    d["bb_pos"] = (c - d.bb_lo) / (d.bb_up - d.bb_lo)
    d["bb_width"] = (d.bb_up - d.bb_lo) / mid

    # --- channels (use PREVIOUS bars so breakout is detectable today) ---
    for n in (10, 20, 55):
        d[f"hh{n}"] = h.rolling(n).max().shift(1)
        d[f"ll{n}"] = l.rolling(n).min().shift(1)
    d["brk20_up"] = (c > d.hh20).astype(int)
    d["brk55_up"] = (c > d.hh55).astype(int)
    d["brk10_dn"] = (c < d.ll10).astype(int)
    d["brk20_dn"] = (c < d.ll20).astype(int)

    # --- volume ---
    d["vol_sma20"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d.vol_sma20
    d["obv"] = (np.sign(d.ret.fillna(0)) * v).cumsum()
    d["obv_slope"] = d.obv.diff(10)

    # --- candlestick anatomy ---
    body = (c - o)
    rng = (h - l).replace(0, np.nan)
    d["body"] = body
    d["body_pct"] = body.abs() / rng
    d["upper_wick"] = (h - np.maximum(c, o)) / rng
    d["lower_wick"] = (np.minimum(c, o) - l) / rng
    d["bull"] = (c > o).astype(int)
    d["body_atr"] = body / d.atr14

    # single-bar patterns
    d["doji"] = (d.body_pct < 0.1).astype(int)
    d["hammer"] = ((d.lower_wick > 0.6) & (d.upper_wick < 0.15) & (d.body_pct < 0.35)).astype(int)
    d["shooting_star"] = ((d.upper_wick > 0.6) & (d.lower_wick < 0.15) & (d.body_pct < 0.35)).astype(int)
    d["marubozu_bull"] = ((d.body_pct > 0.85) & (d.bull == 1)).astype(int)
    d["marubozu_bear"] = ((d.body_pct > 0.85) & (d.bull == 0)).astype(int)
    d["big_bull"] = (d.body_atr > 1.5).astype(int)
    d["big_bear"] = (d.body_atr < -1.5).astype(int)

    # two-bar patterns
    po, pc_, ph, pl = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    d["bull_engulf"] = ((pc_ < po) & (c > o) & (c > po) & (o < pc_)).astype(int)
    d["bear_engulf"] = ((pc_ > po) & (c < o) & (c < po) & (o > pc_)).astype(int)
    d["inside_bar"] = ((h < ph) & (l > pl)).astype(int)
    d["outside_bar"] = ((h > ph) & (l < pl)).astype(int)
    d["piercing"] = ((pc_ < po) & (c > o) & (o < pl) & (c > (po + pc_) / 2) & (c < po)).astype(int)
    d["dark_cloud"] = ((pc_ > po) & (c < o) & (o > ph) & (c < (po + pc_) / 2) & (c > po)).astype(int)

    # three-bar patterns
    b1, b2, b3 = d.bull.shift(2), d.bull.shift(1), d.bull
    c1, c2 = c.shift(2), c.shift(1)
    d["three_white"] = ((b1 == 1) & (b2 == 1) & (b3 == 1) & (c > c2) & (c2 > c1) & (d.body_pct > 0.5)).astype(int)
    d["three_black"] = ((b1 == 0) & (b2 == 0) & (b3 == 0) & (c < c2) & (c2 < c1) & (d.body_pct > 0.5)).astype(int)
    body1 = (c.shift(2) - o.shift(2)); body2 = (c.shift(1) - o.shift(1))
    d["morning_star"] = ((body1 < 0) & (body2.abs() < body1.abs() * 0.3) & (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)).astype(int)
    d["evening_star"] = ((body1 > 0) & (body2.abs() < body1.abs() * 0.3) & (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)).astype(int)

    # streaks
    sgn = np.sign(d.ret.fillna(0))
    streak = np.zeros(len(d))
    for i in range(1, len(d)):
        streak[i] = streak[i - 1] + sgn.iloc[i] if sgn.iloc[i] == np.sign(streak[i - 1]) or streak[i - 1] == 0 else sgn.iloc[i]
    d["streak"] = streak

    # forward returns (for research only — never used in signals)
    for n in (1, 3, 5, 10, 20):
        d[f"fwd{n}"] = c.shift(-n) / c - 1
    return d


PATTERNS_BULL = ["hammer", "bull_engulf", "piercing", "morning_star", "three_white", "marubozu_bull", "big_bull", "brk20_up", "brk55_up"]
PATTERNS_BEAR = ["shooting_star", "bear_engulf", "dark_cloud", "evening_star", "three_black", "marubozu_bear", "big_bear", "brk10_dn", "brk20_dn"]
PATTERNS_NEUTRAL = ["doji", "inside_bar", "outside_bar"]
