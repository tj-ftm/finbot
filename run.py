"""FinBot strategy runner — GitHub Actions version.
Runs one strategy cycle per invocation; state persisted via git commit.
Telegram alerts via TELEGRAM_TOKEN / TELEGRAM_CHAT_ID repo secrets."""
import json, os
import bot_core

def main():
    state = bot_core.tick()
    with open(bot_core.STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)
    print(f"cycle complete: {len(state.get('positions', []))} open, {len(state.get('trades', []))} closed")

if __name__ == "__main__":
    main()
