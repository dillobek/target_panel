import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { existsSync, readFileSync } from 'fs';
import { Pool } from 'pg';

@Injectable()
export class DbService implements OnModuleInit, OnModuleDestroy {
  private pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 10 });
  private log = new Logger('Db');

  async onModuleInit() {
    const file = process.env.MIGRATE_SQL || '/app/db/migrate.sql';
    if (!existsSync(file)) {
      this.log.warn(`${file} topilmadi, migratsiya o'tkazib yuborildi`);
      return;
    }
    const client = await this.pool.connect();
    try {
      await client.query('SELECT pg_advisory_lock(424242)');
      await client.query(readFileSync(file, 'utf8'));
    } finally {
      await client.query('SELECT pg_advisory_unlock(424242)').catch(() => undefined);
      client.release();
    }
  }

  async query<T = any>(sql: string, params: unknown[] = []): Promise<T[]> {
    const r = await this.pool.query(sql, params as any[]);
    return r.rows as T[];
  }

  async one<T = any>(sql: string, params: unknown[] = []): Promise<T | null> {
    const rows = await this.query<T>(sql, params);
    return rows[0] ?? null;
  }

  onModuleDestroy() {
    return this.pool.end();
  }
}
