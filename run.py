"""FinBot strategy runner — GitHub Actions version.
Runs the full cycle once per invocation; state persisted via git commit.
Telegram alerts via TELEGRAM_TOKEN / TELEGRAM_CHAT_ID env (repo secrets)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import bot_core
import telegram_alerts as alerts

def main():
    state = bot_core.tick(alerts)
    # persist state back to repo
    with open(bot_core.STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)
    print("cycle complete:", len(state.get("positions", [])), "open,", len(state.get("trades", [])), "closed")

if __name__ == "__main__":
    main()
