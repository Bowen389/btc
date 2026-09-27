"""Strategy families for V2 development. Each family = grid of params + make(F, params) -> raw exposure [0,1].
All families share the same risk layer (vol targeting) and the same circuit-breaker in simulate()."""
import itertools
import numpy as np, pandas as pd
from strategy import trend_score

MAPS = {
    "steep": {6: 1.0, 5: 0.8, 4: 0.6, 3: 0.3, 2: 0.0, 1: 0.0, 0: 0.0},
    "binary": {6: 1.0, 5: 1.0, 4: 1.0, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
    "linear": {6: 1.0, 5: 0.83, 4: 0.67, 3: 0.5, 2: 0.33, 1: 0.17, 0: 0.0},
    "strict": {6: 1.0, 5: 0.7, 4: 0.4, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
}
TVS = [0.30, 0.40, 0.50, 9.9]


def risk_layer(raw, F, tv, step=0.05):
    vs = (tv / F.vol20).clip(upper=1.0).fillna(0)
    t = pd.Series(np.asarray(raw, dtype=float), index=F.index) * vs
    return (np.round(t / step) * step).clip(0, 1)


def grid(**kw):
    keys = list(kw)
    return [dict(zip(keys, v)) for v in itertools.product(*kw.values())]


# ---------------- F1: V1 discrete trend score ----------------
def f1_make(F, p):
    sc = trend_score(F); base = sc.map(MAPS[p["map"]]).astype(float)
    if p["boost"]:
        base = np.where((F.brk20_up == 1) & (F.vol_ratio > 1.2) & (sc >= 4), np.maximum(base, 0.8), base)
    if p["guard"]:
        g = (F.body_atr < -1.5).astype(int).rolling(3, min_periods=1).max().fillna(0)
        base = np.where(g == 1, base * 0.5, base)
    return risk_layer(base, F, p["tv"])
F1_GRID = grid(map=list(MAPS), boost=[False, True], guard=[False, True], tv=TVS)


# ---------------- F2: continuous trend strength ----------------
def f2_make(F, p):
    a = F.atr14
    z = pd.concat([(F.close - F.ema21) / a, (F.ema21 - F.ema55) / a, (F.close - F.sma200) / a / 3,
                   F.mom20 / (F.vol20 * np.sqrt(20 / 365)), F.mom60 / (F.vol60 * np.sqrt(60 / 365)), F.macd_hist / a], axis=1)
    s = np.tanh(z / p["scale"]).mean(axis=1)
    raw = ((s - p["offset"]) * p["gain"]).clip(0, 1)
    return risk_layer(raw, F, p["tv"])
F2_GRID = grid(scale=[1, 2, 4], offset=[0.0, 0.1, 0.2], gain=[1.5, 2.5], tv=TVS)


# ---------------- F3: V1 + research-driven boosters ----------------
def f3_make(F, p):
    sc = trend_score(F).astype(float)
    if p["b_rsi"]:
        sc = sc + ((F.rsi14 >= 70) & (F.rsi14 < 80)).astype(int) - ((F.rsi14 >= 30) & (F.rsi14 < 50)).astype(int)
    if p["b_candle"]:
        sc = sc + (((F.three_white == 1) | (F.big_bull == 1)) & (F.above200 == 1)).astype(int).rolling(3, min_periods=1).max()
    if p["b_brk"]:
        sc = sc + ((F.brk20_up == 1) & (F.vol_ratio > 1.2)).astype(int).rolling(5, min_periods=1).max()
    if p["b_bear"]:
        sc = sc - (F.body_atr < -1.5).astype(int).rolling(3, min_periods=1).max()
    sc = sc.clip(0, 6).round().astype(int)
    base = sc.map(MAPS[p["map"]]).astype(float)
    return risk_layer(base, F, p["tv"])
F3_GRID = grid(b_rsi=[False, True], b_candle=[False, True], b_brk=[False, True], b_bear=[False, True], map=["steep", "linear", "strict"], tv=[0.30, 0.40, 0.50])


# ---------------- F4: V1 + RSI2 dip-buying in uptrend ----------------
def f4_make(F, p):
    sc = trend_score(F); base = sc.map(MAPS["steep"]).astype(float).values
    rsi2 = F.rsi2.values; on = False; raw = np.zeros(len(F))
    for i in range(len(F)):
        if not on and sc.iloc[i] >= p["min_score"] and rsi2[i] < p["rsi_thr"]: on = True
        elif on and (rsi2[i] > 60 or sc.iloc[i] < 3): on = False
        raw[i] = min(1.0, base[i] + (p["add"] if on else 0.0))
    return risk_layer(raw, F, p["tv"])
F4_GRID = grid(min_score=[3, 4], rsi_thr=[10, 20], add=[0.2, 0.4], tv=[0.30, 0.40, 0.50])


# ---------------- F6: Turtle breakout + ATR trailing stop + pyramiding ----------------
def f6_make(F, p):
    hh = F[f"hh{p['entry']}"].values; ll = F[f"ll{p['exit']}"].values; atr = F.atr14.values; c = F.close.values; s200 = F.sma200.values
    raw = np.zeros(len(F)); units = 0; hi = 0.0; last_add = 0.0; ufrac = 0.0
    for i in range(len(F)):
        if np.isnan(hh[i]) or np.isnan(atr[i]) or np.isnan(s200[i]): continue
        if units == 0:
            if c[i] > hh[i] and (not p["filt200"] or c[i] > s200[i]):
                units = 1; hi = c[i]; last_add = c[i]; ufrac = p["risk"] * c[i] / (p["trail"] * atr[i])
        else:
            hi = max(hi, c[i])
            if c[i] < ll[i] or c[i] < hi - p["trail"] * atr[i]: units = 0
            elif units < p["max_units"] and c[i] > last_add + 0.5 * atr[i]: units += 1; last_add = c[i]
        raw[i] = min(1.0, units * ufrac) if units > 0 else 0.0
    return risk_layer(raw, F, p["tv"])
F6_GRID = grid(entry=[20, 55], exit=[10, 20], trail=[2, 3, 4], risk=[0.01, 0.02, 0.03], max_units=[2, 4], filt200=[False, True], tv=[0.40, 9.9])


# ---------------- ML: walk-forward gradient boosting / logistic ----------------
ML_FEATS = ["body_pct", "upper_wick", "lower_wick", "bull", "body_atr", "streak", "above200", "golden", "brk20_up", "brk55_up", "brk10_dn", "brk20_dn",
            "doji", "hammer", "shooting_star", "bull_engulf", "bear_engulf", "three_white", "three_black", "big_bull", "big_bear", "inside_bar", "outside_bar",
            "morning_star", "evening_star", "rsi14", "rsi2", "atrp", "vol20", "vol60", "bb_pos", "bb_width", "vol_ratio", "dist200", "dist50", "sma200_slope",
            "mom5", "mom10", "mom20", "mom60", "mom120"]


def ml_frame(F):
    X = F[ML_FEATS].copy()
    X["ret1"] = F.ret; X["ret3"] = F.close.pct_change(3)
    X["c_ema21"] = F.close / F.ema21 - 1; X["ema21_55"] = F.ema21 / F.ema55 - 1; X["macd_n"] = F.macd_hist / F.close
    X["vol_2060"] = F.vol20 / F.vol60; X["c_hh20"] = F.close / F.hh20 - 1; X["c_ll20"] = F.close / F.ll20 - 1; X["c_hh55"] = F.close / F.hh55 - 1
    X["obv_n"] = F.obv_slope / F.vol_sma20; X["dow"] = F.date.dt.dayofweek
    return X.replace([np.inf, -np.inf], np.nan)


def ml_walk_forward(F, model_name, horizon=10, start="2021-01-01", retrain_months=6, tv=0.40, q_lo=0.40, q_hi=0.70):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer
    X = ml_frame(F); y = (F[f"fwd{horizon}"] > 0).astype(int)
    raw = pd.Series(0.0, index=F.index); prob = pd.Series(np.nan, index=F.index)
    periods = pd.date_range(start, F.date.max(), freq=f"{retrain_months}MS")
    for k, S in enumerate(periods):
        E = periods[k + 1] if k + 1 < len(periods) else F.date.max() + pd.Timedelta(days=1)
        tr = (F.date <= S - pd.Timedelta(days=horizon + 1)) & X.notna().all(axis=1) & F[f"fwd{horizon}"].notna()
        te = (F.date >= S) & (F.date < E)
        if model_name == "hgb":
            mdl = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=50, l2_regularization=1.0, random_state=0)
        else:
            mdl = make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(C=0.05, max_iter=1000))
        mdl.fit(X[tr], y[tr])
        p_tr = mdl.predict_proba(X[tr])[:, 1]; lo, hi = np.quantile(p_tr, q_lo), np.quantile(p_tr, q_hi)
        Xte = X[te].ffill().bfill()
        p_te = mdl.predict_proba(Xte)[:, 1]
        prob[te] = p_te
        raw[te] = np.clip((p_te - lo) / max(hi - lo, 1e-6), 0, 1)
    return risk_layer(raw, F, tv), prob


FAMILIES = {
    "F1 离散趋势分(V1)": (F1_GRID, f1_make),
    "F2 连续趋势强度": (F2_GRID, f2_make),
    "F3 趋势分+研究增强": (F3_GRID, f3_make),
    "F4 趋势+RSI2抄底": (F4_GRID, f4_make),
    "F6 海龟突破+ATR追踪": (F6_GRID, f6_make),
}
