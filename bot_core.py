"""Core strategy engine (GitHub Actions version) — HYPE 15m/1h breakouts + BTC/ETH/SOL Donchian daily.
Paper mode. State persisted via git commit of bot_state.json."""
import json, os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

STATE_FILE = os.environ.get("STATE_FILE", "bot_state.json")

CAPITAL_INR = float(os.environ.get("CAPITAL_INR", 1000))
RISK_INR = float(os.environ.get("RISK_INR", 50))
USDINR = float(os.environ.get("USDINR", 88.0))
MAX_LEV = 3
MAX_ATTEMPTS_WEEK = 6

HYPE_CONFIGS = {"15m": dict(vol_mult=1.5, rr2=4.0, lookback=48),
                "1h":  dict(vol_mult=3.0, rr2=5.0, lookback=48)}
MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
BYBIT_KLINE = "https://api.bybit.com/v5/market/kline"

def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(os.path.join(os.path.dirname(STATE_FILE), "bot.log"), "a") as f:
        f.write(line + "\n")

def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"positions": [], "trades": [], "attempts": 0, "week": None}

def save_state(s): json.dump(s, open(STATE_FILE, "w"), indent=1)

def fetch_candles(symbol, interval_min, limit=250):
    url = f"{BYBIT_KLINE}?category=linear&symbol={symbol}&interval={interval_min}&limit={limit}"
    d = json.loads(urlopen(Request(url, headers={"User-Agent": "b"}), timeout=20).read())
    rows = sorted(({"time": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                   for r in d["result"]["list"]), key=lambda x: x["time"])
    return rows

def ema_series(cl, n):
    out=[None]*len(cl)
    if len(cl)<n: return out
    e=sum(cl[:n])/n; out[n-1]=e; k=2/(n+1)
    for i in range(n,len(cl)): e=cl[i]*k+e*(1-k); out[i]=e
    return out

def atr(c,i,n=14):
    if i<n+1: return None
    trs=[max(c[j]["high"]-c[j]["low"],abs(c[j]["high"]-c[j-1]["close"]),abs(c[j]["low"]-c[j-1]["close"])) for j in range(i-n+1,i+1)]
    return sum(trs)/len(trs)

def hype_signal(c,cfg):
    if len(c)<210: return None
    closes=[x["close"] for x in c]; i=len(c)-2
    e50,e200=ema_series(closes[:i+1],50)[-1],ema_series(closes[:i+1],200)[-1]
    px_prev,px=closes[-2],closes[-1]
    if not(e50 and e200 and px>e50>e200): return None
    va=sum(x["volume"] for x in c[i-20:i])/20
    if c[i]["volume"]<va*cfg["vol_mult"]: return None
    lvl=max(x["high"] for x in c[i-cfg["lookback"]:i])
    if px_prev<=lvl<px:
        a=atr(c,i) or px*.03; sd=max(a*1.2,px*.02)
        return {"entry":px,"sl":px-sd,"tp1":px+sd*1.5,"tp2":px+sd*cfg["rr2"],"risk_frac":sd/px}
    return None

def donchian_signal(c):
    if len(c)<110: return None
    closes=[x["close"] for x in c[:-1]]; i=len(closes)-1
    sma100=sum(closes[i-99:i+1])/100
    px,prev=closes[i],closes[i-1]
    hi20=max(x["high"] for x in c[i-20:i]); lo10=min(x["low"] for x in c[i-10:i+1])
    rng=(hi20-lo10)/2
    if prev<=hi20<px and px>sma100 and rng>0:
        return {"entry":px,"sl":px-rng,"tp":px+rng*3,
                "exit_sma":sum(closes[i-19:i+1])/20,"risk_frac":rng/px}
    return None

# ---- alerts shim: telegram_alerts optional ----
class _Alerts:
    def trade_open(self,strat,symbol,entry,sl,tp,size_inr):
        try:
            import telegram_alerts as ta; ta.trade_open(strat,symbol,entry,sl,tp,size_inr)
        except Exception: log(f"[alert] OPEN {strat} {symbol} entry={entry} sl={sl} tp={tp}")
    def trade_close(self,strat,symbol,reason,pnl_inr):
        try:
            import telegram_alerts as ta; ta.trade_close(strat,symbol,reason,pnl_inr)
        except Exception: log(f"[alert] CLOSE {strat} {symbol} {reason} pnl={pnl_inr}")
alerts=_Alerts()

def tick():
    state=load_state()
    week=datetime.now(timezone.utc).isocalendar()[1]
    if state.get("week")!=week: state["week"],state["attempts"]=week,0

    # --- manage HYPE positions ---
    for pos in state["positions"][:]:
        if not str(pos.get("strat","")).startswith("hype_"): continue
        iv="60" if pos["strat"]=="hype_1h" else "15"
        c=fetch_candles("HYPEUSDT",iv); cur=c[-1]
        if cur["low"]<=pos["sl"] and not pos.get("tp1_hit"):
            state["trades"].append({**pos,"closed_at":cur["time"],"reason":"stop","gross_inr":-RISK_INR})
            alerts.trade_close(pos["strat"],"HYPE","stop loss",-RISK_INR)
            state["positions"].remove(pos); save_state(state); continue
        if not pos.get("tp1_hit") and cur["high"]>=pos["tp1"]:
            pos["tp1_hit"]=True; pos["sl"]=pos["entry"]; save_state(state)
            log(f"TP1 hit [{pos['strat']}] stop->BE")
            alerts.trade_open(f"{pos['strat']} TP1 booked","HYPE",pos["tp1"],pos["entry"],pos.get("tp2",0),RISK_INR*0.75)
        if pos.get("tp1_hit") and cur["high"]>=pos["tp2"]:
            g=RISK_INR*pos.get("rr2",4)/2
            state["trades"].append({**pos,"closed_at":cur["time"],"reason":"target","gross_inr":g})
            alerts.trade_close(pos["strat"],"HYPE","TP2 target",g)
            state["positions"].remove(pos); save_state(state); continue
        if pos.get("tp1_hit") and cur["low"]<=pos["entry"]:
            state["trades"].append({**pos,"closed_at":cur["time"],"reason":"breakeven","gross_inr":0})
            alerts.trade_close(pos["strat"],"HYPE","breakeven",0)
            state["positions"].remove(pos); save_state(state)

    # --- entries: HYPE ---
    active_tfs={p.get("tf") for p in state["positions"]}
    for tf,cfg in HYPE_CONFIGS.items():
        if tf in active_tfs or state["attempts"]>=MAX_ATTEMPTS_WEEK: continue
        iv="60" if tf=="1h" else "15"
        sig=hype_signal(fetch_candles("HYPEUSDT",iv),cfg)
        if sig:
            notional=RISK_INR/USDINR/sig["risk_frac"]
            pos={"strat":f"hype_{tf}","tf":tf,**sig,"rr2":cfg["rr2"],
                 "notional_usd":round(notional,2),"leverage":MAX_LEV,
                 "opened_at":datetime.now(timezone.utc).isoformat()}
            state["positions"].append(pos); state["attempts"]+=1
            alerts.trade_open(f"HYPE {tf}",f"HYPE @{notional:.1f}u",sig["entry"],sig["sl"],sig["tp2"],notional*USDINR)
            log(f"OPEN [{tf}] entry={sig['entry']:.4f}")

    # --- manage + enter majors (Donchian daily) ---
    have={p.get("symbol") for p in state["positions"] if p.get("strat")=="donchian_daily"}
    for sym in MAJORS:
        for pos in state["positions"][:]:
            if pos.get("symbol")!=sym or pos.get("strat")!="donchian_daily": continue
            c=fetch_candles(sym,"D"); today=c[-1]
            if today["low"]<=pos["sl"]:
                state["trades"].append({**pos,"closed_at":today["time"],"reason":"stop","gross_inr":-RISK_INR})
                alerts.trade_close("Donchian-20",sym.replace("USDT",""),"stop loss",-RISK_INR)
                state["positions"].remove(pos); save_state(state)
            elif today["high"]>=pos["tp"]:
                g=RISK_INR*3
                state["trades"].append({**pos,"closed_at":today["time"],"reason":"target","gross_inr":g})
                alerts.trade_close("Donchian-20",sym.replace("USDT",""),"3R target",g)
                state["positions"].remove(pos); save_state(state)
            elif today["close"]<pos["exit_sma"]*0.99:
                pnl=(today["close"]-pos["entry"])/pos["entry"]/pos["risk_frac"]*RISK_INR
                state["trades"].append({**pos,"closed_at":today["time"],"reason":"trend_exit","gross_inr":round(pnl,2)})
                alerts.trade_close("Donchian-20",sym.replace("USDT",""),"SMA trend exit",pnl)
                state["positions"].remove(pos); save_state(state)
        if sym in have: continue
        sig=donchian_signal(fetch_candles(sym,"D"))
        if sig:
            notional=RISK_INR/USDINR/sig["risk_frac"]
            pos={"strat":"donchian_daily","symbol":sym,**sig,
                 "notional_usd":round(notional,2),"leverage":MAX_LEV,
                 "opened_at":datetime.now(timezone.utc).isoformat()}
            state["positions"].append(pos)
            alerts.trade_open("Donchian-20 Daily",sym.replace("USDT",""),sig["entry"],sig["sl"],sig["tp"],notional*USDINR)
            log(f"OPEN [donchian {sym}]")
    save_state(state)
    return state
