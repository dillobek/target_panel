import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { join } from 'path';
import { AppModule } from './app.module';

async function bootstrap() {
  for (const k of ['DATABASE_URL', 'JWT_SECRET', 'ENCRYPTION_KEY', 'ADMIN_PASSWORD']) {
    if (!process.env[k]) throw new Error(`${k} .env da o'rnatilmagan`);
  }
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { rawBody: true });
  app.useStaticAssets(join(__dirname, '..', 'public'));
  app.set('trust proxy', 1);
  await app.listen(Number(process.env.PORT) || 3000, '0.0.0.0');
  console.log('Targetpanel API ishga tushdi');
}
bootstrap();
