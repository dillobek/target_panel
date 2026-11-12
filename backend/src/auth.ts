import {
  Body,
  CanActivate,
  Controller,
  ExecutionContext,
  Injectable,
  Post,
  SetMetadata,
  UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { JwtService } from '@nestjs/jwt';
import { createHash, timingSafeEqual } from 'crypto';

export const IS_PUBLIC = 'isPublic';
export const Public = () => SetMetadata(IS_PUBLIC, true);

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(private jwt: JwtService, private reflector: Reflector) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC, [ctx.getHandler(), ctx.getClass()]);
    if (isPublic) return true;
    const req = ctx.switchToHttp().getRequest();
    const [kind, token] = String(req.headers.authorization ?? '').split(' ');
    if (kind !== 'Bearer' || !token) throw new UnauthorizedException();
    try {
      await this.jwt.verifyAsync(token);
      return true;
    } catch {
      throw new UnauthorizedException();
    }
  }
}

const sha = (s: string) => createHash('sha256').update(s).digest();

@Controller('api/auth')
export class AuthController {
  constructor(private jwt: JwtService) {}

  @Public()
  @Post('login')
  async login(@Body() body: { password?: string }) {
    const expected = process.env.ADMIN_PASSWORD ?? '';
    if (!expected || !body?.password || !timingSafeEqual(sha(body.password), sha(expected))) {
      await new Promise((r) => setTimeout(r, 800));
      throw new UnauthorizedException("Parol noto'g'ri");
    }
    return { token: await this.jwt.signAsync({ sub: 'admin' }) };
  }
}
