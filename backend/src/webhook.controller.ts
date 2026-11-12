import { Controller, ForbiddenException, Get, HttpCode, Post, Query, Req } from '@nestjs/common';
import { createHmac, timingSafeEqual } from 'crypto';
import { Public } from './auth';
import { DbService } from './db.service';

// Meta Ads webhook: https://<domen>/webhooks/meta
@Controller('webhooks/meta')
export class WebhookController {
  constructor(private db: DbService) {}

  @Public()
  @Get()
  verify(
    @Query('hub.mode') mode: string,
    @Query('hub.verify_token') token: string,
    @Query('hub.challenge') challenge: string,
  ) {
    if (mode === 'subscribe' && token && token === process.env.META_WEBHOOK_VERIFY_TOKEN) return challenge;
    throw new ForbiddenException();
  }

  @Public()
  @Post()
  @HttpCode(200)
  async receive(@Req() req: any) {
    const secret = process.env.META_APP_SECRET ?? '';
    const sig = String(req.headers['x-hub-signature-256'] ?? '');
    const raw: Buffer = req.rawBody ?? Buffer.from('');
    const expected = 'sha256=' + createHmac('sha256', secret).update(raw).digest('hex');
    if (!secret || sig.length !== expected.length || !timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
      throw new ForbiddenException('Imzo xato');
    }
    const body = req.body ?? {};
    for (const entry of body.entry ?? []) {
      for (const change of entry.changes ?? []) {
        await this.db.query(
          `INSERT INTO events (source, external_id, field, payload) VALUES ('meta', $1, $2, $3)`,
          [String(entry.id ?? '').replace(/^act_/, ''), String(change.field ?? ''), JSON.stringify(change.value ?? {})],
        );
      }
    }
    return 'ok';
  }
}
