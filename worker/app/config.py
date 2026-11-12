import os
from zoneinfo import ZoneInfo

# Bot tokeni, admin chat va AI kaliti adminkada (settings jadvali) saqlanadi — app/settings.py
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
META_API_VERSION = os.environ.get("META_API_VERSION") or "v26.0"
TZ = ZoneInfo(os.environ.get("TZ") or "Asia/Tashkent")

WEEKLY_REPORT_TIME = "10:00"   # dushanba
