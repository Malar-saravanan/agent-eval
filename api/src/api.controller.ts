import { BadRequestException, Body, Controller, Get, NotFoundException, Param, Post, Query, Res } from '@nestjs/common';
import { createHash, randomUUID } from 'node:crypto';
import { HARNESSES, listModels, listTasks } from './catalog';
import { all, db, json, one, run } from './db';
import { CATEGORIES, Category, classify } from './failures';
import { enqueue } from './runner';
import { mcnemar, meanCI, pairedStat, Row, verdict } from './stats';

const DONE = `status NOT IN ('queued','running')`;
const mean = (x: number[]) => (x.length ? x.reduce((a, b) => a + b, 0) / x.length : null);

const bad = (m: string) => new BadRequestException(m);
/** Parse a numeric input: reject NaN/out-of-range/non-integers instead of silently storing garbage. */
function num(v: unknown, def: number, lo: number, hi: number, name: string, int = false): number {
  const x = v === undefined || v === null || v === '' ? def : Number(v);
  if (!Number.isFinite(x) || x < lo || x > hi || (int && !Number.isInteger(x))) throw bad(`${name} must be ${int ? 'an integer' : 'a number'} between ${lo} and ${hi}`);
  return x;
}
const uniq = <T>(xs: T[]) => [...new Set(xs)];
// spreadsheet apps execute cells starting with = + - @ : neutralise them in CSV exports
const csvCell = (v: any) => {
  let t = String(v ?? '').replace(/\r?\n|\r/g, ' ');
  if (/^[=+\-@\t]/.test(t)) t = "'" + t;
  return `"${t.replace(/"/g, '""')}"`;
};
const finite = (x: number | null | undefined): x is number => typeof x === 'number' && Number.isFinite(x);

const cfgOut = (c: any) => ({ ...c, settings: json(c.settings) });
const trialRow = (t: any) => ({ ...t, usage: json(t.usage), files: undefined, events: undefined, final_text: undefined });

function experiment(id: string) {
  const e = one(`SELECT * FROM experiments WHERE id=?`, id);
  if (!e) throw new NotFoundException('experiment not found');
  const p = one(`SELECT COUNT(*) total, SUM(${DONE}) done, SUM(status='infra_error') infra, COALESCE(SUM(cost_usd),0) cost
                 FROM trials WHERE experiment_id=?`, id);
  return { id: e.id, name: e.name, trials_per_task: e.trials_per_task, config_ids: json(e.config_ids), task_ids: json(e.task_ids),
           created_at: e.created_at, status: (p.done ?? 0) >= p.total ? 'done' : 'running',
           progress: { total: p.total, done: p.done ?? 0, infra_errors: p.infra ?? 0 }, total_cost: p.cost };
}

/** Trials usable for stats: not N/A, not infra errors. Value picked per metric. */
function rowsFor(expId: string, configId: string, pick: (t: any) => number | null | undefined): Row[] {
  return all(`SELECT * FROM trials WHERE experiment_id=? AND config_id=? AND status NOT IN ('queued','running','infra_error','not_applicable')`,
    expId, configId).flatMap((t) => {
    const v = pick({ ...t, usage: json(t.usage) });
    return v == null ? [] : [{ task_id: t.task_id, value: v }];
  });
}
const METRICS: Record<string, (t: any) => number | null> = {
  score: (t) => t.score,
  cost: (t) => t.cost_usd,
  latency_ms: (t) => t.duration_ms,
  tokens: (t) => (t.usage ? t.usage.prompt_tokens + t.usage.completion_tokens : null),
};

@Controller('api')
export class ApiController {
  @Get('meta') meta() { return { harnesses: HARNESSES, models: listModels() }; }
  @Get('tasks') tasks() { return listTasks(); }

  // ---- configs (immutable; same name => new version) ----
  @Get('configs') configs() { return all(`SELECT * FROM configs ORDER BY created_at DESC, version DESC`).map(cfgOut); }

  @Post('configs')
  createConfig(@Body() b: any) {
    const h = HARNESSES.find((x) => x.name === b?.harness);
    if (!h) throw bad(`harness must be one of: ${HARNESSES.map((x) => x.name).join(', ')}`);
    if (typeof b.name !== 'string' || !/^[A-Za-z0-9._ -]{1,60}$/.test(b.name.trim())) throw bad('name must be 1-60 characters: letters, digits, space, . _ - (no "@": it separates the version)');
    if (!listModels().some((m) => m.id === b.model)) throw bad(`unknown model ${b.model}`);
    b.name = b.name.trim();
    const s = { skills: !!b.settings?.skills, memory: !!b.settings?.memory,
                temperature: num(b.settings?.temperature, 0.2, 0, 2, 'temperature'),
                max_turns: num(b.settings?.max_turns, 30, 1, 200, 'max_turns', true),
                token_budget: num(b.settings?.token_budget, 300000, 1000, 5_000_000, 'token_budget', true), nudge: !!b.settings?.nudge };
    if ((s.skills && !h.capabilities.includes('skills')) || (s.memory && !h.capabilities.includes('memory')))
      throw bad(`${h.name} does not support ${s.skills && !h.capabilities.includes('skills') ? 'skills' : 'memory'}`);
    const hash = createHash('sha256').update(JSON.stringify([b.harness, b.model, s])).digest('hex').slice(0, 12);
    const last = one(`SELECT * FROM configs WHERE name=? ORDER BY version DESC LIMIT 1`, b.name);
    if (last?.hash === hash) return cfgOut(last);  // unchanged => no new version
    const version = (last?.version ?? 0) + 1, id = `${b.name}@v${version}`;
    run(`INSERT INTO configs VALUES (?,?,?,?,?,?,?,?)`, id, b.name, version, hash, b.harness, b.model, JSON.stringify(s), new Date().toISOString());
    return cfgOut(one(`SELECT * FROM configs WHERE id=?`, id));
  }

  // ---- experiments ----
  @Get('experiments') experiments() {
    return all(`SELECT id FROM experiments ORDER BY created_at DESC`).map((e) => experiment(e.id));
  }

  @Post('experiments')
  createExperiment(@Body() b: any) {
    if (typeof b?.name !== 'string' || !b.name.trim()) throw bad('name is required');
    const configIds: string[] = uniq(Array.isArray(b.config_ids) ? b.config_ids.map(String) : []);
    if (!configIds.length) throw bad('config_ids must list at least one config');
    for (const c of configIds) if (!one(`SELECT 1 x FROM configs WHERE id=?`, c)) throw bad(`unknown config ${c}`);
    const known = listTasks().map((t) => t.id);
    if (!known.length) throw bad('no tasks are available (is the tasks directory mounted?)');
    const taskIds: string[] = Array.isArray(b.task_ids) && b.task_ids.length ? uniq(b.task_ids.map(String)) : known;
    for (const t of taskIds) if (!known.includes(t)) throw bad(`unknown task ${t}`);
    const n = num(b.trials, 5, 1, 50, 'trials', true);
    const id = `e_${randomUUID().slice(0, 8)}`;
    const ids: string[] = [];
    db.exec('BEGIN');   // one transaction: an experiment either exists with all its trials or not at all
    try {
      run(`INSERT INTO experiments VALUES (?,?,?,?,?,?)`, id, b.name.trim(), n, JSON.stringify(configIds), JSON.stringify(taskIds), new Date().toISOString());
      for (let i = 0; i < n; i++)  // trial-major order so partial results stay balanced across configs
        for (const t of taskIds) for (const c of configIds) {
          const tid = `t_${randomUUID().slice(0, 10)}`;
          run(`INSERT INTO trials (id, experiment_id, config_id, task_id, trial_idx, status) VALUES (?,?,?,?,?,'queued')`, tid, id, c, t, i);
          ids.push(tid);
        }
      db.exec('COMMIT');
    } catch (e) { db.exec('ROLLBACK'); throw e; }
    enqueue(ids);
    return experiment(id);
  }

  @Get('experiments/:id') exp(@Param('id') id: string) { return experiment(id); }

  @Get('experiments/:id/summary')
  summary(@Param('id') id: string) {
    const e = experiment(id);
    const configs = e.config_ids.map((cid: string) => {
      const c = cfgOut(one(`SELECT * FROM configs WHERE id=?`, cid));
      const ts = all(`SELECT status, cost_usd, duration_ms, usage FROM trials WHERE experiment_id=? AND config_id=?`, id, cid);
      const used = ts.filter((t) => !['queued', 'running', 'infra_error', 'not_applicable'].includes(t.status));
      const m = meanCI(rowsFor(id, cid, METRICS.score));
      return { config_id: cid, name: c.name, harness: c.harness, model: c.model, trials: ts.length,
               scored: rowsFor(id, cid, METRICS.score).length, meanScore: m.mean, ci: m.ci,
               infraErrors: ts.filter((t) => t.status === 'infra_error').length,
               timeouts: ts.filter((t) => t.status === 'timeout').length,
               notApplicable: ts.filter((t) => t.status === 'not_applicable').length,
               // per-trial means over the same trials the statistics use (infra errors / N/A excluded, missing values skipped)
               meanCostUsd: mean(used.map((t) => t.cost_usd).filter(finite)), totalCostUsd: ts.reduce((s, t) => s + (t.cost_usd ?? 0), 0),
               meanLatencyMs: mean(used.map((t) => t.duration_ms).filter(finite)),
               meanTokens: mean(used.map((t) => { const u = json(t.usage); return u ? u.prompt_tokens + u.completion_tokens : null; }).filter(finite)) };
    });
    return { experiment: e, configs };
  }

  @Get('experiments/:id/compare')
  compare(@Param('id') id: string, @Query('a') a: string, @Query('b') b: string) {
    const e = experiment(id);
    if (!a || !b) throw bad('a and b config ids are required');
    if (a === b) throw bad('a and b must be different configs');
    for (const c of [a, b]) if (!e.config_ids.includes(c)) throw bad(`${c} is not part of this experiment`);
    const stat = (k: string) => { const r = pairedStat(rowsFor(id, a, METRICS[k]), rowsFor(id, b, METRICS[k])); return r; };
    const score = stat('score');
    const titles = new Map(listTasks().map((t) => [t.id, t]));
    const strip = ({ meanA, meanB, diff, ci }: any) => ({ meanA, meanB, diff, ci });
    return {
      a, b, pairedTasks: score.pairedTasks, running: e.status === 'running',
      trialsUsed: { a: rowsFor(id, a, METRICS.score).length, b: rowsFor(id, b, METRICS.score).length },
      score: strip(score), cost: strip(stat('cost')),
      latency_ms: strip(stat('latency_ms')), tokens: strip(stat('tokens')),
      verdict: verdict(score.ci, score.pairedTasks),
      mcnemar: mcnemar(rowsFor(id, a, METRICS.score), rowsFor(id, b, METRICS.score)),
      perTask: score.perTask.map((p: any) => ({ ...p, title: titles.get(p.task_id)?.title ?? p.task_id, category: titles.get(p.task_id)?.category })),
    };
  }

  @Get('experiments/:id/trials')
  trials(@Param('id') id: string, @Query('config_id') c?: string, @Query('task_id') t?: string) {
    return all(`SELECT * FROM trials WHERE experiment_id=? AND (? IS NULL OR config_id=?) AND (? IS NULL OR task_id=?)
                ORDER BY task_id, config_id, trial_idx`, id, c ?? null, c ?? null, t ?? null, t ?? null).map(trialRow);
  }

  @Get('experiments/:id/failures')
  failures(@Param('id') id: string) {
    const e = experiment(id);
    const requires = new Map(listTasks().map((t) => [t.id, t.requires ?? []]));
    const settings = new Map(all(`SELECT id, settings FROM configs`).map((r) => [r.id, json(r.settings) ?? {}]));
    const trials = all(`SELECT id, config_id, task_id, status, score, usage, events FROM trials WHERE experiment_id=? AND status IN ('failed','timeout','grader_error')`, id)
      .flatMap((t) => {
        const category = classify({ ...t, usage: json(t.usage), events: json(t.events) ?? [] }, requires.get(t.task_id) ?? [], settings.get(t.config_id));
        return category ? [{ id: t.id, config_id: t.config_id, task_id: t.task_id, category }] : [];
      });
    const configs = e.config_ids.map((config_id: string) => {
      const counts = Object.fromEntries(CATEGORIES.map((c) => [c, 0])) as Record<Category, number>;
      const mine = trials.filter((t) => t.config_id === config_id);
      for (const t of mine) counts[t.category]++;
      return { config_id, failed: mine.length, counts };
    });
    return { categories: CATEGORIES, configs, trials };
  }

  @Get('trials/:id')
  trial(@Param('id') id: string) {
    const t = one(`SELECT * FROM trials WHERE id=?`, id);
    if (!t) throw new NotFoundException('trial not found');
    return { ...t, usage: json(t.usage), meta: json(t.meta), files: json(t.files) ?? [], events: json(t.events) ?? [], final_text: t.final_text ?? '' };
  }

  @Get('experiments/:id/export.json')
  exportJson(@Param('id') id: string, @Res({ passthrough: true }) res: any) {
    res.setHeader('Content-Disposition', `attachment; filename="${id}.json"`);
    return { experiment: experiment(id), trials: all(`SELECT * FROM trials WHERE experiment_id=?`, id)
      .map((t) => ({ ...t, usage: json(t.usage), files: json(t.files), events: json(t.events) })) };
  }

  @Get('experiments/:id/export.csv')
  exportCsv(@Param('id') id: string, @Res({ passthrough: true }) res: any) {
    experiment(id);   // 404 for an unknown experiment instead of an empty file
    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', `attachment; filename="${id}.csv"`);
    const head = 'config_id,task_id,trial_idx,status,score,cost_usd,duration_ms,prompt_tokens,completion_tokens,calls,reasoning';
    const body = all(`SELECT * FROM trials WHERE experiment_id=? ORDER BY config_id, task_id, trial_idx`, id).map((t) => {
      const u = json(t.usage) ?? {};
      return [t.config_id, t.task_id, t.trial_idx, t.status, t.score, t.cost_usd, t.duration_ms, u.prompt_tokens, u.completion_tokens, u.calls, t.reasoning].map(csvCell).join(',');
    });
    return [head, ...body].join('\n');
  }
}
