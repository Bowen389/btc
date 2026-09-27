import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from features import build_features
from strategy import DEFAULT
from backtest import simulate, metrics
from live import LIVE, components
from strategy_v2 import f1_make
raw = pd.read_csv("btc_daily.csv", parse_dates=["date"]); F = build_features(raw)
P = dict(DEFAULT, dd_caps=LIVE["dd_caps"], rebal_threshold=0.10, rearm_score=6)
t2 = components(F).target
sim = simulate(F, t2, P, "2019-01-01", "2026-12-31")
t1 = f1_make(F, dict(map="steep", boost=False, guard=False, tv=0.4)); sim1 = simulate(F, t1, P, "2019-01-01", "2026-12-31")
px = F.set_index("date").close.reindex(sim.index); bh = px / px.iloc[0] * 10_000
oos = simulate(F, t2, P, "2021-01-01", "2026-12-31"); mo = metrics(oos.equity)
fig, ax = plt.subplots(3, 1, figsize=(13, 11), sharex=True, gridspec_kw={"height_ratios": [3, 1.3, 1]})
ax[0].plot(bh.index, bh, color="grey", lw=1, label=f"Buy & Hold  (final ${bh.iloc[-1]:,.0f}, MaxDD {((bh/bh.cummax()-1).min())*100:.0f}%)")
ax[0].plot(sim1.index, sim1.equity, color="tab:orange", lw=1.1, alpha=0.8, label=f"V1 discrete score (final ${sim1.equity.iloc[-1]:,.0f}, MaxDD {((sim1.equity/sim1.equity.cummax()-1).min())*100:.0f}%)")
ax[0].plot(sim.index, sim.equity, color="tab:blue", lw=1.8, label=f"V2 FINAL continuous trend, vol-target 40% (final ${sim.equity.iloc[-1]:,.0f}, MaxDD {((sim.equity/sim.equity.cummax()-1).min())*100:.0f}%)")
ax[0].axvspan(pd.Timestamp("2021-01-01"), sim.index[-1], color="green", alpha=0.06)
ax[0].text(pd.Timestamp("2019-03-01"), 150_000, "2019-20: first training window", fontsize=9, color="dimgray")
ax[0].text(pd.Timestamp("2021-03-01"), 150_000, f"2021-26 WALK-FORWARD OUT-OF-SAMPLE: V2 CAGR {mo['cagr']*100:.1f}%  MaxDD {mo['maxdd']*100:.1f}%  Sharpe {mo['sharpe']:.2f}", fontsize=9, color="green")
ax[0].set_yscale("log"); ax[0].set_ylabel("Equity (USD, log)"); ax[0].legend(loc="upper left", fontsize=9); ax[0].grid(alpha=0.3)
ax[0].set_title("BTC-USD daily — V2 final strategy vs V1 vs Buy&Hold ($10,000 start, fee 0.2%/side, circuit-breaker ON)")
for s_, col, lab in [(bh, "grey", "Buy&Hold"), (sim1.equity, "tab:orange", "V1"), (sim.equity, "tab:blue", "V2 final")]:
    d = s_ / s_.cummax() - 1; ax[1].fill_between(d.index, d * 100, 0, color=col, alpha=0.35 if col == "grey" else 0.5, label=f"{lab} drawdown")
ax[1].axhline(-30, color="red", ls="--", lw=1, label="-30% hard limit"); ax[1].axhline(-25, color="red", ls=":", lw=1, label="-25% halt level")
ax[1].set_ylabel("Drawdown %"); ax[1].legend(loc="lower left", fontsize=8, ncol=2); ax[1].grid(alpha=0.3)
ax[2].fill_between(sim.index, sim.exposure * 100, 0, color="tab:blue", alpha=0.6, label="V2 BTC exposure % of equity")
ax[2].plot(sim.index, sim.cap * 100, color="red", lw=0.8, alpha=0.7, label="circuit-breaker cap"); ax[2].set_ylim(0, 105); ax[2].set_ylabel("Exposure %"); ax[2].legend(loc="upper left", fontsize=8); ax[2].grid(alpha=0.3)
plt.tight_layout(); plt.savefig("v2_chart.png", dpi=110); print("saved v2_chart.png")
m = metrics(sim.equity); print("V2 full 2019-26:", {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()})
print("V2 yearly:", {Y: round(sim.equity[str(Y)].iloc[-1] / (sim.equity[:f'{Y-1}-12-31'].iloc[-1] if Y > 2019 else 10000) - 1, 3) for Y in range(2019, 2027)})
print("V2 trades/yr OOS:", oos.attrs["n_trades"] / 5.74, " avg exposure OOS:", round(oos.exposure.mean(), 3))
