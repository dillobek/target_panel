"""Natijalarni hisoblash: har bir mijozning "natija turi"ga qarab."""

RESULT_ACTIONS = {
    "messaging": ["onsite_conversion.messaging_conversation_started_7d"],
    "lead_form": ["lead", "onsite_conversion.lead_grouped"],
    "lead_site": ["offsite_conversion.fb_pixel_lead"],
    "purchase": ["offsite_conversion.fb_pixel_purchase", "purchase"],
}

RESULT_LABEL = {
    "messaging": "Yozishmalar",
    "lead_form": "Lidlar",
    "lead_site": "Lidlar (sayt)",
    "purchase": "Xaridlar",
}


def results_from_actions(actions, result_type: str) -> int:
    wanted = RESULT_ACTIONS.get(result_type, [])
    by_type = {a.get("action_type"): a.get("value") for a in actions or []}
    for t in wanted:  # birinchi topilgan turni olamiz (ikki marta sanamaslik uchun)
        if t in by_type:
            try:
                return int(float(by_type[t]))
            except (TypeError, ValueError):
                return 0
    return 0


def cost_per(spend: float, results: int) -> float | None:
    return round(spend / results, 2) if results else None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return round((new - old) / old * 100, 1)


def aggregate(rows: list[dict], result_type: str) -> dict:
    """Bir nechta insights_daily qatorini (account/kun) yig'adi."""
    spend = sum(float(r["spend"] or 0) for r in rows)
    impressions = sum(int(r["impressions"] or 0) for r in rows)
    clicks = sum(int(r["clicks"] or 0) for r in rows)
    reach = sum(int(r["reach"] or 0) for r in rows)
    results = sum(results_from_actions(r["actions"], result_type) for r in rows)
    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "reach": reach,
        "results": results,
        "cpr": cost_per(spend, results),
        "ctr": round(clicks / impressions * 100, 2) if impressions else 0.0,
        "cpm": round(spend / impressions * 1000, 2) if impressions else 0.0,
    }
