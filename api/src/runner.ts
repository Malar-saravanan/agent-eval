/** Trial queue: bounded concurrency, retries on infra errors, resumable after a crash. */
import { readFileSync } from 'node:fs';
import { all, json, one, run } from './db';

const WORKER = process.env.WORKER_URL ?? 'http://worker:8000';
const CONCURRENCY = Number(process.env.CONCURRENCY ?? 4);
const VALID = new Set(['passed', 'failed', 'timeout', 'infra_error', 'grader_error', 'not_applicable']);
const MAX_ATTEMPTS = 3;  // infra errors (429s, upstream 5xx, worker down) are retried; model failures are not

// The worker publishes a secret on a volume only root can read; /trial refuses requests without it (agents share the
// worker's network namespace and must not be able to start or wipe trials). Re-read every call: it changes on restart.
const TOKEN_FILE = process.env.WORKER_TOKEN_FILE ?? '/ipc/worker-token';
function workerAuth(): Record<string, string> {
  try { return { 'x-worker-token': readFileSync(TOKEN_FILE, 'utf8').trim() }; } catch { return {}; }
}

const queue: string[] = [];
let active = 0;

export function enqueue(ids: string[]) {
  queue.push(...ids);
  pump();
}

/** Call once at startup: anything left queued/running by a previous process goes back in the queue. */
export function resume() {
  run(`UPDATE trials SET status='queued' WHERE status='running'`);
  enqueue(all(`SELECT id FROM trials WHERE status='queued' ORDER BY trial_idx, rowid`).map((r) => r.id));
}

function pump() {
  while (active < CONCURRENCY && queue.length) {
    const id = queue.shift()!;
    active++;
    runOne(id).catch((e) => console.error('trial crashed', id, e)).finally(() => { active--; pump(); });
  }
}

async function runOne(id: string) {
  const t = one(`SELECT * FROM trials WHERE id=?`, id);
  const c = one(`SELECT * FROM configs WHERE id=?`, t.config_id);
  const config = { harness: c.harness, model: c.model, settings: json(c.settings) };
  let res: any = null;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    run(`UPDATE trials SET status='running', attempts=? WHERE id=?`, attempt, id);
    try {
      const r = await fetch(`${WORKER}/trial`, {
        method: 'POST', headers: { 'content-type': 'application/json', ...workerAuth() },
        body: JSON.stringify({ trial_id: id, task_id: t.task_id, config }),
        signal: AbortSignal.timeout(20 * 60_000),
      });
      res = r.ok ? await r.json() : { status: 'infra_error', reasoning: `worker HTTP ${r.status}${r.status === 401 ? ' (worker token rejected: is the ipc volume shared?)' : ''}` };
    } catch (e: any) {
      res = { status: 'infra_error', reasoning: `worker unreachable: ${e.message}` };
    }
    if (res.status !== 'infra_error') break;
    await new Promise((ok) => setTimeout(ok, 2000 * attempt * attempt));  // backoff
  }
  // A malformed worker reply (missing/unknown status) must never leave the trial 'running' forever.
  if (!VALID.has(res?.status)) res = { status: 'infra_error', reasoning: `worker returned an invalid result (status=${JSON.stringify(res?.status)})` };
  try {
    run(
      `UPDATE trials SET status=?, score=?, reasoning=?, duration_ms=?, cost_usd=?, usage=?, final_text=?, files=?, events=?, meta=? WHERE id=?`,
      res.status, res.score ?? null, res.reasoning ?? null, res.duration_ms ?? null, res.cost_usd ?? null,
      JSON.stringify(res.usage ?? null), res.final_text ?? '', JSON.stringify(res.files ?? []), JSON.stringify(res.events ?? []), JSON.stringify(res.meta ?? null), id,
    );
  } catch (e: any) {
    console.error('could not store trial result', id, e.message);
    run(`UPDATE trials SET status='infra_error', reasoning=? WHERE id=?`, `result could not be stored: ${String(e.message).slice(0, 160)}`, id);
  }
}
