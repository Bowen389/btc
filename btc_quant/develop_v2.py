"""V2 development: anchored walk-forward over 6 strategy families + ML + ensemble.
For every test year Y in 2021..2026, parameters are chosen ONLY on 2019..Y-1 (constraint: train MaxDD > -25%,
objective rank(Sharpe)+rank(Calmar)); the year Y is then traded with those parameters. Stitched 2021-2026 = pure out-of-sample."""
import json, time, sys
import numpy as np, pandas as pd
from features import build_features
from strategy import DEFAULT
from backtest import simulate, metrics
from strategy_v2 import FAMILIES, ml_walk_forward

CAPS = ((0.10, 0.75), (0.15, 0.50), (0.20, 0.25), (0.25, 0.0))
P = dict(DEFAULT, dd_caps=CAPS, rebal_threshold=0.10, rearm_score=6)
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
OOS = ("2021-01-01", "2026-12-31")
DD_LIMIT = -0.25

raw = pd.read_csv("btc_daily.csv", parse_dates=["date"])
F = build_features(raw)


def select(cands):
    ok = [(i, m) for i, m in cands if m["maxdd"] > DD_LIMIT]
    if not ok:  # nothing satisfies -> take the least-drawdown decile
        ok = sorted(cands, key=lambda x: x[1]["maxdd"], reverse=True)[:max(1, len(cands) // 10)]
    df = pd.DataFrame({i: m for i, m in ok}).T
    return int((df.sharpe.rank() + df.calmar.rank()).idxmax())


def walk_forward(name, grid_, make):
    t0 = time.time()
    targets = [make(F, p) for p in grid_]
    sims = [simulate(F, t, P, "2019-01-01", "2026-12-31") for t in targets]   # anchored windows are prefixes of one path
    stitched = pd.Series(0.0, index=F.index); chosen = {}
    for Y in YEARS:
        cands = [(i, metrics(s.equity[: f"{Y-1}-12-31"])) for i, s in enumerate(sims)]
        b = select(cands); chosen[Y] = grid_[b]
        m = (F.date >= f"{Y}-01-01") & (F.date <= f"{Y}-12-31")
        stitched[m] = targets[b][m]
    print(f"  {name}: {len(grid_)} configs, {time.time()-t0:.0f}s", flush=True)
    return stitched, chosen


def report(name, target, chosen=None):
    sim = simulate(F, target, P, *OOS); m = metrics(sim.equity)
    yr = {Y: sim.equity[str(Y)].iloc[-1] / (sim.equity[: f"{Y-1}-12-31"].iloc[-1] if Y > 2021 else 10000) - 1 for Y in YEARS}
    return dict(name=name, final=m["final"], cagr=m["cagr"], maxdd=m["maxdd"], sharpe=m["sharpe"], calmar=m["calmar"], worst_month=m["worst_month"],
                trades=sim.attrs["n_trades"], avg_exp=sim.exposure.mean(), halts=len(sim.attrs["halts"]), **{f"y{Y}": v for Y, v in yr.items()}), sim, chosen


results = []; stitched_targets = {}; chosen_all = {}
print("Walk-forward over families ...", flush=True)
for name, (g, mk) in FAMILIES.items():
    tgt, ch = walk_forward(name, g, mk); stitched_targets[name] = tgt; chosen_all[name] = ch
    results.append(report(name, tgt, ch)[0])

print("ML walk-forward (retrain every 6 months) ...", flush=True)
for mname, label in [("hgb", "F5a ML梯度提升(10日方向)"), ("logit", "F5b ML逻辑回归(10日方向)")]:
    t0 = time.time(); tgt, prob = ml_walk_forward(F, mname); stitched_targets[label] = tgt
    results.append(report(label, tgt)[0]); print(f"  {label}: {time.time()-t0:.0f}s", flush=True)
    # directional accuracy of the model itself (info only)
    ok = prob.notna() & F.fwd10.notna()
    acc = ((prob[ok] > 0.5) == (F.fwd10[ok] > 0)).mean(); print(f"     OOS hit-rate P(10d up): {acc*100:.1f}%  (base rate {(F.fwd10[ok]>0).mean()*100:.1f}%)")

# ensembles (pre-specified, equal weight)
ens_all = pd.concat(stitched_targets.values(), axis=1).mean(axis=1); ens_all = (np.round(ens_all / 0.05) * 0.05)
stitched_targets["F7 全家族等权集成"] = ens_all; results.append(report("F7 全家族等权集成", ens_all)[0])
rule_names = [n for n in stitched_targets if n.startswith(("F1", "F2", "F3", "F4", "F6"))]
ens_rule = (np.round(pd.concat([stitched_targets[n] for n in rule_names], axis=1).mean(axis=1) / 0.05) * 0.05)
stitched_targets["F8 规则家族集成(无ML)"] = ens_rule; results.append(report("F8 规则家族集成(无ML)", ens_rule)[0])

# benchmark: buy & hold with the same circuit breaker, and plain B&H
one = pd.Series(1.0, index=F.index)
results.append(report("买入持有+同样熔断", one)[0])
sim_bh = simulate(F, one, P, *OOS, use_caps=False); mb = metrics(sim_bh.equity)
results.append(dict(name="买入持有(无熔断)", final=mb["final"], cagr=mb["cagr"], maxdd=mb["maxdd"], sharpe=mb["sharpe"], calmar=mb["calmar"], worst_month=mb["worst_month"], trades=1, avg_exp=1.0, halts=0,
                    **{f"y{Y}": sim_bh.equity[str(Y)].iloc[-1] / (sim_bh.equity[: f"{Y-1}-12-31"].iloc[-1] if Y > 2021 else 10000) - 1 for Y in YEARS}))

R = pd.DataFrame(results)
R["pass"] = R.maxdd > DD_LIMIT
R = R.sort_values(["pass", "sharpe"], ascending=False)
pd.set_option("display.width", 250)
print("\n" + "=" * 150)
print("OUT-OF-SAMPLE 2021-01-01 -> 2026-09-26 (walk-forward, params re-selected each year on prior data only; $10k start; fee 0.2%/side; circuit-breaker ON)")
print("=" * 150)
show = R.copy()
for c in ["cagr", "maxdd", "worst_month", "avg_exp"] + [f"y{Y}" for Y in YEARS]: show[c] = (show[c] * 100).round(1)
show["final"] = show["final"].round(0)
print(show[["name", "pass", "final", "cagr", "maxdd", "sharpe", "calmar", "worst_month", "trades", "avg_exp", "halts"] + [f"y{Y}" for Y in YEARS]].to_string(index=False))
R.to_csv("v2_results.csv", index=False)
json.dump({k: {str(y): v for y, v in ch.items()} for k, ch in chosen_all.items()}, open("v2_chosen_params.json", "w"), indent=1, ensure_ascii=False, default=str)
pd.DataFrame(stitched_targets).assign(date=F.date.values).to_csv("v2_targets.csv", index=False)

print("\nChosen params per test-year (stability check):")
for k, ch in chosen_all.items():
    print(f"  {k}")
    for y, p in ch.items(): print(f"     {y}: {p}")
