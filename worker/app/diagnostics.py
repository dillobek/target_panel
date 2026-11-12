"""Reklama tahlili: qoidalar asosida muammolarni topish (+ ixtiyoriy AI izoh)."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from . import db
from .ai import explain
from .config import ADMIN_CHAT_ID, TZ
from .crypto import decrypt
from .meta import MetaClient, MetaError, insights_url
from .metrics import RESULT_LABEL, aggregate, cost_per, results_from_actions
from .notify import alert, e, get_rule, send

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


async def diagnose_client(client) -> tuple[str, list[dict]]:
    accounts = await _client_accounts(client["id"])
    if not accounts:
        return "", []
    rt = client["result_type"]
    spike = float((await get_rule(client["id"], "cpr_spike"))["threshold"] or 30)
    no_res = float((await get_rule(client["id"], "spend_no_result"))["threshold"] or 5)

    findings: list[dict] = []
    summary_lines = []
    end = datetime.now(TZ).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    for acc in accounts:
        daily = [dict(r) for r in await db.fetch(
            "SELECT * FROM insights_daily WHERE ad_account_id=$1 AND date BETWEEN $2 AND $3 ORDER BY date",
            acc["id"], start, end)]
        acc_findings = analyse_account(daily, rt, spike, no_res)
        try:
            client_api = MetaClient(decrypt(acc["token_enc"]))
            ext = acc["external_id"]
            ads_7d, ads_daily, places = await client_api.batch([
                insights_url(ext, level="ad", date_preset="last_7d", limit=200,
                             fields="ad_id,ad_name,spend,impressions,clicks,ctr,frequency,actions"),
                insights_url(ext, level="ad", date_preset="last_7d", time_increment=1, limit=1000,
                             fields="ad_id,ctr,impressions"),
                insights_url(ext, level="account", date_preset="last_7d", breakdowns="publisher_platform",
                             fields="spend,clicks,impressions,actions"),
            ])
            acc_findings += analyse_ads((ads_7d or {}).get("data", []), (ads_daily or {}).get("data", []), rt)
            acc_findings += analyse_placements((places or {}).get("data", []), rt)
        except MetaError as ex:
            log.warning("Tahlil uchun Meta xatosi (%s): %s", acc["name"], ex)
        for f in acc_findings:
            f["account"] = acc["name"]
        findings += acc_findings
        if daily:
            agg = aggregate(daily, rt)
            summary_lines.append(
                f"{acc['name']} ({acc['currency']}): 7 kun sarf {agg['spend']}, "
                f"{RESULT_LABEL.get(rt, 'natija')} {agg['results']}, narxi {agg['cpr']}, CTR {agg['ctr']}%, CPM {agg['cpm']}"
            )
    return "\n".join(summary_lines), findings


ICON = {"high": "❗", "medium": "⚠️", "low": "ℹ️"}


async def run_for_client(client, to_chat: int = ADMIN_CHAT_ID) -> None:
    summary, findings = await diagnose_client(client)
    if not summary:
        return
    # Muhim topilmalar alert sifatida ham (qoida "mijozga ham" desa guruhga ham boradi)
    today = datetime.now(TZ).date()
    for f in findings:
        if f["type"] in ("cpr_spike", "spend_no_result"):
            await alert(f["type"], f"diag:{client['id']}:{f['type']}:{f['account']}:{today}",
                        f"{ICON[f['severity']]} {e(f['account'])}: {e(f['text'])}", client_id=client["id"])

    lines = [f"🔍 <b>{e(client['name'])}</b> — tahlil ({today - timedelta(days=1):%d.%m})"]
    if findings:
        for f in sorted(findings, key=lambda x: ["high", "medium", "low"].index(x["severity"])):
            lines.append(f"{ICON[f['severity']]} <i>{e(f['account'])}</i>: {e(f['text'])}")
    else:
        lines.append("✅ Jiddiy muammo topilmadi.")
    ai_text = await explain(client["name"], summary, findings)
    if ai_text:
        lines.append("\n🤖 <b>AI xulosa</b>\n" + e(ai_text))
    await send(to_chat, "\n".join(lines))


async def run_all() -> None:
    today = datetime.now(TZ).date()
    for c in await db.fetch("SELECT * FROM clients WHERE diagnostics = true"):
        done = await db.fetchval(
            "SELECT 1 FROM reports_log WHERE client_id=$1 AND kind='diagnostics' AND period=$2", c["id"], today)
        if done:
            continue
        try:
            await run_for_client(c)
            ok, err = True, None
        except Exception as ex:  # noqa: BLE001
            log.exception("Tahlil xatosi: %s", c["name"])
            ok, err = False, str(ex)[:300]
        await db.execute(
            """INSERT INTO reports_log (client_id, kind, period, ok, error) VALUES ($1,'diagnostics',$2,$3,$4)
               ON CONFLICT (client_id, kind, period) DO NOTHING""", c["id"], today, ok, err)
