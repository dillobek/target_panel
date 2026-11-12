import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { JwtModule } from '@nestjs/jwt';
import { ApiController } from './api.controller';
import { AuthController, AuthGuard } from './auth';
import { DbService } from './db.service';
import { WebhookController } from './webhook.controller';

@Module({
  imports: [
    JwtModule.register({
      global: true,
      secret: process.env.JWT_SECRET,
      signOptions: { expiresIn: '7d' },
    }),
  ],
  controllers: [AuthController, ApiController, WebhookController],
  providers: [DbService, { provide: APP_GUARD, useClass: AuthGuard }],
})
export class AppModule {}
