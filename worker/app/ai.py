"""Ixtiyoriy AI tahlilchi (ANTHROPIC_API_KEY bo'lsa ishlaydi)."""
import json
import logging

from .config import AI_MODEL, ANTHROPIC_API_KEY

log = logging.getLogger("ai")

SYSTEM = (
    "Sen tajribali Meta Ads targetologisan. Senga reklama accountlarining 7 kunlik raqamlari va avtomatik "
    "topilgan muammolar beriladi. O'zbek tilida, qisqa va amaliy xulosa yoz: 1) asosiy muammo va ehtimoliy "
    "sababi, 2) aniq 2-4 ta qadam (nimani o'zgartirish kerak). Faqat berilgan raqamlarga tayan, raqam "
    "o'ylab topma. Ma'lumot kam bo'lsa, shuni ayt. 900 belgidan oshirma. HTML yoki markdown ishlatma."
)


async def explain(client_name: str, summary: str, findings: list[dict]) -> str | None:
    if not ANTHROPIC_API_KEY or not summary:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        payload = {
            "mijoz": client_name,
            "raqamlar": summary,
            "topilgan_muammolar": [{"account": f.get("account"), "muammo": f["text"]} for f in findings],
        }
        msg = await client.messages.create(
            model=AI_MODEL,
            max_tokens=700,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip() or None
    except Exception as ex:  # noqa: BLE001
        log.warning("AI tahlil ishlamadi: %s", ex)
        return None
