// Read-only catalog: tasks (one task.yaml per task dir), models (config/models.yaml), harness capabilities.
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { parse } from 'yaml';

const TASKS_DIR = process.env.TASKS_DIR ?? '/tasks';
const MODELS_FILE = process.env.MODELS_FILE ?? '/config/models.yaml';

// Keep in sync with worker/harnesses.py (capabilities of each adapter).
export const HARNESSES = [
  { name: 'hermes', capabilities: ['skills', 'memory'] },
  { name: 'opencode', capabilities: ['skills'] },
];

let cache: { at: number; tasks: any[] } | null = null;

/** Task definitions rarely change; parse the YAML at most every 10s instead of on every request. */
export function listTasks(): any[] {
  if (cache && Date.now() - cache.at < 10_000) return cache.tasks;
  const tasks = readTasks();
  cache = { at: Date.now(), tasks };
  return tasks;
}

function readTasks() {
  if (!existsSync(TASKS_DIR)) return [];
  return readdirSync(TASKS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory() && existsSync(join(TASKS_DIR, d.name, 'task.yaml')))
    .map((d) => parse(readFileSync(join(TASKS_DIR, d.name, 'task.yaml'), 'utf8')))
    .map((t) => ({ id: t.id, title: t.title, category: t.category, grader: t.grader?.type, requires: t.requires ?? [] }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

export function listModels() {
  const m = parse(readFileSync(MODELS_FILE, 'utf8'));
  return Object.entries<any>(m).map(([id, v]) => ({ id, price_per_1m: v.price_per_1m }));
}
