import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  NotFoundException,
  Param,
  ParseIntPipe,
  Patch,
  Post,
  Put,
  Query,
} from '@nestjs/common';
import { encrypt } from './crypto.util';
import { DbService } from './db.service';

const RESULT_TYPES = ['messaging', 'lead_form', 'lead_site', 'purchase'];
const RULE_TYPES = ['account_status', 'ad_issues', 'spend_limit', 'cpr_spike', 'spend_no_result', 'token_error'];
const META_V = () => process.env.META_API_VERSION || 'v26.0';

function str(v: unknown, field: string, max = 200): string {
  if (typeof v !== 'string' || !v.trim()) throw new BadRequestException(`${field} majburiy`);
  if (v.length > max) throw new BadRequestException(`${field} juda uzun`);
  return v.trim();
}

async function metaGet(url: string): Promise<any> {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(20000) });
    return await r.json();
  } catch {
    throw new BadRequestException("Meta'ga ulanib bo'lmadi — server internetini tekshiring");
  }
}

async function verifyMetaToken(token: string): Promise<string> {
  const j = await metaGet(`https://graph.facebook.com/${META_V()}/me?fields=id,name&access_token=${encodeURIComponent(token)}`);
  if (j.error) throw new BadRequestException('Meta token xato: ' + j.error.message);
  const aj = await metaGet(
    `https://graph.facebook.com/${META_V()}/me/adaccounts?fields=name&limit=1&access_token=${encodeURIComponent(token)}`,
  );
  if (aj.error) throw new BadRequestException("Token reklama accountlarini o'qiy olmaydi: " + aj.error.message);
  return j.name ?? 'Meta';
}

@Controller('api')
export class ApiController {
  constructor(private db: DbService) {}

  // ---------- Umumiy ----------
  @Get('config')
  async config() {
    const r = await this.db.one("SELECT value FROM settings WHERE key='bot_username'");
    return { botUsername: r?.value ?? process.env.BOT_USERNAME ?? '' };
  }

  @Get('stats')
  async stats() {
    return this.db.one(`
      SELECT
        (SELECT count(*) FROM ad_accounts)::int AS total,
        (SELECT count(*) FROM ad_accounts WHERE platform='tg_ads' OR account_status = 1)::int AS active,
        (SELECT count(*) FROM ad_accounts WHERE platform='meta' AND account_status <> 1)::int AS problem,
        (SELECT count(*) FROM ad_accounts a WHERE NOT EXISTS (SELECT 1 FROM client_sources s WHERE s.ad_account_id=a.id))::int AS unassigned,
        (SELECT count(*) FROM tg_groups g WHERE g.active AND NOT EXISTS (SELECT 1 FROM clients c WHERE c.group_id=g.id))::int AS free_groups,
        (SELECT at FROM heartbeat WHERE name='worker') AS worker_heartbeat`);
  }

  // ---------- Ulanishlar ----------
  @Get('connections')
  async connections() {
    return this.db.query(`
      SELECT c.id, c.platform, c.name, c.token_last4, c.status, c.last_error, c.last_checked_at, c.created_at,
             (SELECT count(*) FROM ad_accounts a WHERE a.connection_id=c.id)::int AS accounts
      FROM connections c ORDER BY c.id`);
  }

  @Post('connections')
  async addConnection(@Body() b: any) {
    const platform = b?.platform === 'tg_ads' ? 'tg_ads' : 'meta';
    const name = str(b?.name, 'Nomi', 100);
    const token = str(b?.token, 'Token', 2000);
    let status = 'ok';
    if (platform === 'meta') await verifyMetaToken(token);
    else status = 'pending_api';
    const row = await this.db.one(
      `INSERT INTO connections (platform, name, token_enc, token_last4, status, last_checked_at)
       VALUES ($1,$2,$3,$4,$5, now()) RETURNING id`,
      [platform, name, encrypt(token), token.slice(-4), status],
    );
    if (platform === 'meta') await this.job('sync_now', { connection_id: row.id });
    return row;
  }

  @Post('connections/:id/sync')
  async syncConnection(@Param('id', ParseIntPipe) id: number) {
    return this.job('sync_now', { connection_id: id });
  }

  @Delete('connections/:id')
  async deleteConnection(@Param('id', ParseIntPipe) id: number) {
    await this.db.query('DELETE FROM connections WHERE id=$1', [id]);
    return { ok: true };
  }

  // ---------- Accountlar ----------
  @Get('accounts')
  async accounts(@Query('platform') platform?: string) {
    const where = platform === 'meta' || platform === 'tg_ads' ? 'WHERE a.platform = $1' : '';
    return this.db.query(
      `SELECT a.id, a.platform, a.external_id, a.name, a.currency, a.account_status, a.spend_cap, a.amount_spent,
              a.yesterday_spend, a.updated_at,
              COALESCE(string_agg(c.name, ', ' ORDER BY c.name), '') AS clients
       FROM ad_accounts a
       LEFT JOIN client_sources s ON s.ad_account_id = a.id
       LEFT JOIN clients c ON c.id = s.client_id
       ${where}
       GROUP BY a.id ORDER BY a.name`,
      where ? [platform] : [],
    );
  }

  // ---------- Guruhlar ----------
  @Get('groups')
  async groups() {
    return this.db.query(`
      SELECT g.id, g.chat_id::text AS chat_id, g.title, g.bot_is_admin, g.active,
             (SELECT name FROM clients c WHERE c.group_id=g.id LIMIT 1) AS client
      FROM tg_groups g WHERE g.active ORDER BY g.created_at DESC`);
  }

  // ---------- Mijozlar ----------
  @Get('clients')
  async clients() {
    return this.db.query(`
      SELECT c.*, g.title AS group_title,
             (SELECT count(*) FROM client_sources s JOIN ad_accounts a ON a.id=s.ad_account_id
              WHERE s.client_id=c.id AND a.platform='meta')::int AS meta_sources,
             (SELECT count(*) FROM client_sources s JOIN ad_accounts a ON a.id=s.ad_account_id
              WHERE s.client_id=c.id AND a.platform='tg_ads')::int AS tg_sources
      FROM clients c LEFT JOIN tg_groups g ON g.id=c.group_id ORDER BY c.name`);
  }

  @Get('clients/:id')
  async client(@Param('id', ParseIntPipe) id: number) {
    const c = await this.db.one('SELECT * FROM clients WHERE id=$1', [id]);
    if (!c) throw new NotFoundException();
    c.sources = await this.db.query(
      `SELECT s.id, s.tg_prefix, a.id AS ad_account_id, a.platform, a.name, a.external_id
       FROM client_sources s JOIN ad_accounts a ON a.id=s.ad_account_id WHERE s.client_id=$1 ORDER BY a.name`,
      [id],
    );
    return c;
  }

  @Post('clients')
  async createClient(@Body() b: any) {
    return this.db.one('INSERT INTO clients (name) VALUES ($1) RETURNING id', [str(b?.name, 'Mijoz nomi', 100)]);
  }

  @Patch('clients/:id')
  async updateClient(@Param('id', ParseIntPipe) id: number, @Body() b: any) {
    const sets: string[] = [];
    const vals: unknown[] = [];
    const add = (col: string, v: unknown) => {
      vals.push(v);
      sets.push(`${col}=$${vals.length}`);
    };
    if (b.name !== undefined) add('name', str(b.name, 'Mijoz nomi', 100));
    if (b.result_type !== undefined) {
      if (!RESULT_TYPES.includes(b.result_type)) throw new BadRequestException("Natija turi noto'g'ri");
      add('result_type', b.result_type);
    }
    if (b.group_id !== undefined) add('group_id', b.group_id === null || b.group_id === '' ? null : Number(b.group_id));
    if (b.report_daily !== undefined) add('report_daily', !!b.report_daily);
    if (b.report_weekly !== undefined) add('report_weekly', !!b.report_weekly);
    if (b.diagnostics !== undefined) add('diagnostics', !!b.diagnostics);
    if (b.ai_to_group !== undefined) add('ai_to_group', !!b.ai_to_group);
    if (b.report_daily_time !== undefined) {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(b.report_daily_time)) throw new BadRequestException('Vaqt HH:MM formatida');
      add('report_daily_time', b.report_daily_time);
    }
    if (!sets.length) return { ok: true };
    vals.push(id);
    await this.db.query(`UPDATE clients SET ${sets.join(', ')} WHERE id=$${vals.length}`, vals);
    return { ok: true };
  }

  @Delete('clients/:id')
  async deleteClient(@Param('id', ParseIntPipe) id: number) {
    await this.db.query('DELETE FROM alert_rules WHERE client_id=$1', [id]);
    await this.db.query('DELETE FROM clients WHERE id=$1', [id]);
    return { ok: true };
  }

  @Post('clients/:id/sources')
  async addSource(@Param('id', ParseIntPipe) id: number, @Body() b: any) {
    const accId = Number(b?.ad_account_id);
    if (!accId) throw new BadRequestException('Account tanlang');
    const prefix = typeof b?.tg_prefix === 'string' && b.tg_prefix.trim() ? b.tg_prefix.trim().slice(0, 50) : null;
    await this.db.query(
      `INSERT INTO client_sources (client_id, ad_account_id, tg_prefix) VALUES ($1,$2,$3)
       ON CONFLICT (client_id, ad_account_id) DO UPDATE SET tg_prefix=EXCLUDED.tg_prefix`,
      [id, accId, prefix],
    );
    return { ok: true };
  }

  @Delete('clients/:id/sources/:sid')
  async removeSource(@Param('id', ParseIntPipe) id: number, @Param('sid', ParseIntPipe) sid: number) {
    await this.db.query('DELETE FROM client_sources WHERE id=$1 AND client_id=$2', [sid, id]);
    return { ok: true };
  }

  @Post('clients/:id/test-report')
  async testReport(@Param('id', ParseIntPipe) id: number) {
    return this.job('test_report', { client_id: id });
  }

  // ---------- AI tahlil ----------
  @Get('clients/:id/analyses')
  async analyses(@Param('id', ParseIntPipe) id: number) {
    return this.db.query(
      `SELECT id, kind, question, findings, ai_json, ai_text, model, error, created_at
       FROM analyses WHERE client_id=$1 ORDER BY id DESC LIMIT 20`,
      [id],
    );
  }

  @Post('clients/:id/diagnostics')
  async diagnosticsNow(@Param('id', ParseIntPipe) id: number) {
    return this.job('ai_analysis', { client_id: id });
  }

  @Post('clients/:id/ask')
  async ask(@Param('id', ParseIntPipe) id: number, @Body() b: any) {
    const question = str(b?.question, 'Savol', 1000);
    return this.job('ai_question', { client_id: id, question });
  }

  // ---------- Alert qoidalari ----------
  @Get('alert-rules')
  async rules(@Query('client_id') clientId?: string) {
    const cid = Number(clientId) || 0;
    return this.db.query(
      `SELECT g.type,
              COALESCE(c.enabled, g.enabled) AS enabled,
              COALESCE(c.threshold, g.threshold) AS threshold,
              COALESCE(c.notify_client, g.notify_client) AS notify_client,
              (c.id IS NOT NULL) AS overridden
       FROM alert_rules g
       LEFT JOIN alert_rules c ON c.type=g.type AND c.client_id=$1 AND $1 <> 0
       WHERE g.client_id=0 ORDER BY g.id`,
      [cid],
    );
  }

  @Put('alert-rules')
  async saveRules(@Body() b: any) {
    const cid = Number(b?.client_id) || 0;
    for (const r of b?.rules ?? []) {
      if (!RULE_TYPES.includes(r.type)) continue;
      const th = r.threshold === null || r.threshold === '' || r.threshold === undefined ? null : Number(r.threshold);
      await this.db.query(
        `INSERT INTO alert_rules (client_id, type, enabled, threshold, notify_client) VALUES ($1,$2,$3,$4,$5)
         ON CONFLICT (client_id, type) DO UPDATE
         SET enabled=EXCLUDED.enabled, threshold=EXCLUDED.threshold, notify_client=EXCLUDED.notify_client`,
        [cid, r.type, !!r.enabled, Number.isFinite(th as number) ? th : null, !!r.notify_client],
      );
    }
    return { ok: true };
  }

  @Get('alerts-log')
  async alertsLog() {
    return this.db.query(
      `SELECT l.id, l.type, l.message, l.sent_to, l.created_at, c.name AS client
       FROM alerts_log l LEFT JOIN clients c ON c.id=l.client_id ORDER BY l.id DESC LIMIT 100`,
    );
  }

  @Get('jobs/:id')
  async jobStatus(@Param('id', ParseIntPipe) id: number) {
    return this.db.one('SELECT id, type, status, error, result, done_at FROM jobs WHERE id=$1', [id]);
  }

  private job(type: string, payload: object) {
    return this.db.one('INSERT INTO jobs (type, payload) VALUES ($1,$2) RETURNING id', [type, JSON.stringify(payload)]);
  }
}
