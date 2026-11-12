import os
from zoneinfo import ZoneInfo

DATABASE_URL = os.environ.get("DATABASE_URL", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID") or 0)
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
META_API_VERSION = os.environ.get("META_API_VERSION") or "v26.0"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL") or "claude-sonnet-5-5"
TZ = ZoneInfo(os.environ.get("TZ") or "Asia/Tashkent")

WEEKLY_REPORT_TIME = "10:00"   # dushanba
DIAGNOSTICS_TIME = "08:30"     # har kuni, sizga
