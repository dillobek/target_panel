"""Reklama tahlili: ma'lumot yig'ish, qoidalar signallari va AI tahlili."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from . import ai, db, settings
from .config import TZ
from .crypto import decrypt
from .meta import MetaClient, MetaError, insights_url
from .metrics import RESULT_LABEL, aggregate, cost_per, results_from_actions
from .notify import admin_chat, alert, e, get_rule, send

log = logging.getLogger("diagnostics")

FATIGUE_FREQUENCY = 3.0
LOW_CTR = 0.8


async def _client_accounts(client_id: int):
    return await db.fetch(
        """SELECT a.*, c.token_enc FROM client_sources s
           JOIN ad_accounts a ON a.id = s.ad_account_id AND a.platform = 'meta'
           JOIN connections c ON c.id = a.connection_id AND c.status = 'ok'
           WHERE s.client_id = $1""",
        client_id,
    )


def analyse_account(daily: list[dict], result_type: str, cpr_spike_pct: float, no_result_spend: float) -> list[dict]:
    """Account darajasidagi qoidalar. daily: insights_daily qatorlari (sanasi bo'yicha tartiblangan)."""
    findings: list[dict] = []
    if len(daily) < 2:
        return findings
    last = daily[-1]
    prev = daily[:-1]
    last_agg = aggregate([last], result_type)
    prev_agg = aggregate(prev, result_type)

    if last_agg["cpr"] and prev_agg["cpr"]:
        change = (last_agg["cpr"] - prev_agg["cpr"]) / prev_agg["cpr"] * 100
        if change >= cpr_spike_pct:
            findings.append({
                "type": "cpr_spike", "severity": "high",
                "text": f"Natija narxi {prev_agg['cpr']:.2f} → {last_agg['cpr']:.2f} (+{change:.0f}%) "
                        f"oldingi {len(prev)} kun o'rtachasiga nisbatan",
            })
    if last_agg["spend"] >= no_result_spend and last_agg["results"] == 0:
        findings.append({
            "type": "spend_no_result", "severity": "high",
            "text": f"Kecha {last_agg['spend']:.2f} sarflandi, lekin natija 0",
        })
    week = aggregate(daily, result_type)
    if week["impressions"] > 1000 and week["ctr"] < LOW_CTR:
        findings.append({
            "type": "low_ctr", "severity": "medium",
            "text": f"7 kunlik CTR past: {week['ctr']:.2f}% (kreativ yoki auditoriya mos emas bo'lishi mumkin)",
        })
    return findings


def analyse_ads(ads_7d: list[dict], ads_daily: list[dict], result_type: str) -> list[dict]:
    findings: list[dict] = []
    by_ad: dict[str, list[dict]] = defaultdict(list)
    for r in ads_daily:
        by_ad[r.get("ad_id")].append(r)
    for ad in ads_7d:
        freq = float(ad.get("frequency") or 0)
        days = sorted(by_ad.get(ad.get("ad_id"), []), key=lambda r: r["date_start"])
        if freq >= FATIGUE_FREQUENCY and len(days) >= 5:
            first = [float(d.get("ctr") or 0) for d in days[:3]]
            last = [float(d.get("ctr") or 0) for d in days[-2:]]
            f_avg, l_avg = sum(first) / len(first), sum(last) / len(last)
            if f_avg > 0 and l_avg < f_avg * 0.7:
                findings.append({
                    "type": "fatigue", "severity": "medium",
                    "text": f"“{ad.get('ad_name')}” charchagan: frequency {freq:.1f}, CTR {f_avg:.2f}% → {l_avg:.2f}%",
                })
        spend = float(ad.get("spend") or 0)
        if spend >= 10 and results_from_actions(ad.get("actions"), result_type) == 0:
            findings.append({
                "type": "ad_no_result", "severity": "medium",
                "text": f"“{ad.get('ad_name')}” 7 kunda {spend:.2f} sarfladi, natija 0",
            })
    return findings


def analyse_placements(rows: list[dict], result_type: str) -> list[dict]:
    findings: list[dict] = []
    total_spend = sum(float(r.get("spend") or 0) for r in rows)
    total_res = sum(results_from_actions(r.get("actions"), result_type) for r in rows)
    avg = cost_per(total_spend, total_res)
    for r in rows:
        spend = float(r.get("spend") or 0)
        res = results_from_actions(r.get("actions"), result_type)
        name = r.get("publisher_platform")
        if spend >= 3 and res == 0 and total_res > 0:
            findings.append({"type": "placement", "severity": "medium",
                             "text": f"{name}: {spend:.2f} sarf, natija 0 — bu joylashuvni o'chirishni ko'ring"})
        elif avg and res and spend / res > avg * 2:
            findings.append({"type": "placement", "severity": "low",
                             "text": f"{name}: natija narxi {spend / res:.2f}, o'rtacha {avg:.2f} dan 2 baravar qimmat"})
    return findings


def _m(row: dict, rt: str) -> dict:
    """Bitta insights qatorini AI uchun ixcham ko'rinishga keltiradi."""
    spend = round(float(row.get("spend") or 0), 2)
    res = results_from_actions(row.get("actions"), rt)
    imp = int(row.get("impressions") or 0)
    clicks = int(row.get("clicks") or 0)
    return {
        "sarf": spend, "natija": res, "narx": cost_per(spend, res),
        "ctr": round(clicks / imp * 100, 2) if imp else 0, "cpm": round(spend / imp * 1000, 2) if imp else 0,
        "frequency": round(float(row["frequency"]), 2) if row.get("frequency") else None,
    }


async def collect(client) -> tuple[dict, list[dict]]:
    """Mijozning barcha Meta accountlari bo'yicha ma'lumot to'plami va qoidalar signallari."""
    accounts = await _client_accounts(client["id"])
    rt = client["result_type"]
    spike = float((await get_rule(client["id"], "cpr_spike"))["threshold"] or 30)
    no_res = float((await get_rule(client["id"], "spend_no_result"))["threshold"] or 5)
    end = datetime.now(TZ).date() - timedelta(days=1)
    bundle: dict = {"davr_oxiri": str(end), "accountlar": []}
    findings: list[dict] = []

    for acc in accounts:
        daily14 = [dict(r) for r in await db.fetch(
            "SELECT * FROM insights_daily WHERE ad_account_id=$1 AND date BETWEEN $2 AND $3 ORDER BY date",
            acc["id"], end - timedelta(days=13), end)]
        daily7 = [r for r in daily14 if r["date"] >= end - timedelta(days=6)]
        acc_findings = analyse_account(daily7, rt, spike, no_res)
        item = {
            "account": acc["name"], "valyuta": acc["currency"],
            "kunlik": [{"sana": str(r["date"]), **_m(r, rt)} for r in daily14],
            "jami_7_kun": aggregate(daily7, rt) if daily7 else None,
        }
        try:
            api = MetaClient(decrypt(acc["token_enc"]))
            ext = acc["external_id"]
            camps, ads7, adsd, places, demo = await api.batch([
                insights_url(ext, level="campaign", date_preset="last_7d", limit=100,
                             fields="campaign_name,objective,spend,impressions,clicks,frequency,actions"),
                insights_url(ext, level="ad", date_preset="last_7d", limit=200,
                             fields="ad_id,ad_name,adset_name,campaign_name,spend,impressions,clicks,ctr,frequency,actions"),
                insights_url(ext, level="ad", date_preset="last_7d", time_increment=1, limit=1000,
                             fields="ad_id,ctr,impressions"),
                insights_url(ext, level="account", date_preset="last_7d", breakdowns="publisher_platform",
                             fields="spend,clicks,impressions,actions"),
                insights_url(ext, level="account", date_preset="last_7d", breakdowns="age,gender",
                             fields="spend,clicks,impressions,actions"),
            ])
            camps = (camps or {}).get("data", [])
            ads7 = (ads7 or {}).get("data", [])
            places = (places or {}).get("data", [])
            demo = (demo or {}).get("data", [])
            acc_findings += analyse_ads(ads7, (adsd or {}).get("data", []), rt)
            acc_findings += analyse_placements(places, rt)
            by_spend = lambda rows: sorted(rows, key=lambda r: -float(r.get("spend") or 0))  # noqa: E731
            item["kampaniyalar"] = [{"nomi": r.get("campaign_name"), "maqsad": r.get("objective"), **_m(r, rt)}
                                    for r in by_spend(camps)[:15]]
            item["reklamalar"] = [{"nomi": r.get("ad_name"), "kampaniya": r.get("campaign_name"),
                                   "adset": r.get("adset_name"), **_m(r, rt)} for r in by_spend(ads7)[:25]]
            item["joylashuvlar"] = [{"joy": r.get("publisher_platform"), **_m(r, rt)} for r in by_spend(places)]
            item["yosh_jins"] = [{"yosh": r.get("age"), "jins": r.get("gender"), **_m(r, rt)}
                                 for r in by_spend(demo)[:14]]
        except MetaError as ex:
            log.warning("Tahlil uchun Meta xatosi (%s): %s", acc["name"], ex)
            item["xato"] = f"Batafsil ma'lumot olinmadi: {ex}"
        for f in acc_findings:
            f["account"] = acc["name"]
        findings += acc_findings
        bundle["accountlar"].append(item)
    return bundle, findings


ICON = {"high": "❗", "medium": "⚠️", "low": "ℹ️"}
AI_LEVEL = {"yuqori": "❗", "o'rta": "⚠️", "past": "ℹ️"}
AI_STATE = {"yaxshi": "🟢 yaxshi", "o'rtacha": "🟡 o'rtacha", "yomon": "🔴 yomon"}


def format_analysis(client_name: str, day, findings: list[dict], ai_json: dict | None, ai_text: str | None,
                    ai_error: str | None) -> str:
    lines = [f"🤖 <b>{e(client_name)}</b> — AI tahlil ({day:%d.%m})"]
    if ai_json:
        lines.append(f"Holat: {AI_STATE.get(ai_json.get('holat'), e(ai_json.get('holat', '—')))}")
        if ai_json.get("xulosa"):
            lines.append(e(ai_json["xulosa"]))
        probs = ai_json.get("muammolar") or []
        if probs:
            lines.append("\n<b>Muammolar</b>")
            for i, p in enumerate(probs, 1):
                lines.append(f"{AI_LEVEL.get(p.get('daraja'), '•')} {i}. <i>{e(p.get('joy', ''))}</i>: {e(p.get('muammo', ''))}")
                if p.get("sabab"):
                    lines.append(f"   Sabab: {e(p['sabab'])}")
                if p.get("tavsiya"):
                    lines.append(f"   👉 {e(p['tavsiya'])}")
        if ai_json.get("imkoniyatlar"):
            lines.append("\n<b>💡 Imkoniyatlar</b>")
            lines += [f"• {e(x)}" for x in ai_json["imkoniyatlar"]]
        if ai_json.get("qadamlar"):
            lines.append("\n<b>✅ Bugungi qadamlar</b>")
            lines += [f"{i}. {e(x)}" for i, x in enumerate(ai_json["qadamlar"], 1)]
        return "\n".join(lines)

    if ai_text:  # JSON emas, lekin matn bor
        lines.append(e(ai_text))
        return "\n".join(lines)

    lines[0] = f"🔍 <b>{e(client_name)}</b> — tahlil ({day:%d.%m})"
    if findings:
        for f in sorted(findings, key=lambda x: ["high", "medium", "low"].index(x["severity"])):
            lines.append(f"{ICON[f['severity']]} <i>{e(f['account'])}</i>: {e(f['text'])}")
    else:
        lines.append("✅ Qoidalar jiddiy muammo topmadi.")
    if ai_error:
        lines.append(f"\n<i>AI ishlamadi: {e(ai_error)}</i>")
    return "\n".join(lines)


async def run_for_client(client, kind: str = "daily", to_chat: int | None = None) -> int | None:
    """Tahlil qiladi, bazaga saqlaydi va Telegram'ga yuboradi. Qaytaradi: analyses.id"""
    bundle, findings = await collect(client)
    if not bundle["accountlar"]:
        if to_chat:
            await send(to_chat, f"{e(client['name'])}: Meta account biriktirilmagan.")
        return None
    today = datetime.now(TZ).date()
    for f in findings:  # muhim signallar alert sifatida ham (qoida ruxsat bersa guruhga)
        if kind == "daily" and f["type"] in ("cpr_spike", "spend_no_result"):
            await alert(f["type"], f"diag:{client['id']}:{f['type']}:{f['account']}:{today}",
                        f"{ICON[f['severity']]} {e(f['account'])}: {e(f['text'])}", client_id=client["id"])

    ai_json = ai_text = model = ai_error = None
    try:
        ai_json, ai_text, model = await ai.analyse(client["name"], RESULT_LABEL.get(client["result_type"], "Natija"),
                                                   bundle, findings)
    except ai.AiDisabled as ex:
        ai_error = str(ex)
    except Exception as ex:  # noqa: BLE001
        log.exception("AI tahlil xatosi")
        ai_error = str(ex)[:300]

    analysis_id = await db.fetchval(
        """INSERT INTO analyses (client_id, kind, findings, ai_json, ai_text, model, error)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
        client["id"], kind, [{k: f[k] for k in ("type", "severity", "text", "account")} for f in findings],
        ai_json, None if ai_json else ai_text, model, ai_error,
    )
    text = format_analysis(client["name"], today - timedelta(days=1), findings, ai_json, ai_text, ai_error)
    await send(to_chat or await admin_chat(), text)
    if client.get("ai_to_group") and ai_json:
        group = await db.fetchval(
            "SELECT g.chat_id FROM clients c JOIN tg_groups g ON g.id=c.group_id AND g.active WHERE c.id=$1", client["id"])
        if group:
            await send(group, text)
    return analysis_id


async def ask(client, question: str) -> tuple[int, str]:
    bundle, _ = await collect(client)
    if not bundle["accountlar"]:
        return 0, "Bu mijozga Meta account biriktirilmagan."
    try:
        text, model = await ai.answer(client["name"], RESULT_LABEL.get(client["result_type"], "Natija"), bundle, question)
        err = None
    except ai.AiDisabled as ex:
        text, model, err = str(ex), None, str(ex)
    aid = await db.fetchval(
        "INSERT INTO analyses (client_id, kind, question, ai_text, model, error) VALUES ($1,'question',$2,$3,$4,$5) RETURNING id",
        client["id"], question, text, model, err)
    return aid, text


def _in_window(now: datetime, hhmm: str, hours: int = 3) -> bool:
    h, m = map(int, hhmm.split(":"))
    minutes = now.hour * 60 + now.minute
    return h * 60 + m <= minutes <= h * 60 + m + hours * 60


async def run_all() -> None:
    """Har daqiqada chaqiriladi; adminkadagi tahlil vaqti kelganda har bir mijozni bir marta tahlil qiladi."""
    now = datetime.now(TZ)
    if not _in_window(now, await settings.diagnostics_time()):
        return
    today = now.date()
    for c in await db.fetch("SELECT * FROM clients WHERE diagnostics = true"):
        done = await db.fetchval(
            "SELECT 1 FROM reports_log WHERE client_id=$1 AND kind='diagnostics' AND period=$2", c["id"], today)
        if done:
            continue
        try:
            await run_for_client(dict(c))
            ok, err = True, None
        except Exception as ex:  # noqa: BLE001
            log.exception("Tahlil xatosi: %s", c["name"])
            ok, err = False, str(ex)[:300]
        await db.execute(
            """INSERT INTO reports_log (client_id, kind, period, ok, error) VALUES ($1,'diagnostics',$2,$3,$4)
               ON CONFLICT (client_id, kind, period) DO NOTHING""", c["id"], today, ok, err)
