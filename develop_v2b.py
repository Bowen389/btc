"""Round 2: objective = maximise CAGR s.t. train MaxDD > -25% (user's literal definition), vs robust objective.
Also widen F2 grid and add F0 (hold + trend exit)."""
import json, time
import numpy as np, pandas as pd
from features import build_features
from strategy import DEFAULT, trend_score
from backtest import simulate, metrics
from strategy_v2 import FAMILIES, f2_make, grid, risk_layer, MAPS

CAPS = ((0.10, 0.75), (0.15, 0.50), (0.20, 0.25), (0.25, 0.0))
P = dict(DEFAULT, dd_caps=CAPS, rebal_threshold=0.10, rearm_score=6)
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]; OOS = ("2021-01-01", "2026-12-31"); DD_LIMIT = -0.25
raw = pd.read_csv("btc_daily.csv", parse_dates=["date"]); F = build_features(raw)

def f0_make(F, p):
    sc = trend_score(F); base = (sc >= p["k"]).astype(float)
    return risk_layer(base, F, p["tv"])
F0_GRID = grid(k=[2, 3, 4, 5], tv=[0.30, 0.40, 0.50, 0.60, 9.9])
F2W_GRID = grid(scale=[1, 2, 4], offset=[-0.1, 0.0, 0.1, 0.2], gain=[1.5, 2.5, 4.0], tv=[0.30, 0.40, 0.50, 0.60, 9.9])
FAM = dict(FAMILIES); FAM["F0 持有+趋势退出"] = (F0_GRID, f0_make); FAM["F2w 连续趋势(宽域)"] = (F2W_GRID, f2_make)
FAM.pop("F2 连续趋势强度")

def select(cands, obj):
    ok = [(i, m) for i, m in cands if m["maxdd"] > DD_LIMIT]
    if not ok: ok = sorted(cands, key=lambda x: x[1]["maxdd"], reverse=True)[:max(1, len(cands) // 10)]
    df = pd.DataFrame({i: m for i, m in ok}).T
    if obj == "cagr": return int(df.cagr.idxmax())
    if obj == "cagr_sharpe": return int((df.cagr.rank() + df.sharpe.rank()).idxmax())
    return int((df.sharpe.rank() + df.calmar.rank()).idxmax())

def walk_forward(grid_, make, obj, targets=None, sims=None):
    targets = targets or [make(F, p) for p in grid_]
    sims = sims or [simulate(F, t, P, "2019-01-01", "2026-12-31") for t in targets]
    st = pd.Series(0.0, index=F.index); chosen = {}
    for Y in YEARS:
        cands = [(i, metrics(s.equity[: f"{Y-1}-12-31"])) for i, s in enumerate(sims)]
        b = select(cands, obj); chosen[Y] = grid_[b]
        m = (F.date >= f"{Y}-01-01") & (F.date <= f"{Y}-12-31"); st[m] = targets[b][m]
    return st, chosen, targets, sims

rows = []; keep = {}
for name, (g, mk) in FAM.items():
    t0 = time.time(); targets = sims = None
    for obj in ["sharpe_calmar", "cagr_sharpe", "cagr"]:
        st, ch, targets, sims = walk_forward(g, mk, obj, targets, sims)
        sim = simulate(F, st, P, *OOS); m = metrics(sim.equity)
        yr = {f"y{Y}": sim.equity[str(Y)].iloc[-1] / (sim.equity[: f"{Y-1}-12-31"].iloc[-1] if Y > 2021 else 10000) - 1 for Y in YEARS}
        rows.append(dict(family=name, objective=obj, final=m["final"], cagr=m["cagr"], maxdd=m["maxdd"], sharpe=m["sharpe"], calmar=m["calmar"], worst_month=m["worst_month"],
                         trades=sim.attrs["n_trades"], avg_exp=sim.exposure.mean(), halts=len(sim.attrs["halts"]), n_param_sets=len({json.dumps(v, sort_keys=True) for v in ch.values()}), **yr))
        keep[(name, obj)] = (st, ch)
    print(f"  {name}: {len(g)} configs {time.time()-t0:.0f}s", flush=True)

R = pd.DataFrame(rows); R["pass"] = R.maxdd > DD_LIMIT
pd.set_option("display.width", 250)
S = R.copy()
for c in ["cagr", "maxdd", "worst_month", "avg_exp"] + [f"y{Y}" for Y in YEARS]: S[c] = (S[c] * 100).round(1)
S["final"] = S.final.round(0); S["sharpe"] = S.sharpe.round(2); S["calmar"] = S.calmar.round(2)
print("\nOOS 2021-2026 walk-forward — by selection objective")
print(S.sort_values(["pass", "cagr"], ascending=False)[["family", "objective", "pass", "final", "cagr", "maxdd", "sharpe", "calmar", "worst_month", "trades", "avg_exp", "halts", "n_param_sets"] + [f"y{Y}" for Y in YEARS]].to_string(index=False))
R.to_csv("v2b_results.csv", index=False)
best = R[R["pass"]].sort_values("cagr", ascending=False).iloc[0]
print("\nBEST passing (by OOS CAGR):", best.family, best.objective)
st, ch = keep[(best.family, best.objective)]
for y, p in ch.items(): print("   ", y, p)
json.dump(dict(family=best.family, objective=best.objective, params_by_year={str(k): v for k, v in ch.items()}), open("v2b_best.json", "w"), indent=1, ensure_ascii=False)
# also dump the F2w robust choice for comparison
st2, ch2 = keep[("F2w 连续趋势(宽域)", "sharpe_calmar")]
print("\nF2w robust-objective params:"); [print("   ", y, p) for y, p in ch2.items()]
