"""Meta Marketing API mijozi (Graph API)."""
import asyncio
import json
import logging
from urllib.parse import urlencode

import httpx

from .config import META_API_VERSION

log = logging.getLogger("meta")

RATE_LIMIT_CODES = {4, 17, 32, 613, 80000, 80004}
TOKEN_ERROR_CODES = {102, 190}

INSIGHT_FIELDS = "spend,impressions,reach,clicks,ctr,cpm,frequency,actions"


class MetaError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code

    @property
    def is_token_error(self) -> bool:
        return self.code in TOKEN_ERROR_CODES


class MetaClient:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://graph.facebook.com/{META_API_VERSION}"

    async def _request(self, method: str, url: str, **kw) -> dict:
        for attempt in range(4):
            async with httpx.AsyncClient(timeout=90) as c:
                r = await c.request(method, url, **kw)
            data = r.json()
            err = data.get("error") if isinstance(data, dict) else None
            if not err:
                return data
            code = err.get("code")
            if code in RATE_LIMIT_CODES and attempt < 3:
                wait = 30 * (attempt + 1)
                log.warning("Meta limit (%s), %s s kutilyapti", code, wait)
                await asyncio.sleep(wait)
                continue
            raise MetaError(err.get("message", "Meta xatosi"), code)
        raise MetaError("Meta limitdan chiqmadi")

    async def get(self, path: str, params: dict | None = None) -> dict:
        p = dict(params or {}, access_token=self.token)
        return await self._request("GET", f"{self.base}/{path}", params=p)

    async def ad_accounts(self) -> list[dict]:
        fields = "name,account_id,account_status,currency,spend_cap,amount_spent,disable_reason"
        data = await self.get("me/adaccounts", {"fields": fields, "limit": 100})
        rows = list(data.get("data", []))
        nxt = data.get("paging", {}).get("next")
        while nxt:
            page = await self._request("GET", nxt)
            rows += page.get("data", [])
            nxt = page.get("paging", {}).get("next")
        return rows

    async def batch(self, relative_urls: list[str]) -> list[dict | None]:
        """Bir so'rovda 50 tagacha GET. Har bir javob: dict (body) yoki None (xato)."""
        out: list[dict | None] = []
        for i in range(0, len(relative_urls), 50):
            chunk = relative_urls[i : i + 50]
            payload = {
                "access_token": self.token,
                "include_headers": "false",
                "batch": json.dumps([{"method": "GET", "relative_url": u} for u in chunk]),
            }
            resp = await self._request("POST", self.base + "/", data=payload)
            for item in resp if isinstance(resp, list) else []:
                if not item:
                    out.append(None)
                    continue
                try:
                    body = json.loads(item.get("body") or "{}")
                except ValueError:
                    body = {}
                if item.get("code") != 200 or "error" in body:
                    log.warning("Batch xato: %s", body.get("error", {}).get("message"))
                    out.append(None)
                else:
                    out.append(body)
        return out


def insights_url(account_id: str, **params) -> str:
    return f"act_{account_id}/insights?" + urlencode(params)


def minor_to_major(value) -> float | None:
    """Meta spend_cap / amount_spent ni sentlarda beradi."""
    if value in (None, "", "0"):
        return None if value in (None, "") else 0.0
    try:
        return int(value) / 100
    except (TypeError, ValueError):
        return None
