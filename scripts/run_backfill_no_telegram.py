"""One-off runner: backfill history without requiring Telegram credentials.

load_config() raises if TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are unset, even
though run_backfill never sends Telegram messages (see CLAUDE.md). This
constructs a Config directly to bypass that for a Telegram-free analysis run.
"""
import sys

from hadar_tracker.backfill import run_backfill
from hadar_tracker.config import Config

days = int(sys.argv[1]) if len(sys.argv) > 1 else 90

config = Config(
    db_path="data/hadar.sqlite3",
    images_dir="data/images",
    telegram_bot_token="unused",
    telegram_chat_id="unused",
    user_id=5609,
    forum_id=1,
)

sys.exit(run_backfill(config=config, days=days))
