import { BadRequestException } from '@nestjs/common';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// db.ts opens the database on import, so the path must be set before anything imports it.
vi.hoisted(() => {
  const { mkdtempSync } = require('node:fs');
  const { tmpdir } = require('node:os');
  const { join } = require('node:path');
  process.env.DB_PATH = join(mkdtempSync(join(tmpdir(), 'api-spec-')), 'evals.db');
});

vi.mock('./runner', () => ({ enqueue: vi.fn(), resume: vi.fn() }));
vi.mock('./catalog', async (orig) => ({
  ...(await orig<typeof import('./catalog')>()),
  listModels: () => [{ id: 'gpt-4.1-mini', price_per_1m: { input: 0.4, output: 1.6 } }],
  listTasks: () => ['a-task', 'b-task', 'c-task'].map((id) => ({ id, title: id, category: 'code', grader: 'unit_tests', requires: [] })),
}));

import { ApiController } from './api.controller';
import { all, one, run } from './db';
import { enqueue } from './runner';

const ctl = new ApiController();
const base = { name: 'baseline', harness: 'hermes', model: 'gpt-4.1-mini' };

beforeEach(() => {
  run('DELETE FROM trials');
  run('DELETE FROM experiments');
  run('DELETE FROM configs');
  vi.mocked(enqueue).mockClear();
});

describe('config versioning', () => {
  it('same name + same settings returns the existing version (no new row)', () => {
    const a = ctl.createConfig({ ...base, settings: { skills: true } });
    const b = ctl.createConfig({ ...base, settings: { skills: true } });
    expect(a.id).toBe('baseline@v1');
    expect(b.id).toBe(a.id);
    expect(all('SELECT * FROM configs')).toHaveLength(1);
  });

  it('changed settings create version 2 and leave v1 untouched (immutable)', () => {
    const v1 = ctl.createConfig({ ...base, settings: { skills: true, temperature: 0.2 } });
    const rowBefore = one('SELECT * FROM configs WHERE id=?', v1.id);
    const v2 = ctl.createConfig({ ...base, settings: { skills: true, temperature: 0.7 } });
    expect(v2.id).toBe('baseline@v2');
    expect(v2.version).toBe(2);
    expect(v2.hash).not.toBe(v1.hash);
    expect(one('SELECT * FROM configs WHERE id=?', v1.id)).toEqual(rowBefore);
    expect(v2.settings.temperature).toBe(0.7);
    expect(all('SELECT * FROM configs')).toHaveLength(2);
  });

  it('changing model or harness also bumps the version; different names version independently', () => {
    ctl.createConfig({ ...base });
    expect(ctl.createConfig({ ...base, harness: 'opencode' }).id).toBe('baseline@v2');
    expect(ctl.createConfig({ ...base, name: 'other' }).id).toBe('other@v1');
  });

  it('reverting to an earlier setting compares against the latest version, so it becomes a new version', () => {
    ctl.createConfig({ ...base, settings: { memory: false } });
    ctl.createConfig({ ...base, settings: { memory: true } });
    expect(ctl.createConfig({ ...base, settings: { memory: false } }).id).toBe('baseline@v3');
  });

  it('applies defaults: token_budget 300000, nudge false, temperature 0.2, max_turns 30', () => {
    const c = ctl.createConfig({ ...base });
    expect(c.settings).toEqual({ skills: false, memory: false, temperature: 0.2, max_turns: 30, token_budget: 300000, nudge: false });
  });

  it('an explicit temperature of 0 is kept (not replaced by the default)', () => {
    expect(ctl.createConfig({ ...base, settings: { temperature: 0 } }).settings.temperature).toBe(0);
  });

  it('omitted settings and explicit defaults hash identically', () => {
    const a = ctl.createConfig({ ...base });
    const b = ctl.createConfig({ ...base, settings: { token_budget: 300000, nudge: false, skills: false } });
    expect(b.id).toBe(a.id);
  });

  it('rejects unknown harness, unknown model and missing name', () => {
    expect(() => ctl.createConfig({ ...base, harness: 'nope' })).toThrow(BadRequestException);
    expect(() => ctl.createConfig({ ...base, model: 'gpt-9' })).toThrow(/unknown model gpt-9/);
    expect(() => ctl.createConfig({ ...base, name: '' })).toThrow(BadRequestException);
    expect(all('SELECT * FROM configs')).toHaveLength(0);
  });
});

describe('createExperiment', () => {
  const mkCfgs = () => [ctl.createConfig({ ...base }).id, ctl.createConfig({ ...base, name: 'b' }).id];

  it('creates trials_per_task x tasks x configs queued trials in trial-major order and enqueues them', () => {
    const [c1, c2] = mkCfgs();
    const e = ctl.createExperiment({ name: 'exp', config_ids: [c1, c2], trials: 2 });
    expect(e.progress).toEqual({ total: 12, done: 0, infra_errors: 0 });
    expect(e.status).toBe('running');
    const rows = all('SELECT * FROM trials WHERE experiment_id=? ORDER BY rowid', e.id);
    expect(rows).toHaveLength(12);
    expect(rows.every((r) => r.status === 'queued')).toBe(true);
    expect(rows.map((r) => r.trial_idx)).toEqual([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]);
    // within a repetition: task-major, then config
    expect(rows.slice(0, 6).map((r) => `${r.task_id}/${r.config_id}`)).toEqual([
      `a-task/${c1}`, `a-task/${c2}`, `b-task/${c1}`, `b-task/${c2}`, `c-task/${c1}`, `c-task/${c2}`]);
    expect(enqueue).toHaveBeenCalledTimes(1);
    expect(vi.mocked(enqueue).mock.calls[0][0]).toEqual(rows.map((r) => r.id));
  });

  it('restricts to the requested tasks and accepts trials 1..50 only', () => {
    const [c1] = mkCfgs();
    expect(ctl.createExperiment({ name: 'x', config_ids: [c1], task_ids: ['b-task'], trials: 3 }).progress.total).toBe(3);
    for (const bad of [0, 51, 2.5, 'abc', NaN, -1]) {
      expect(() => ctl.createExperiment({ name: 'x', config_ids: [c1], task_ids: ['b-task'], trials: bad as any }), `trials=${bad}`).toThrow(/trials must be an integer/);
    }
  });

  it('never creates a ghost experiment: a rejected request leaves no rows behind', () => {
    const [c1] = mkCfgs();
    const before = (all(`SELECT COUNT(*) n FROM experiments`)[0] as any).n;
    expect(() => ctl.createExperiment({ name: 'x', config_ids: [c1], trials: 'abc' })).toThrow();
    expect(() => ctl.createExperiment({ name: '', config_ids: [c1] })).toThrow(/name is required/);
    expect(() => ctl.createExperiment({ name: 'x', config_ids: [] })).toThrow(/at least one config/);
    expect((all(`SELECT COUNT(*) n FROM experiments`)[0] as any).n).toBe(before);
  });

  it('de-duplicates repeated config and task ids (no double-weighted trials)', () => {
    const [c1] = mkCfgs();
    const e = ctl.createExperiment({ name: 'x', config_ids: [c1, c1], task_ids: ['b-task', 'b-task'], trials: 2 });
    expect(e.config_ids).toEqual([c1]);
    expect(e.progress.total).toBe(2);
  });

  it('config settings are validated, not coerced to NaN', () => {
    const base = { name: 'v', harness: 'hermes', model: 'gpt-4.1-mini' };
    expect(() => ctl.createConfig({ ...base, settings: { max_turns: 'many' } })).toThrow(/max_turns/);
    expect(() => ctl.createConfig({ ...base, settings: { temperature: 5 } })).toThrow(/temperature/);
    expect(() => ctl.createConfig({ ...base, settings: { token_budget: -1 } })).toThrow(/token_budget/);
    expect(() => ctl.createConfig({ ...base, name: 'bad@name' })).toThrow(/name must be/);
    expect(() => ctl.createConfig({ ...base, name: 42 as any })).toThrow(/name must be/);
    expect(() => ctl.createConfig({ ...base, harness: 'opencode', settings: { memory: true } })).toThrow(/does not support memory/);
  });

  it('defaults to 5 trials per task', () => {
    const [c1] = mkCfgs();
    expect(ctl.createExperiment({ name: 'x', config_ids: [c1] }).trials_per_task).toBe(5);
  });

  it('rejects unknown config, unknown task and missing fields without creating anything', () => {
    const [c1] = mkCfgs();
    expect(() => ctl.createExperiment({ name: 'x', config_ids: ['ghost@v1'] })).toThrow(/unknown config/);
    expect(() => ctl.createExperiment({ name: 'x', config_ids: [c1], task_ids: ['zzz'] })).toThrow(/unknown task/);
    expect(() => ctl.createExperiment({ name: 'x', config_ids: [] })).toThrow(BadRequestException);
    expect(() => ctl.createExperiment({ config_ids: [c1] })).toThrow(BadRequestException);
    expect(all('SELECT * FROM experiments')).toHaveLength(0);
    expect(enqueue).not.toHaveBeenCalled();
  });

  it('pins the exact config versions: a later config change does not alter the experiment', () => {
    const v1 = ctl.createConfig({ ...base, settings: { skills: false } });
    const e = ctl.createExperiment({ name: 'x', config_ids: [v1.id], trials: 1 });
    ctl.createConfig({ ...base, settings: { skills: true } });
    expect(ctl.exp(e.id).config_ids).toEqual(['baseline@v1']);
    expect(all('SELECT DISTINCT config_id FROM trials WHERE experiment_id=?', e.id)).toEqual([{ config_id: 'baseline@v1' }]);
  });
});

describe('exports and compare (review regressions)', () => {
  const res = { setHeader: () => {} };
  function seeded() {
    const a = ctl.createConfig({ ...base, name: 'A' }).id, b = ctl.createConfig({ ...base, name: 'B' }).id;
    const e = ctl.createExperiment({ name: 'e', config_ids: [a, b], task_ids: ['b-task'], trials: 2 });
    return { a, b, e };
  }

  it('CSV neutralises spreadsheet formulas, quotes every field and flattens newlines', () => {
    const { e, a } = seeded();
    run(`UPDATE trials SET status='failed', score=0, reasoning=? WHERE experiment_id=? AND config_id=?`, '=HYPERLINK("http://x","y"),\nline2', e.id, a);
    const csv = ctl.exportCsv(e.id, res);
    const bad = csv.split('\n').find((l: string) => l.includes('HYPERLINK'))!;
    expect(bad).toContain(`"'=HYPERLINK(""http://x"",""y""),`);   // formula prefixed, quotes doubled
    expect(bad).toContain(`"A@v1"`);                              // config_id is quoted too
    expect(csv.split('\n').every((l: string) => !/^line2/.test(l))).toBe(true);   // newline did not start a new row
  });

  it('exporting an unknown experiment is a 404, not an empty file', () => {
    expect(() => ctl.exportCsv('e_nope', res)).toThrow(/not found/);
  });

  it('compare rejects identical, unknown and foreign configs', () => {
    const { e, a } = seeded();
    expect(() => ctl.compare(e.id, a, a)).toThrow(/different configs/);
    expect(() => ctl.compare(e.id, a, 'ghost@v1')).toThrow(/not part of this experiment/);
    expect(() => ctl.compare(e.id, '', a)).toThrow(/required/);
  });

  it('compare with too few paired tasks says insufficient_data and reports coverage and run state', () => {
    const { e, a, b } = seeded();
    run(`UPDATE trials SET status='passed', score=1 WHERE experiment_id=?`, e.id);
    const c: any = ctl.compare(e.id, a, b);
    expect(c.verdict).toBe('insufficient_data');   // only 1 task
    expect(c.pairedTasks).toBe(1);
    expect(c.trialsUsed).toEqual({ a: 2, b: 2 });
    expect(c.running).toBe(false);
    expect(c.perTask[0]).toMatchObject({ nA: 2, nB: 2 });
  });
});
