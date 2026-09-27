"""Event-driven daily backtest with fees, rebalance threshold, drawdown circuit-breaker.
Signal at close t -> position held over t+1 return (== execute at t+1 open ~ t close on 24/7 market)."""
import itertools, json, sys
import numpy as np, pandas as pd
from features import build_features
from strategy import DEFAULT, raw_target, dd_cap, trend_score

INIT = 10_000.0


def simulate(F: pd.DataFrame, target: pd.Series, p: dict, start, end, use_caps=True):
    idx = F.index[(F.date >= start) & (F.date <= end)]
    ret = F.ret.values
    tgt = target.values
    eq = INIT; cash = INIT; btc = 0.0; peak = INIT; halted = False
    rows = []
    n_trades = 0; turnover = 0.0; halts = []
    score = trend_score(F).values
    for i in idx[:-1]:
        # --- decision at close of day i ---
        dd = eq / peak - 1
        cap = dd_cap(dd, p["dd_caps"]) if use_caps else 1.0
        if use_caps:
            halt_lvl = p["dd_caps"][-1][0]
            if dd <= -halt_lvl and not halted:
                halted = True; halts.append((F.date[i].date(), round(eq)))
            if halted and score[i] >= p.get("rearm_score", 6):   # re-arm on a fresh strong trend, new campaign
                halted = False; peak = eq
            if halted:
                cap = 0.0
        t = min(tgt[i], cap)
        cur = btc / eq if eq > 0 else 0
        if abs(t - cur) >= p["rebal_threshold"] or (t == 0 and btc > 0) or (cur == 0 and t > 0):
            trade = t * eq - btc
            cost = abs(trade) * p["fee"]
            btc += trade; cash -= trade + cost; eq = btc + cash
            n_trades += 1; turnover += abs(trade)
            exposure_after = btc / eq
        else:
            trade = 0.0; exposure_after = cur
        # --- hold over day i+1 ---
        btc *= (1 + ret[i + 1]); eq = btc + cash; peak = max(peak, eq)
        rows.append((F.date[i + 1], eq, exposure_after, trade, t, cap, halted))
    out = pd.DataFrame(rows, columns=["date", "equity", "exposure", "trade", "target", "cap", "halted"]).set_index("date")
    out.attrs["n_trades"] = n_trades; out.attrs["turnover"] = turnover; out.attrs["halts"] = halts
    return out


def metrics(eqs: pd.Series, price: pd.Series = None):
    r = eqs.pct_change().dropna()
    yrs = (eqs.index[-1] - eqs.index[0]).days / 365.25
    cagr = (eqs.iloc[-1] / eqs.iloc[0]) ** (1 / yrs) - 1
    dd = eqs / eqs.cummax() - 1
    sharpe = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else 0
    neg = r[r < 0]
    sortino = r.mean() / neg.std() * np.sqrt(365) if len(neg) > 1 else 0
    m = eqs.resample("ME").last().pct_change().dropna()
    return dict(final=eqs.iloc[-1], total=eqs.iloc[-1] / eqs.iloc[0] - 1, cagr=cagr, maxdd=dd.min(), sharpe=sharpe, sortino=sortino,
                calmar=cagr / abs(dd.min()) if dd.min() < 0 else np.nan, worst_day=r.min(), worst_month=m.min(), vol=r.std() * np.sqrt(365),
                dd_days=int((dd < 0).sum()))


def fmt(m):
    return (f"final ${m['final']:>9,.0f}  CAGR {m['cagr']*100:>6.1f}%  MaxDD {m['maxdd']*100:>6.1f}%  Sharpe {m['sharpe']:>4.2f}  "
            f"Calmar {m['calmar']:>4.2f}  worstDay {m['worst_day']*100:>6.1f}%  worstMon {m['worst_month']*100:>6.1f}%  vol {m['vol']*100:>4.0f}%")


if __name__ == "__main__":
    raw = pd.read_csv("btc_daily.csv", parse_dates=["date"])
    F = build_features(raw)
    IS = ("2019-01-01", "2022-12-31"); OOS = ("2023-01-01", "2026-12-31"); ALL = ("2019-01-01", "2026-12-31")

    # ---------- benchmarks ----------
    bench = {}
    one = pd.Series(1.0, index=F.index)
    p0 = dict(DEFAULT)
    bench["Buy&Hold"] = one
    bench["SMA200 filter"] = (F.close > F.sma200).astype(float)
    bench["EMA21/55 trend"] = pd.Series(np.where((F.close > F.ema21) & (F.ema21 > F.ema55), 1.0, np.where((F.close < F.ema21) & (F.ema21 < F.ema55), 0.0, np.nan)), index=F.index).ffill().fillna(0)
    # Donchian 20/10 turtle
    pos = np.zeros(len(F)); 
    for i in range(1, len(F)):
        pos[i] = 1.0 if F.brk20_up[i] else (0.0 if F.brk10_dn[i] else pos[i - 1])
    bench["Donchian 20/10"] = pd.Series(pos, index=F.index)
    print("=" * 110); print("BENCHMARKS (no drawdown caps, fee 0.2%/side)"); print("=" * 110)
    for name, tg in bench.items():
        for lbl, (a, b) in {"IS 19-22": IS, "OOS 23-26": OOS, "ALL": ALL}.items():
            sim = simulate(F, tg, p0, a, b, use_caps=False)
            print(f"{name:<16}{lbl:<10}{fmt(metrics(sim.equity))}  trades {sim.attrs['n_trades']}")
        print()

    # ---------- grid search on IS for composite ----------
    print("=" * 110); print("COMPOSITE grid search (selected on IN-SAMPLE 2019-2022 only; caps ON)"); print("=" * 110)
    grid = []
    maps = {
        "steep": {6: 1.0, 5: 0.8, 4: 0.6, 3: 0.3, 2: 0.0, 1: 0.0, 0: 0.0},
        "binary": {6: 1.0, 5: 1.0, 4: 1.0, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
        "linear": {6: 1.0, 5: 0.83, 4: 0.67, 3: 0.5, 2: 0.33, 1: 0.17, 0: 0.0},
        "strict": {6: 1.0, 5: 0.7, 4: 0.4, 3: 0.0, 2: 0.0, 1: 0.0, 0: 0.0},
    }
    caps_sets = {
        "caps30": ((0.15, 0.75), (0.20, 0.50), (0.25, 0.25), (0.30, 0.0)),
        "caps25": ((0.10, 0.75), (0.15, 0.50), (0.20, 0.25), (0.25, 0.0)),
    }
    for tv, mname, boost, guard, cname, rb, rearm in itertools.product([0.30, 0.40, 0.45, 0.50, 9.9], maps.keys(), [True, False], [True, False], caps_sets.keys(), [0.10, 0.15, 0.20], [5, 6]):
        p = dict(DEFAULT, target_vol=tv, map_=maps[mname], breakout_boost=boost, crash_guard=guard, dd_caps=caps_sets[cname], rebal_threshold=rb, rearm_score=rearm)
        tg = raw_target(F, p).target
        s_is = simulate(F, tg, p, *IS); m_is = metrics(s_is.equity)
        s_oos = simulate(F, tg, p, *OOS); m_oos = metrics(s_oos.equity)
        grid.append(dict(tv=tv, map=mname, boost=boost, guard=guard, caps=cname, rb=rb, rearm=rearm, is_cagr=m_is["cagr"], is_dd=m_is["maxdd"], is_sharpe=m_is["sharpe"], is_calmar=m_is["calmar"],
                         oos_cagr=m_oos["cagr"], oos_dd=m_oos["maxdd"], oos_sharpe=m_oos["sharpe"], oos_calmar=m_oos["calmar"], trades_is=s_is.attrs["n_trades"], trades_oos=s_oos.attrs["n_trades"], halts_is=len(s_is.attrs["halts"]), halts_oos=len(s_oos.attrs["halts"])))
    G = pd.DataFrame(grid)
    G["is_score"] = G.is_calmar.rank() + G.is_sharpe.rank() - (G.trades_is / 50.0)   # IS risk-adjusted; mild penalty for trade count
    G.loc[G.is_dd < -0.27, "is_score"] = -1e9        # hard requirement: IS max drawdown must stay above -27% (buffer under the 30% limit)
    G = G.sort_values("is_score", ascending=False)
    G.to_csv("grid_results.csv", index=False)
    pd.set_option("display.width", 200)
    print(G.head(12).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\n... robustness: OOS Sharpe / MaxDD across the whole grid:  median Sharpe %.2f  (min %.2f, max %.2f)  median MaxDD %.1f%%  worst MaxDD %.1f%%" % (
        G.oos_sharpe.median(), G.oos_sharpe.min(), G.oos_sharpe.max(), G.oos_dd.median() * 100, G.oos_dd.min() * 100))
    best = G.iloc[0]
    chosen = dict(DEFAULT, target_vol=float(best.tv), map_=maps[best["map"]], breakout_boost=bool(best.boost), crash_guard=bool(best.guard),
                  dd_caps=caps_sets[best.caps], rebal_threshold=float(best.rb), rearm_score=int(best.rearm))
    json.dump(dict(chosen, map_={str(k): v for k, v in chosen["map_"].items()}, map_name=best["map"], caps_name=best.caps), open("chosen_params.json", "w"), indent=2)
    print("\nCHOSEN (by in-sample only):", best["map"], "target_vol", best.tv, "boost", best.boost, "guard", best.guard, "caps", best.caps, "rebal", best.rb, "rearm", best.rearm)

    # ---------- final evaluation ----------
    print("\n" + "=" * 110); print("FINAL COMPOSITE — full detail"); print("=" * 110)
    tg = raw_target(F, chosen).target
    res = {}
    for lbl, (a, b) in {"IS 19-22": IS, "OOS 23-26": OOS, "ALL 19-26": ALL}.items():
        sim = simulate(F, tg, chosen, a, b); m = metrics(sim.equity); res[lbl] = sim
        print(f"caps ON   {lbl:<10}{fmt(m)}  trades {sim.attrs['n_trades']}  avg exposure {sim.exposure.mean()*100:.0f}%  halted days {int(sim.halted.sum())}  halts {sim.attrs['halts']}")
        sim2 = simulate(F, tg, chosen, a, b, use_caps=False); m2 = metrics(sim2.equity)
        print(f"caps OFF  {lbl:<10}{fmt(m2)}  trades {sim2.attrs['n_trades']}")
    full = res["ALL 19-26"]
    full.to_csv("backtest_equity.csv")
    # yearly table
    y = full.equity.resample("YE").last(); y0 = pd.concat([pd.Series([INIT], index=[full.index[0] - pd.Timedelta(days=1)]), y])
    bh = F.set_index("date").close.reindex(full.index).resample("YE").last(); bh0 = pd.concat([pd.Series([F.set_index("date").close.loc[:full.index[0]].iloc[-1]], index=[full.index[0] - pd.Timedelta(days=1)]), bh])
    print("\nYear-by-year (strategy vs buy&hold):")
    for i in range(1, len(y0)):
        yr = y0.index[i].year
        ddy = (full.equity[str(yr)] / full.equity[str(yr)].cummax() - 1).min()
        print(f"  {yr}: strategy {y0.iloc[i]/y0.iloc[i-1]-1:+7.1%}  (intra-year maxDD {ddy:6.1%})   B&H {bh0.iloc[i]/bh0.iloc[i-1]-1:+7.1%}")
    # Monte-Carlo style stress: bootstrap blocks of OOS daily strategy returns to estimate prob(DD>30%)
    r = full.equity.pct_change().dropna().values
    rng = np.random.default_rng(0); L = 365; B = 20; hits = 0; N = 3000
    for _ in range(N):
        starts = rng.integers(0, len(r) - B, size=L // B + 1)
        path = np.concatenate([r[s:s + B] for s in starts])[:L]
        e = np.cumprod(1 + path); dd = (e / np.maximum.accumulate(e) - 1).min()
        hits += dd <= -0.30
    print(f"\nBlock-bootstrap (3000 x 1-year paths): P(max drawdown >= 30%) = {hits/N*100:.1f}%")
