// Vite strips the `node:` prefix from `node:sqlite` (not in its builtin list) and then fails to resolve `sqlite`.
// Loading it through createRequire sidesteps the bundler; production code still imports `node:sqlite` directly.
import { createRequire } from 'node:module';

export const { DatabaseSync } = createRequire(import.meta.url)('node:sqlite');
