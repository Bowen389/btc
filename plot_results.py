import json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from features import build_features
from strategy import raw_target
from backtest import simulate, metrics

raw = pd.read_csv("btc_daily.csv", parse_dates=["date"])
F = build_features(raw)
cp = json.load(open("chosen_params.json"))
p = dict(cp, map_={int(k): v for k, v in cp["map_"].items()}, dd_caps=tuple(tuple(x) for x in cp["dd_caps"]))
tg = raw_target(F, p).target
sim = simulate(F, tg, p, "2019-01-01", "2026-12-31")
px = F.set_index("date").close.reindex(sim.index)
bh = px / px.iloc[0] * 10_000

fig, ax = plt.subplots(3, 1, figsize=(13, 11), sharex=True, gridspec_kw={"height_ratios": [3, 1.3, 1]})
ax[0].plot(bh.index, bh, color="grey", lw=1, label=f"Buy & Hold  (final ${bh.iloc[-1]:,.0f}, MaxDD {((bh/bh.cummax()-1).min())*100:.0f}%)")
ax[0].plot(sim.index, sim.equity, color="tab:blue", lw=1.6, label=f"Strategy  (final ${sim.equity.iloc[-1]:,.0f}, MaxDD {((sim.equity/sim.equity.cummax()-1).min())*100:.0f}%)")
ax[0].axvspan(pd.Timestamp("2023-01-01"), sim.index[-1], color="green", alpha=0.06)
ax[0].text(pd.Timestamp("2020-06-01"), 200_000, "IN-SAMPLE (parameter selection)", fontsize=10, color="dimgray")
ax[0].text(pd.Timestamp("2023-06-01"), 200_000, "OUT-OF-SAMPLE (untouched)", fontsize=10, color="green")
ax[0].set_yscale("log"); ax[0].set_ylabel("Equity (USD, log)"); ax[0].legend(loc="upper left"); ax[0].grid(alpha=0.3)
ax[0].set_title("BTC-USD daily trend/vol-targeted strategy vs Buy&Hold — $10,000 start, fee 0.2%/side, drawdown circuit-breaker ON")
dd_s = sim.equity / sim.equity.cummax() - 1; dd_b = bh / bh.cummax() - 1
ax[1].fill_between(dd_b.index, dd_b * 100, 0, color="grey", alpha=0.4, label="Buy&Hold drawdown")
ax[1].fill_between(dd_s.index, dd_s * 100, 0, color="tab:blue", alpha=0.6, label="Strategy drawdown")
ax[1].axhline(-30, color="red", ls="--", lw=1, label="-30% hard limit"); ax[1].set_ylabel("Drawdown %"); ax[1].legend(loc="lower left"); ax[1].grid(alpha=0.3)
ax[2].fill_between(sim.index, sim.exposure * 100, 0, color="tab:orange", alpha=0.7, label="BTC exposure % of equity")
ax[2].plot(sim.index, sim.cap * 100, color="red", lw=0.8, alpha=0.7, label="circuit-breaker cap")
ax[2].set_ylabel("Exposure %"); ax[2].set_ylim(0, 105); ax[2].legend(loc="upper left"); ax[2].grid(alpha=0.3)
plt.tight_layout(); plt.savefig("backtest_chart.png", dpi=110)
print("saved backtest_chart.png")
