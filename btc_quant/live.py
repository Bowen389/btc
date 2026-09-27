"""LIVE rules (V2 final): F2 continuous trend strength + vol targeting 40% + drawdown circuit-breaker.
Selected by anchored walk-forward 2021-2026 over 6 families + ML + ensembles (see develop_v2*.py, v2_results.csv)."""
import numpy as np, pandas as pd
from features import build_features
from strategy import trend_score, dd_cap

LIVE = dict(
    family="F2 连续趋势强度",
    scale=2.0, offset=0.0, gain=1.5,      # signal params (identical in every walk-forward year)
    tv=0.40,                              # risk dial: annualised vol target
    step=0.05, rebal_threshold=0.10, fee=0.002,
    dd_caps=((0.10, 0.75), (0.15, 0.50), (0.20, 0.25), (0.25, 0.0)),
    rearm_score=6,                        # after a halt, re-enter only when discrete trend score is 6/6
    hard_floor=0.70,                      # account red line: 70% of starting equity
)
COMP_NAMES = ["收盘−EMA21 (÷ATR)", "EMA21−EMA55 (÷ATR)", "收盘−SMA200 (÷3ATR)", "20日动量 (÷波动)", "60日动量 (÷波动)", "MACD柱 (÷ATR)"]


def components(F: pd.DataFrame, p=LIVE) -> pd.DataFrame:
    a = F.atr14
    Z = pd.concat([(F.close - F.ema21) / a, (F.ema21 - F.ema55) / a, (F.close - F.sma200) / a / 3,
                   F.mom20 / (F.vol20 * np.sqrt(20 / 365)), F.mom60 / (F.vol60 * np.sqrt(60 / 365)), F.macd_hist / a], axis=1)
    Z.columns = [f"z{i+1}" for i in range(6)]
    T = np.tanh(Z / p["scale"]); T.columns = [f"t{i+1}" for i in range(6)]
    s = T.mean(axis=1)
    raw = ((s - p["offset"]) * p["gain"]).clip(0, 1)
    vs = (p["tv"] / F.vol20).clip(upper=1.0).fillna(0)
    tgt = (np.round(raw * vs / p["step"]) * p["step"]).clip(0, 1)
    out = pd.concat([Z, T], axis=1); out["strength"] = s; out["raw"] = raw; out["vol_scalar"] = vs; out["target"] = tgt; out["score6"] = trend_score(F)
    return out


def scenario_targets(raw_df: pd.DataFrame, pct_moves=(-0.10, -0.08, -0.06, -0.04, -0.02, 0.0, 0.03, 0.06)) -> pd.DataFrame:
    """Approximate tomorrow's target if tomorrow closes at close*(1+m): append a synthetic bar and rebuild features."""
    last = raw_df.iloc[-1]; rows = []
    for m in pct_moves:
        px = last.close * (1 + m)
        syn = pd.DataFrame([dict(date=last.date + pd.Timedelta(days=1), open=last.close, high=max(px, last.close), low=min(px, last.close), close=px, volume=raw_df.volume.tail(20).mean())])
        Fx = build_features(pd.concat([raw_df, syn], ignore_index=True)); c = components(Fx).iloc[-1]
        rows.append(dict(move=m, close=px, strength=c.strength, target=c.target))
    return pd.DataFrame(rows)
