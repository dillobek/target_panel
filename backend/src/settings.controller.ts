import { BadRequestException, Body, Controller, Get, Post, Put } from '@nestjs/common';
import { encrypt } from './crypto.util';
import { DbService } from './db.service';

export const AI_MODELS = ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'];

async function safeFetch(url: string, init: RequestInit | undefined, service: string): Promise<Response> {
  try {
    return await fetch(url, { ...init, signal: AbortSignal.timeout(15000) });
  } catch {
    throw new BadRequestException(`${service} ga ulanib bo'lmadi — server internetini tekshiring`);
  }
}

@Controller('api/settings')
export class SettingsController {
  constructor(private db: DbService) {}

  private async set(key: string, value: string | null, secret = false) {
    await this.db.query(
      `INSERT INTO settings (key, value, is_secret, updated_at) VALUES ($1,$2,$3, now())
       ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, is_secret=EXCLUDED.is_secret, updated_at=now()`,
      [key, value, secret],
    );
  }

  @Get()
  async get() {
    const rows = await this.db.query<{ key: string; value: string; is_secret: boolean; updated_at: string }>(
      'SELECT key, value, is_secret, updated_at FROM settings',
    );
    const m = Object.fromEntries(rows.map((r) => [r.key, r]));
    const v = (k: string) => m[k]?.value ?? null;
    let starters: unknown[] = [];
    try {
      starters = JSON.parse(v('bot_starters') ?? '[]');
    } catch {
      starters = [];
    }
    return {
      bot: {
        connected: !!m['bot_token'] || !!process.env.BOT_TOKEN,
        username: v('bot_username') ?? process.env.BOT_USERNAME ?? null,
        token_last4: v('bot_token_last4'),
        status: v('bot_status'),
        status_at: m['bot_status']?.updated_at ?? null,
      },
      admin_chat_id: v('admin_chat_id') ?? process.env.ADMIN_CHAT_ID ?? null,
      admin_chat_name: v('admin_chat_name'),
      starters,
      ai: {
        enabled: (v('ai_enabled') ?? 'true') === 'true',
        model: v('ai_model') ?? 'claude-sonnet-5-5',
        key_set: !!m['anthropic_api_key'] || !!process.env.ANTHROPIC_API_KEY,
        key_last4: v('anthropic_key_last4'),
        models: AI_MODELS,
      },
      diagnostics_time: v('diagnostics_time') ?? '08:30',
    };
  }

  @Put('bot')
  async setBot(@Body() b: any) {
    const token = String(b?.token ?? '').trim();
    if (!/^\d+:[\w-]{30,}$/.test(token)) throw new BadRequestException("Bot token formati noto'g'ri (123456:ABC...)");
    const r = await safeFetch(`https://api.telegram.org/bot${token}/getMe`, undefined, 'Telegram');
    const j: any = await r.json().catch(() => ({}));
    if (!j.ok) throw new BadRequestException('Telegram tokenni qabul qilmadi: ' + (j.description ?? r.status));
    await this.set('bot_token', encrypt(token), true);
    await this.set('bot_token_last4', token.slice(-4));
    await this.set('bot_username', j.result.username);
    await this.set('bot_status', 'restarting');
    return { username: j.result.username };
  }

  @Put('admin-chat')
  async setAdminChat(@Body() b: any) {
    const id = String(b?.chat_id ?? '').trim();
    if (!/^-?\d{1,20}$/.test(id)) throw new BadRequestException("Chat ID raqam bo'lishi kerak");
    await this.set('admin_chat_id', id);
    await this.set('admin_chat_name', typeof b?.name === 'string' ? b.name.slice(0, 100) : null);
    return { ok: true };
  }

  @Put('ai')
  async setAi(@Body() b: any) {
    if (b?.model !== undefined) {
      if (!AI_MODELS.includes(b.model)) throw new BadRequestException("Model noto'g'ri");
      await this.set('ai_model', b.model);
    }
    if (b?.enabled !== undefined) await this.set('ai_enabled', b.enabled ? 'true' : 'false');
    if (b?.diagnostics_time !== undefined) {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(b.diagnostics_time)) throw new BadRequestException('Vaqt HH:MM formatida');
      await this.set('diagnostics_time', b.diagnostics_time);
    }
    const key = typeof b?.api_key === 'string' ? b.api_key.trim() : '';
    if (key) {
      const r = await safeFetch('https://api.anthropic.com/v1/models?limit=1', {
        headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      }, 'Anthropic');
      if (r.status === 401 || r.status === 403) throw new BadRequestException('Anthropic API kaliti xato');
      if (!r.ok) throw new BadRequestException(`Anthropic tekshiruvi muvaffaqiyatsiz (${r.status})`);
      await this.set('anthropic_api_key', encrypt(key), true);
      await this.set('anthropic_key_last4', key.slice(-4));
    }
    return { ok: true };
  }

  @Post('test-message')
  async testMessage() {
    return this.db.one(`INSERT INTO jobs (type, payload) VALUES ('test_admin_message', '{}') RETURNING id`);
  }
}
