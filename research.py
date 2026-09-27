"""Multi-angle statistical study of BTC daily bars 2019-01-01 -> now.
Outputs research_report.txt. Forward returns used ONLY here (research), never in live signals."""
import numpy as np, pandas as pd
from scipy import stats
from features import build_features, PATTERNS_BULL, PATTERNS_BEAR, PATTERNS_NEUTRAL

raw = pd.read_csv("btc_daily.csv", parse_dates=["date"])
F = build_features(raw)
D = F[F.date >= "2019-01-01"].copy()
out = []
P = lambda *a: out.append(" ".join(str(x) for x in a))

base = {n: D[f"fwd{n}"].mean() for n in (1, 5, 10, 20)}
basewin = {n: (D[f"fwd{n}"] > 0).mean() for n in (1, 5, 10, 20)}
P("=" * 78)
P(f"BTC-USD daily study  {D.date.min().date()} -> {D.date.max().date()}  n={len(D)}")
P("=" * 78)
P(f"Baseline avg fwd ret: 1d {base[1]*100:.2f}%  5d {base[5]*100:.2f}%  10d {base[10]*100:.2f}%  20d {base[20]*100:.2f}%")
P(f"Baseline win rate   : 1d {basewin[1]*100:.1f}%  5d {basewin[5]*100:.1f}%  10d {basewin[10]*100:.1f}%  20d {basewin[20]*100:.1f}%")


def cond_table(title, mask_dict, horizons=(1, 5, 10, 20)):
    P("\n" + "-" * 78); P(title); P("-" * 78)
    P(f"{'condition':<34}{'n':>5} " + " ".join(f"{'avg'+str(h)+'d':>8}{'win':>6}{'t':>6}" for h in horizons))
    for name, m in mask_dict.items():
        sub = D[m]
        if len(sub) < 5:
            P(f"{name:<34}{len(sub):>5}  (too few)"); continue
        cells = []
        for h in horizons:
            x = sub[f"fwd{h}"].dropna(); y = D[f"fwd{h}"].dropna()
            t = stats.ttest_ind(x, y, equal_var=False).statistic if len(x) > 2 else np.nan
            cells.append(f"{x.mean()*100:>7.2f}%{(x>0).mean()*100:>5.0f}%{t:>6.1f}")
        P(f"{name:<34}{len(sub):>5} " + " ".join(cells))


# 1) candlestick patterns, unconditional and conditional on trend regime
cond_table("1) BULLISH candlestick / breakout patterns (all regimes)", {p: D[p] == 1 for p in PATTERNS_BULL})
cond_table("1b) BULLISH patterns when close > SMA200", {p: (D[p] == 1) & (D.above200 == 1) for p in PATTERNS_BULL})
cond_table("1c) BULLISH patterns when close < SMA200", {p: (D[p] == 1) & (D.above200 == 0) for p in PATTERNS_BULL})
cond_table("2) BEARISH candlestick / breakdown patterns (all regimes)", {p: D[p] == 1 for p in PATTERNS_BEAR})
cond_table("2b) BEARISH patterns when close > SMA200", {p: (D[p] == 1) & (D.above200 == 1) for p in PATTERNS_BEAR})
cond_table("3) Neutral patterns", {p: D[p] == 1 for p in PATTERNS_NEUTRAL})

# 4) trend regimes
cond_table("4) Trend regimes", {
    "close > SMA200": D.above200 == 1,
    "close < SMA200": D.above200 == 0,
    "SMA50 > SMA200 (golden)": D.golden == 1,
    "SMA50 < SMA200 (death)": D.golden == 0,
    ">SMA200 & SMA200 rising": (D.above200 == 1) & (D.sma200_slope > 0),
    ">SMA200 & SMA200 falling": (D.above200 == 1) & (D.sma200_slope <= 0),
    "<SMA200 & SMA200 falling": (D.above200 == 0) & (D.sma200_slope <= 0),
    "<SMA200 & SMA200 rising": (D.above200 == 0) & (D.sma200_slope > 0),
    "close > EMA21 > EMA55": (D.close > D.ema21) & (D.ema21 > D.ema55),
    "close < EMA21 < EMA55": (D.close < D.ema21) & (D.ema21 < D.ema55),
    "MACD hist > 0": D.macd_hist > 0,
    "MACD hist < 0": D.macd_hist < 0,
})

# 5) distance from SMA200 buckets (overextension)
bins = [-1, -0.3, -0.15, 0, 0.15, 0.3, 0.6, 5]
cond_table("5) Distance from SMA200 buckets", {f"dist200 in ({bins[i]:+.2f},{bins[i+1]:+.2f}]": (D.dist200 > bins[i]) & (D.dist200 <= bins[i + 1]) for i in range(len(bins) - 1)})

# 6) RSI buckets
cond_table("6) RSI14 buckets", {f"RSI14 {lo}-{hi}": (D.rsi14 >= lo) & (D.rsi14 < hi) for lo, hi in [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 101)]})
cond_table("6b) RSI2 extremes by regime", {
    "RSI2<10 & >SMA200": (D.rsi2 < 10) & (D.above200 == 1),
    "RSI2<10 & <SMA200": (D.rsi2 < 10) & (D.above200 == 0),
    "RSI2>90 & >SMA200": (D.rsi2 > 90) & (D.above200 == 1),
    "RSI2>90 & <SMA200": (D.rsi2 > 90) & (D.above200 == 0),
})

# 7) volatility regimes
q = D.vol20.quantile([0.25, 0.5, 0.75])
cond_table("7) Realized vol (20d ann.) quartiles", {
    f"vol20 < {q[0.25]:.2f}": D.vol20 < q[0.25],
    f"vol20 {q[0.25]:.2f}-{q[0.5]:.2f}": (D.vol20 >= q[0.25]) & (D.vol20 < q[0.5]),
    f"vol20 {q[0.5]:.2f}-{q[0.75]:.2f}": (D.vol20 >= q[0.5]) & (D.vol20 < q[0.75]),
    f"vol20 > {q[0.75]:.2f}": D.vol20 >= q[0.75],
    "BB squeeze (width<20th pct)": D.bb_width < D.bb_width.quantile(0.2),
})

# 8) volume
cond_table("8) Volume confirmation", {
    "up day, vol_ratio>1.5": (D.bull == 1) & (D.vol_ratio > 1.5),
    "up day, vol_ratio<0.7": (D.bull == 1) & (D.vol_ratio < 0.7),
    "down day, vol_ratio>1.5": (D.bull == 0) & (D.vol_ratio > 1.5),
    "down day, vol_ratio<0.7": (D.bull == 0) & (D.vol_ratio < 0.7),
    "brk20_up & vol_ratio>1.2": (D.brk20_up == 1) & (D.vol_ratio > 1.2),
    "brk20_up & vol_ratio<=1.2": (D.brk20_up == 1) & (D.vol_ratio <= 1.2),
    "OBV 10d slope>0 & >SMA200": (D.obv_slope > 0) & (D.above200 == 1),
})

# 9) streaks
cond_table("9) Consecutive up/down streaks", {f"streak = {s:+d}": D.streak == s for s in (-5, -4, -3, -2, 2, 3, 4, 5)} | {"streak <= -6": D.streak <= -6, "streak >= 6": D.streak >= 6})

# 10) momentum / autocorrelation matrix
P("\n" + "-" * 78); P("10) Momentum vs mean reversion: corr(past N-day ret, next M-day ret)  (Spearman)"); P("-" * 78)
P(f"{'past\\next':<10}" + "".join(f"{m:>8}d" for m in (1, 5, 10, 20)))
for n in (1, 2, 3, 5, 10, 20, 60, 120):
    row = []
    for m in (1, 5, 10, 20):
        x = D[f"mom{n}"] if n in (5, 10, 20, 60, 120) else D.close.pct_change(n)
        s = pd.concat([x, D[f"fwd{m}"]], axis=1).dropna()
        row.append(f"{stats.spearmanr(s.iloc[:,0], s.iloc[:,1]).correlation:>9.3f}")
    P(f"{n:<10}" + "".join(row))

# 11) seasonality
P("\n" + "-" * 78); P("11) Seasonality"); P("-" * 78)
dow = D.groupby(D.date.dt.dayofweek).ret.agg(["mean", lambda x: (x > 0).mean(), "count"])
dow.index = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
P("Day of week (avg daily ret %, win %):")
for k, r in dow.iterrows():
    P(f"  {k}: {r['mean']*100:+.3f}%  win {r.iloc[1]*100:.1f}%")
mon = D.groupby(D.date.dt.month).ret.mean() * 100
P("Month avg daily ret %: " + ", ".join(f"{m}:{v:+.2f}" for m, v in mon.items()))

# 12) drawdown anatomy of buy&hold
eq = D.close / D.close.iloc[0]
dd = eq / eq.cummax() - 1
P("\n" + "-" * 78); P("12) Buy & hold since 2019: risk anatomy"); P("-" * 78)
P(f"Total return {eq.iloc[-1]:.1f}x   max drawdown {dd.min()*100:.1f}%   ann.vol {D.logret.std()*np.sqrt(365)*100:.0f}%")
P(f"Worst day {D.ret.min()*100:.1f}%   worst 5d {D.fwd5.min()*100:.1f}%   worst 20d {D.fwd20.min()*100:.1f}%")
P(f"% of days below SMA200: {(D.above200==0).mean()*100:.0f}%   NEXT-day avg ret when above200: {D[D.above200==1].fwd1.mean()*100:+.3f}%/d  below200: {D[D.above200==0].fwd1.mean()*100:+.3f}%/d")
dd_above = D[D.above200==1].fwd20.min(); dd_below = D[D.above200==0].fwd20.min()
P(f"Worst 20d fwd when above200: {dd_above*100:.1f}%   when below200: {dd_below*100:.1f}%")
P(f"Std of next-day ret above200: {D[D.above200==1].fwd1.std()*100:.2f}%  below200: {D[D.above200==0].fwd1.std()*100:.2f}%")

txt = "\n".join(out)
open("research_report.txt", "w").write(txt)
print(txt)
F.to_parquet("features.parquet") if False else F.to_csv("features.csv", index=False)
