import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
  const { mkdtempSync } = require('node:fs');
  const { tmpdir } = require('node:os');
  const { join } = require('node:path');
  process.env.DB_PATH = join(mkdtempSync(join(tmpdir(), 'runner-spec-')), 'evals.db');
  process.env.CONCURRENCY = '2';
});

import { all, one, run } from './db';
import { enqueue, resume } from './runner';

const cfgSettings = { skills: true, nudge: false };

function seed(id: string, status = 'queued', idx = 0) {
  run(`INSERT OR IGNORE INTO configs VALUES ('c@v1','c',1,'h','hermes','gpt-4.1-mini',?, 'now')`, JSON.stringify(cfgSettings));
  run(`INSERT INTO trials (id, experiment_id, config_id, task_id, trial_idx, status) VALUES (?,?,?,?,?,?)`, id, 'e1', 'c@v1', 'task-1', idx, status);
}
const trial = (id: string) => one('SELECT * FROM trials WHERE id=?', id);
const reply = (body: any, status = 200) => ({ ok: status < 400, status, json: async () => body }) as any;
const infra = () => reply({ status: 'infra_error', reasoning: 'upstream 429', score: null });
const passed = (extra = {}) => reply({ status: 'passed', score: 1, reasoning: 'ok', duration_ms: 1234, cost_usd: 0.002,
  usage: { prompt_tokens: 5, completion_tokens: 2, calls: 1 }, final_text: 'done', files: ['a.txt'],
  events: [{ type: 'assistant', text: 'hi' }], meta: { task_hash: 'abc123', harness_version: '1.0', budget: { max_steps: 3, max_tokens: 9 } }, ...extra });

/** Advance fake timers until the trial leaves queued/running (covers the retry backoff sleeps). */
async function settle(id: string) {
  for (let i = 0; i < 50 && ['queued', 'running'].includes(trial(id).status); i++) await vi.advanceTimersByTimeAsync(5000);
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.useFakeTimers();
  run('DELETE FROM trials');
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('trial queue', () => {
  it('infra_error twice then passed -> passed after exactly 3 attempts', async () => {
    seed('t1');
    fetchMock.mockResolvedValueOnce(infra()).mockResolvedValueOnce(infra()).mockResolvedValueOnce(passed());
    enqueue(['t1']);
    await settle('t1');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const t = trial('t1');
    expect(t.status).toBe('passed');
    expect(t.attempts).toBe(3);
    expect(t.score).toBe(1);
  });

  it('infra_error three times -> final infra_error with attempts 3 (no 4th try)', async () => {
    seed('t1');
    fetchMock.mockResolvedValue(infra());
    enqueue(['t1']);
    await settle('t1');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const t = trial('t1');
    expect(t.status).toBe('infra_error');
    expect(t.attempts).toBe(3);
    expect(t.score).toBeNull();
    expect(t.reasoning).toBe('upstream 429');
  });

  it('retries back off between attempts (2s then 8s)', async () => {
    seed('t1');
    fetchMock.mockResolvedValue(infra());
    enqueue(['t1']);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(7999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    await settle('t1');   // let the queue drain so no worker slot leaks into the next test
  });

  it('a model failure (failed/timeout/grader_error) is NOT retried', async () => {
    for (const status of ['failed', 'timeout', 'grader_error', 'not_applicable']) {
      run('DELETE FROM trials');
      fetchMock.mockReset().mockResolvedValue(reply({ status, score: status === 'timeout' ? 0 : null }));
      seed('t1');
      enqueue(['t1']);
      await settle('t1');
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(trial('t1')).toMatchObject({ status, attempts: 1 });
    }
  });

  it('worker down (fetch rejects) is treated as infra_error and retried', async () => {
    seed('t1');
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    enqueue(['t1']);
    await settle('t1');
    const t = trial('t1');
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(t.status).toBe('infra_error');
    expect(t.reasoning).toContain('worker unreachable: ECONNREFUSED');
  });

  it('worker HTTP 500 is infra_error; recovery on a later attempt wins', async () => {
    seed('t1');
    fetchMock.mockResolvedValueOnce(reply({}, 500)).mockResolvedValueOnce(passed());
    enqueue(['t1']);
    await settle('t1');
    expect(trial('t1')).toMatchObject({ status: 'passed', attempts: 2 });
  });

  it('persists everything the worker returned, including meta', async () => {
    seed('t1');
    fetchMock.mockResolvedValue(passed());
    enqueue(['t1']);
    await settle('t1');
    const t = trial('t1');
    expect(JSON.parse(t.meta)).toEqual({ task_hash: 'abc123', harness_version: '1.0', budget: { max_steps: 3, max_tokens: 9 } });
    expect(JSON.parse(t.usage)).toEqual({ prompt_tokens: 5, completion_tokens: 2, calls: 1 });
    expect(JSON.parse(t.events)).toEqual([{ type: 'assistant', text: 'hi' }]);
    expect(JSON.parse(t.files)).toEqual(['a.txt']);
    expect([t.final_text, t.duration_ms, t.cost_usd, t.reasoning]).toEqual(['done', 1234, 0.002, 'ok']);
  });

  it('sends trial id, task id and the config (with parsed settings) to the worker', async () => {
    seed('t1');
    fetchMock.mockResolvedValue(passed());
    enqueue(['t1']);
    await settle('t1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/trial$/);
    expect(JSON.parse(init.body)).toEqual({ trial_id: 't1', task_id: 'task-1',
      config: { harness: 'hermes', model: 'gpt-4.1-mini', settings: cfgSettings } });
  });

  it('respects the concurrency limit', async () => {
    ['a', 'b', 'c', 'd'].forEach((id, i) => seed(id, 'queued', i));
    let inflight = 0, peak = 0;
    fetchMock.mockImplementation(async () => {
      peak = Math.max(peak, ++inflight);
      await new Promise((r) => setTimeout(r, 100));
      inflight--;
      return passed();
    });
    enqueue(['a', 'b', 'c', 'd']);
    await vi.advanceTimersByTimeAsync(1000);
    expect(peak).toBe(2);
    expect(all(`SELECT status FROM trials`).every((t) => t.status === 'passed')).toBe(true);
  });
});

describe('resume', () => {
  it('re-queues trials left running by a crashed process and runs queued ones, skipping finished', async () => {
    seed('done', 'passed', 0);
    seed('stuck', 'running', 1);
    seed('waiting', 'queued', 2);
    fetchMock.mockResolvedValue(passed());
    resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(['queued', 'running', 'passed']).toContain(trial('stuck').status);   // no longer stranded in 'running' limbo
    await settle('stuck');
    await settle('waiting');
    expect(trial('stuck').status).toBe('passed');
    expect(trial('waiting').status).toBe('passed');
    expect(trial('done').attempts).toBe(0);                                      // untouched
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const sent = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body).trial_id).sort();
    expect(sent).toEqual(['stuck', 'waiting']);
  });
});
