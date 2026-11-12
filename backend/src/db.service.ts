import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { Pool } from 'pg';

@Injectable()
export class DbService implements OnModuleDestroy {
  private pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 10 });

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
