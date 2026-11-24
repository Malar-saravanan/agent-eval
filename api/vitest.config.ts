import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: { alias: { 'node:sqlite': fileURLToPath(new URL('./test/node-sqlite-shim.ts', import.meta.url)) } },
});
