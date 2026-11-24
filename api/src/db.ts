import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const path = process.env.DB_PATH ?? './data/evals.db';
mkdirSync(dirname(path), { recursive: true });
export const db = new DatabaseSync(path);

db.exec(`
CREATE TABLE IF NOT EXISTS configs (
  id TEXT PRIMARY KEY, name TEXT, version INTEGER, hash TEXT, harness TEXT, model TEXT,
  settings TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY, name TEXT, trials_per_task INTEGER, config_ids TEXT, task_ids TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS trials (
  id TEXT PRIMARY KEY, experiment_id TEXT, config_id TEXT, task_id TEXT, trial_idx INTEGER,
  status TEXT, score REAL, reasoning TEXT, duration_ms INTEGER, cost_usd REAL, usage TEXT,
  final_text TEXT, files TEXT, events TEXT, attempts INTEGER DEFAULT 0, meta TEXT);
CREATE INDEX IF NOT EXISTS trials_exp ON trials(experiment_id);
CREATE UNIQUE INDEX IF NOT EXISTS trials_cell ON trials(experiment_id, config_id, task_id, trial_idx);
`);

try { db.exec('ALTER TABLE trials ADD COLUMN meta TEXT'); } catch { /* column already exists */ }

export const all = (sql: string, ...p: any[]) => db.prepare(sql).all(...p) as any[];
export const one = (sql: string, ...p: any[]) => db.prepare(sql).get(...p) as any;
export const run = (sql: string, ...p: any[]) => db.prepare(sql).run(...p);
export const json = (s: string | null) => (s ? JSON.parse(s) : null);
