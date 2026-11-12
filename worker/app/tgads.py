"""Telegram Ads ulagichi — kabinetdagi API hujjati asosida to'ldiriladi.

Kerakli metodlar (MetaClient bilan bir xil shakl):
  accounts() -> [{"external_id", "name", "currency"}]
  daily_stats(ad_ids, days) -> [{"ad_id", "ad_name", "date", "spend", "impressions", "clicks"}]
Worker bu modulni ulagich tayyor bo'lganda chaqiradi; hozircha TG ulanishlari "API kutilmoqda" holatida turadi.
"""


class TgAdsNotConfigured(Exception):
    pass


class TgAdsClient:
    def __init__(self, token: str):
        self.token = token

    async def accounts(self) -> list[dict]:
        raise TgAdsNotConfigured("Telegram Ads API ulagichi hali qo'shilmagan")

    async def daily_stats(self, ad_ids: list[str], days: int = 7) -> list[dict]:
        raise TgAdsNotConfigured("Telegram Ads API ulagichi hali qo'shilmagan")
