"""Telegram alerts (optional — silent no-op if secrets missing)."""
import os, json
from urllib.request import Request, urlopen

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send(msg):
    if not TOKEN or not CHAT_ID:
        print(f"[tg-skip] {msg}")
        return False
    try:
        body = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data=body, method="POST", headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"[tg-err] {e}")
        return False

def trade_open(strat, symbol, entry, sl, tp, size_inr):
    send(f"🟢 <b>POSITION OPENED</b> [{strat}]\n"
         f"<b>{symbol}</b> PERP\n"
         f"Entry: <code>{entry}</code>\n"
         f"SL: <code>{sl}</code> | TP: <code>{tp}</code>\n"
         f"Size: ₹{float(size_inr):,.0f}")

def trade_close(strat, symbol, reason, pnl_inr):
    emoji = "✅" if pnl_inr >= 0 else "🔴"
    net = pnl_inr * 0.7 if pnl_inr > 0 else pnl_inr
    send(f"{emoji} <b>TRADE CLOSED</b> [{strat}]\n"
         f"<b>{symbol}</b> — {reason}\n"
         f"Gross: {'+' if pnl_inr>=0 else ''}₹{pnl_inr:.0f}\n"
         f"After-tax: {'+' if net>=0 else ''}₹{net:.0f}")
