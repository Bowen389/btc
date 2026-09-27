#!/usr/bin/env python3
"""
每日操作指令生成器（BTC 现货 / 只做多 / 日线）—— V2 规则：F2 连续趋势强度 + 目标波动 40% + 回撤熔断
用法：
  python3 daily.py                          # 拉最新数据 -> 输出今日操作
  python3 daily.py --auto-execute           # 同上，并按收盘价把建议交易直接记入账本（GitHub Action 模式）
  python3 daily.py --init 10000             # 初始化账户：现金 10000 美元，BTC 0
  python3 daily.py --done [--price P]       # 手动模式：记录"我已按建议执行"
  python3 daily.py --record --usd X --price P   # 记录任意一笔实际成交（正数买入，负数卖出）
  python3 daily.py --set --cash C --btc B   # 手动校正持仓
  python3 daily.py --no-fetch               # 不联网，用本地 btc_daily.csv
输出：signal_latest.txt（全文）、signal_latest.json（摘要，用于邮件标题）、signals_log.csv（日志）
"""
import argparse, contextlib, datetime as dt, io, json, os, sys, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
from features import build_features
from strategy import dd_cap
from live import LIVE as P, components, scenario_targets, COMP_NAMES

STATE = "portfolio.json"; LOG = "signals_log.csv"; OUT_TXT = "signal_latest.txt"; OUT_JSON = "signal_latest.json"
HALT_LVL = P["dd_caps"][-1][0]
CST = dt.timezone(dt.timedelta(hours=8))


def load_state():
    if not os.path.exists(STATE):
        sys.exit("未找到 portfolio.json，请先运行: python3 daily.py --init 10000")
    return json.load(open(STATE))


def save_state(s):
    json.dump(s, open(STATE, "w"), indent=2, ensure_ascii=False, default=str)


def fetch(max_wait_min=8):
    """Fetch daily bars; wait (up to max_wait_min) until yesterday's UTC candle is present."""
    import fetch_data
    now = dt.datetime.now(dt.timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    expect = (end - dt.timedelta(days=1)).date()
    deadline = time.time() + max_wait_min * 60
    while True:
        try:
            df = fetch_data.fetch_coinbase(fetch_data.START, end)
        except Exception as e:
            print(f"[warn] coinbase failed ({e}); falling back to bitstamp", file=sys.stderr)
            df = fetch_data.fetch_bitstamp(fetch_data.START, end)
        df = df[df["date"] < pd.Timestamp(end).tz_localize(None)]
        if df["date"].iloc[-1].date() >= expect or time.time() > deadline:
            break
        time.sleep(45)
    df.to_csv("btc_daily.csv", index=False)
    return df, df["date"].iloc[-1].date() < expect


def book_trade(s, usd, price, date, note=""):
    qty = usd / price; fee = abs(usd) * P["fee"]
    s["btc"] += qty; s["cash"] -= usd + fee
    s["trades"].append(dict(date=str(date), side="BUY" if usd > 0 else "SELL", usd=round(usd, 2), price=price, qty=round(qty, 6), fee=round(fee, 2), note=note))
    return qty, fee


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", type=float); ap.add_argument("--done", action="store_true"); ap.add_argument("--price", type=float)
    ap.add_argument("--record", action="store_true"); ap.add_argument("--usd", type=float)
    ap.add_argument("--set", action="store_true"); ap.add_argument("--cash", type=float); ap.add_argument("--btc", type=float)
    ap.add_argument("--no-fetch", action="store_true"); ap.add_argument("--auto-execute", action="store_true")
    a = ap.parse_args()

    if a.init is not None:
        s = dict(start_date=str(dt.datetime.now(CST).date()), start_equity=a.init, cash=a.init, btc=0.0, peak_equity=a.init, halted=False, pending=None, trades=[], rules=f"V2 {P['family']} tv{P['tv']}")
        save_state(s); print(f"账户已初始化：现金 ${a.init:,.0f}，BTC 0。"); return

    s = load_state()
    if a.set:
        if a.cash is not None: s["cash"] = a.cash
        if a.btc is not None: s["btc"] = a.btc
        save_state(s); print(f"已校正：现金 ${s['cash']:,.2f}  BTC {s['btc']:.6f}"); return

    if a.record:
        if a.usd is None or a.price is None: sys.exit("--record 需要 --usd 和 --price")
        qty, fee = book_trade(s, a.usd, a.price, dt.datetime.now(CST).date(), "manual")
        s["pending"] = None; save_state(s)
        print(f"已记录：{'买入' if a.usd>0 else '卖出'} ${abs(a.usd):,.0f} @ ${a.price:,.0f} = {abs(qty):.6f} BTC（手续费 ${fee:.2f}）→ 现金 ${s['cash']:,.2f}  BTC {s['btc']:.6f}"); return

    if a.done:
        pend = s.get("pending")
        if not pend or pend.get("usd", 0) == 0 or pend.get("executed"): sys.exit("没有待执行的建议。")
        price = a.price or pend["price"]; qty, fee = book_trade(s, pend["usd"], price, pend["date"], "done")
        s["pending"] = dict(pend, executed=True); save_state(s)
        print(f"已记录：{'买入' if pend['usd']>0 else '卖出'} ${abs(pend['usd']):,.0f} @ ${price:,.0f} = {abs(qty):.6f} BTC（手续费 ${fee:.2f}）")
        print(f"当前：现金 ${s['cash']:,.2f}  BTC {s['btc']:.6f}  按 ${price:,.0f} 计权益 ${s['cash']+s['btc']*price:,.2f}"); return

    # ---------- signal ----------
    if a.no_fetch:
        raw = pd.read_csv("btc_daily.csv", parse_dates=["date"]); stale = False
    else:
        raw, stale = fetch()
    F = build_features(raw); C = components(F)
    L = F.iloc[-1]; c = C.iloc[-1]; price = float(L.close); sig_date = str(L.date.date())

    equity = s["cash"] + s["btc"] * price
    s["peak_equity"] = max(s.get("peak_equity", equity), equity)
    dd = equity / s["peak_equity"] - 1
    floor_hit = equity <= s["start_equity"] * P["hard_floor"]
    cap = dd_cap(dd, P["dd_caps"])
    if dd <= -HALT_LVL and not s["halted"]:
        s["halted"] = True; s["halt_date"] = sig_date
    if s["halted"] and int(c.score6) >= P["rearm_score"]:
        s["halted"] = False; s["peak_equity"] = equity; dd = 0.0; cap = 1.0; s["rearm_date"] = sig_date
    if s["halted"] or floor_hit: cap = 0.0
    target = min(float(c.target), cap)
    cur = s["btc"] * price / equity if equity > 0 else 0.0
    need = abs(target - cur) >= P["rebal_threshold"] or (target == 0 and s["btc"] > 0) or (cur == 0 and target > 0)
    trade_usd = round(target * equity - s["btc"] * price) if need else 0
    if abs(trade_usd) < 20: trade_usd = 0

    if trade_usd > 0: action, headline = "买入", f"买入 ${trade_usd:,}（{cur*100:.0f}%→{target*100:.0f}%）"
    elif trade_usd < 0: action, headline = "卖出", f"卖出 ${-trade_usd:,}（{cur*100:.0f}%→{target*100:.0f}%）"
    else: action, headline = "持有", f"持有不动（仓位 {cur*100:.0f}%）"
    if floor_hit: headline = "‼ 触及-30%红线，全部卖出并停止"
    elif s["halted"]: headline = f"熔断中，空仓等待 6/6 信号｜{headline}"
    if stale: headline = "⚠数据延迟｜" + headline
    headline += f"｜BTC ${price:,.0f}｜信号日 {sig_date}"

    buf = io.StringIO()
    class Tee:
        def write(self, x): buf.write(x); sys.__stdout__.write(x)
        def flush(self): sys.__stdout__.flush()

    with contextlib.redirect_stdout(Tee()):
        print("=" * 70)
        print(f"  {headline}")
        print(f"  生成时间 {dt.datetime.now(CST).strftime('%Y-%m-%d %H:%M')} 北京时间    规则: {P['family']} / 目标波动 {P['tv']*100:.0f}%")
        if stale: print("  ⚠ 交易所尚未给出昨日完整日 K，本信号基于更早一根 K 线，建议稍后手动重跑一次。")
        print("=" * 70)
        print(f"  账本: 现金 ${s['cash']:,.0f} + BTC {s['btc']:.6f} (≈${s['btc']*price:,.0f})  = 权益 ${equity:,.0f}")
        print(f"  权益高点 ${s['peak_equity']:,.0f}  当前回撤 {dd*100:.1f}%  熔断上限 {cap*100:.0f}%  {'【已熔断，等待趋势分 6/6 重启】' if s['halted'] else ''}")
        print("-" * 70)
        for i, n in enumerate(COMP_NAMES):
            print(f"  {n:<22} z={c[f'z{i+1}']:+5.2f}  → {c[f't{i+1}']:+.2f}")
        print(f"  趋势强度 s = {c.strength:+.3f}（范围 −1~+1）→ 原始仓位 = min(1, 1.5×s) = {c.raw*100:.0f}%")
        print(f"  20日年化波动 {L.vol20*100:.0f}% → 波动缩放 ×{c.vol_scalar:.2f}   |  离散趋势分 {int(c.score6)}/6   RSI14 {L.rsi14:.0f}   ATR14 ${L.atr14:,.0f}")
        print("-" * 70)
        print(f"  目标仓位 {target*100:.0f}%   当前仓位 {cur*100:.0f}%")
        if floor_hit:
            print("  ‼ 账户已触及 -30% 红线：全部卖出并停止，规则已用尽，重新评估后再决定是否继续。")
        if trade_usd > 0:
            print(f"  ▶ 今日操作：买入 ${trade_usd:,}（≈{trade_usd/price:.6f} BTC，占权益 {trade_usd/equity*100:.0f}%），市价或贴近盘口的限价")
        elif trade_usd < 0:
            print(f"  ▶ 今日操作：卖出 ${-trade_usd:,}（≈{-trade_usd/price:.6f} BTC，占权益 {-trade_usd/equity*100:.0f}%），市价或贴近盘口的限价")
        else:
            print("  ▶ 今日操作：持有不动（目标与当前仓位差 <10%，不值得付手续费）")

        # ledger update
        if a.auto_execute and trade_usd != 0:
            qty, fee = book_trade(s, trade_usd, price, sig_date, "auto@close")
            s["pending"] = dict(date=sig_date, usd=trade_usd, target=target, price=price, executed=True, auto=True)
            print(f"  ✔ 已按收盘价 ${price:,.0f} 记入账本（手续费 ${fee:.2f}）。若实际成交差异大，用『校正持仓』流程同步。")
        else:
            s["pending"] = dict(date=sig_date, usd=trade_usd, target=target, price=price, executed=False) if trade_usd != 0 else None
        btc_after = s["btc"] if a.auto_execute else s["btc"] + trade_usd / price
        cash_after = s["cash"] if a.auto_execute else s["cash"] - trade_usd - abs(trade_usd) * P["fee"]
        eq_after = cash_after + btc_after * price
        print(f"  执行后账本应为: 现金 ${cash_after:,.0f}  BTC {btc_after:.6f}  仓位 {btc_after*price/eq_after*100 if eq_after else 0:.0f}%   ← 与交易所余额核对")

        print("-" * 70); print("  明日情景（若明日收盘价为…→ 信号目标仓位；实际还受熔断上限约束）:")
        for _, r in scenario_targets(raw).iterrows():
            eq_s = cash_after + btc_after * r.close; dd_s = eq_s / max(s["peak_equity"], eq_after) - 1
            cap_s = dd_cap(dd_s, P["dd_caps"]); t_s = min(r.target, cap_s)
            cur_s = btc_after * r.close / eq_s if eq_s > 0 else 0
            act = f"卖 ${abs(t_s*eq_s - btc_after*r.close):,.0f}" if cur_s - t_s >= 0.10 else (f"买 ${abs(t_s*eq_s - btc_after*r.close):,.0f}" if t_s - cur_s >= 0.10 else "持有")
            print(f"    {r.move*100:+4.0f}%  ${r.close:>9,.0f}   强度 {r.strength:+.2f}   信号 {r.target*100:>3.0f}%   熔断上限 {cap_s*100:>3.0f}%   → {act}")
        if btc_after > 0:
            print("  账户熔断价位（收盘价）:")
            for lvl, cp in P["dd_caps"]:
                eq_lvl = max(s["peak_equity"], eq_after) * (1 - lvl); px_lvl = (eq_lvl - cash_after) / btc_after
                print(f"    权益回撤 {lvl*100:.0f}%（权益 ${eq_lvl:,.0f} ≈ BTC ${px_lvl:,.0f}）→ 仓位上限 {cp*100:.0f}%")
        print(f"  账户红线：权益 ${s['start_equity']*P['hard_floor']:,.0f}（-30%）绝不跨越")
        print("=" * 70)
        if trade_usd != 0 and not a.auto_execute:
            print(f"  执行后请运行: python3 daily.py --done --price 你的成交价")

    open(OUT_TXT, "w").write(buf.getvalue())
    json.dump(dict(headline=headline, sig_date=sig_date, run_time_cst=dt.datetime.now(CST).isoformat(timespec="minutes"), close=price, action=action, trade_usd=trade_usd,
                   target=target, cur=cur, equity=round(equity, 2), cash_after=round(cash_after, 2), btc_after=round(btc_after, 6), strength=round(float(c.strength), 3),
                   score6=int(c.score6), stale=stale, halted=s["halted"], floor_hit=floor_hit, auto=a.auto_execute), open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
    s["last_eval"] = sig_date; save_state(s)
    row = dict(date=sig_date, close=price, strength=round(float(c.strength), 3), score6=int(c.score6), vol20=round(float(L.vol20), 3), raw_target=float(c.target), cap=cap, target=target,
               equity=round(equity), dd=round(dd, 4), trade_usd=trade_usd, auto=a.auto_execute, stale=stale)
    pd.DataFrame([row]).to_csv(LOG, mode="a", header=not os.path.exists(LOG), index=False)


if __name__ == "__main__":
    main()
