"""Signal logic shared by backtest and live daily script.  NO forward-looking data used."""
import numpy as np
import pandas as pd

DEFAULT = dict(
    target_vol=0.45,        # annualised vol target for position scaling
    map_={6: 1.0, 5: 0.8, 4: 0.6, 3: 0.3, 2: 0.0, 1: 0.0, 0: 0.0},
    breakout_boost=True,    # volume-confirmed 20d breakout -> at least 80% (if score>=4)
    crash_guard=True,       # big bear candle (< -1.5 ATR) -> halve exposure for 3 days
    rebal_threshold=0.10,   # only trade when |target - current| >= 10% of equity
    dd_caps=((0.15, 0.75), (0.20, 0.50), (0.25, 0.25), (0.30, 0.0)),  # drawdown -> exposure cap
    fee=0.002,              # per side, incl. slippage
    step=0.05,              # exposure rounded to 5% steps
)


def trend_score(F: pd.DataFrame) -> pd.Series:
    s = ((F.close > F.sma200).astype(int)
         + (F.ema21 > F.ema55).astype(int)
         + (F.close > F.ema21).astype(int)
         + (F.macd_hist > 0).astype(int)
         + (F.mom20 > 0).astype(int)
         + (F.mom60 > 0).astype(int))
    return s


def raw_target(F: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Target exposure BEFORE drawdown caps (pure signal). Returns DataFrame with components."""
    sc = trend_score(F)
    base = sc.map(p["map_"]).astype(float)
    if p["breakout_boost"]:
        boost = (F.brk20_up == 1) & (F.vol_ratio > 1.2) & (sc >= 4)
        base = np.where(boost, np.maximum(base, 0.8), base)
    vol_scalar = (p["target_vol"] / F.vol20).clip(upper=1.0).fillna(0)
    tgt = pd.Series(base, index=F.index) * vol_scalar
    guard = pd.Series(0, index=F.index)
    if p["crash_guard"]:
        g = (F.body_atr < -1.5).astype(int)
        guard = g.rolling(3, min_periods=1).max().fillna(0)  # active day of + next 2 days
        tgt = np.where(guard == 1, tgt * 0.5, tgt)
    tgt = (np.round(pd.Series(tgt, index=F.index) / p["step"]) * p["step"]).clip(0, 1)
    return pd.DataFrame({"score": sc, "base": base, "vol_scalar": vol_scalar, "guard": guard, "target": tgt})


def dd_cap(dd: float, caps) -> float:
    cap = 1.0
    for lvl, c in caps:
        if dd <= -lvl:
            cap = min(cap, c)
    return cap
