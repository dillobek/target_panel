"""AI tahlilchi: reklama ma'lumotlarini Claude'ga berib, tuzilgan tahlil va javob oladi."""
import json
import logging

from . import settings

log = logging.getLogger("ai")

ANALYSIS_SYSTEM = """Sen 8 yillik tajribali Meta Ads targetologisan va O'zbekiston bozorini yaxshi bilasan.
Senga bitta mijozning reklama ma'lumotlari JSON ko'rinishida beriladi: kunlik raqamlar (14 kungacha),
kampaniyalar, reklamalar, joylashuvlar, yosh/jins kesimi (7 kun) va avtomatik qoidalar topgan signallar.

Vazifang: targetologga amaliy tahlil berish.
- Lid/natija narxi qayerda va nega qimmatlashganini top (qaysi kampaniya, reklama, joylashuv, segment).
- Kreativ charchashi (frequency oshishi + CTR tushishi), natijasiz sarf, past CTR, qimmat CPM,
  byudjetning noto'g'ri taqsimlanishi kabi muammolarni ko'rsat.
- Eng yaxshi ishlayotgan reklama/segmentlarni ham ko'rsat (byudjetni qayerga ko'chirish mumkin).
- Har bir tavsiya aniq va bajariladigan bo'lsin ("X reklamani o'chiring", "Y segmentga byudjetni 30% oshiring").
- Faqat berilgan raqamlarga tayan, raqam o'ylab topma. Ma'lumot kam bo'lsa (masalan 3 kundan kam yoki
  sarf juda kichik), xulosani ehtiyotkor qil va shuni ayt.
- Hamma matn o'zbek tilida (lotin), qisqa va aniq.

Javobni FAQAT quyidagi JSON shaklida qaytar, boshqa hech narsa yozma:
{
  "holat": "yaxshi" | "o'rtacha" | "yomon",
  "xulosa": "2-3 gaplik umumiy xulosa",
  "muammolar": [
    {"daraja": "yuqori" | "o'rta" | "past", "joy": "account/kampaniya/reklama nomi",
     "muammo": "nima bo'lyapti (raqam bilan)", "sabab": "ehtimoliy sabab", "tavsiya": "nima qilish kerak"}
  ],
  "imkoniyatlar": ["yaxshi ishlayotgan narsa va undan qanday foydalanish"],
  "qadamlar": ["bugun qilinadigan 1-4 ta aniq qadam, muhimlik tartibida"]
}"""

QUESTION_SYSTEM = """Sen tajribali Meta Ads targetologisan. Senga mijozning reklama ma'lumotlari (JSON) va
targetologning savoli beriladi. Faqat shu ma'lumotlarga tayanib, o'zbek tilida (lotin) aniq va amaliy javob ber.
Raqamlarni keltir, raqam o'ylab topma. Ma'lumotda javob bo'lmasa, shuni ochiq ayt va qanday ma'lumot kerakligini yoz.
Javob 1200 belgidan oshmasin. Markdown yoki HTML ishlatma, oddiy matn va "•" ro'yxatlardan foydalan."""


class AiDisabled(Exception):
    pass


async def _client():
    cfg = await settings.ai_config()
    if not cfg["enabled"]:
        raise AiDisabled("AI tahlil adminkada o'chirilgan")
    if not cfg["api_key"]:
        raise AiDisabled("Anthropic API kaliti kiritilmagan (Adminka → Sozlamalar)")
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=cfg["api_key"]), cfg["model"]


def _text(msg) -> str:
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


def _parse_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def analyse(client_name: str, result_label: str, bundle: dict, findings: list[dict]) -> tuple[dict | None, str | None, str]:
    """Qaytaradi: (ai_json, xom_matn, model). AI o'chiq bo'lsa AiDisabled."""
    client, model = await _client()
    payload = {
        "mijoz": client_name,
        "natija_turi": result_label,
        "malumotlar": bundle,
        "qoidalar_signallari": [{"joy": f.get("account"), "signal": f["text"]} for f in findings],
    }
    msg = await client.messages.create(
        model=model,
        max_tokens=2000,
        system=ANALYSIS_SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}],
    )
    raw = _text(msg)
    return _parse_json(raw), raw, model


async def answer(client_name: str, result_label: str, bundle: dict, question: str) -> tuple[str, str]:
    client, model = await _client()
    payload = {"mijoz": client_name, "natija_turi": result_label, "malumotlar": bundle}
    msg = await client.messages.create(
        model=model,
        max_tokens=1200,
        system=QUESTION_SYSTEM,
        messages=[{
            "role": "user",
            "content": "Ma'lumotlar:\n" + json.dumps(payload, ensure_ascii=False, default=str) + "\n\nSavol: " + question,
        }],
    )
    return _text(msg), model
