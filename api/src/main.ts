import 'reflect-metadata';
import { Module } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { ApiController } from './api.controller';
import { resume } from './runner';

@Module({ controllers: [ApiController] })
class AppModule {}

async function main() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { logger: ['error', 'warn', 'log'] });
  const web = process.env.WEB_DIR ?? join(process.cwd(), 'web');
  if (existsSync(web)) app.useStaticAssets(web);  // built Vue UI
  resume();
  await app.listen(Number(process.env.PORT ?? 3000), '0.0.0.0');
  console.log('api up');
}
main();
