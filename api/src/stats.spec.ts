import { describe, expect, it } from 'vitest';
import { mcnemar, meanCI, pairedStat, Row, verdict } from './stats';

const rows = (task: string, vals: number[]): Row[] => vals.map((value) => ({ task_id: task, value }));
const mk = (perTask: Record<string, number[]>): Row[] => Object.entries(perTask).flatMap(([t, v]) => rows(t, v));

describe('pairedStat', () => {
  it('identical configs: diff 0, CI spans 0', () => {
    const a = mk({ t1: [1, 0, 1, 0, 1], t2: [0, 0, 1, 1, 0], t3: [1, 1, 0, 1, 0], t4: [0, 1, 0, 0, 1] });
    const r = pairedStat(a, a);
    expect(r.diff).toBe(0);
    expect(r.ci[0]).toBeLessThanOrEqual(0);
    expect(r.ci[1]).toBeGreaterThanOrEqual(0);
  });

  it('clearly better B: CI above 0', () => {
    const tasks = Array.from({ length: 12 }, (_, i) => `t${i}`);
    const a = mk(Object.fromEntries(tasks.map((t, i) => [t, [0, 0, i % 3 === 0 ? 1 : 0, 0, 0]])));
    const b = mk(Object.fromEntries(tasks.map((t) => [t, [1, 1, 1, 1, 1]])));
    const r = pairedStat(a, b);
    expect(r.ci[0]).toBeGreaterThan(0);
    expect(r.diff).toBeGreaterThan(0.7);
  });

  it('zero variance and tiny inputs do not throw', () => {
    const a = mk({ t1: [1, 1, 1], t2: [1, 1, 1], t3: [1, 1, 1] });
    expect(() => pairedStat(a, a)).not.toThrow();
    expect(pairedStat(a, a).ci).toEqual([0, 0]);
    expect(pairedStat(mk({ t1: [1] }), mk({ t1: [0] })).pairedTasks).toBe(1);
    expect(pairedStat([], []).pairedTasks).toBe(0);
  });

  it('only pairs tasks present in both configs', () => {
    const a = mk({ t1: [1, 1], t2: [0, 0], t3: [1, 0] });
    const b = mk({ t1: [1, 1], t2: [1, 1] });
    const r = pairedStat(a, b);
    expect(r.pairedTasks).toBe(2);
    expect(r.perTask.map((p) => p.task_id).sort()).toEqual(['t1', 't2']);
  });

  it('is deterministic (seeded)', () => {
    const a = mk({ t1: [1, 0, 1], t2: [0, 0, 1], t3: [1, 1, 0] });
    const b = mk({ t1: [1, 1, 1], t2: [0, 1, 1], t3: [1, 0, 0] });
    expect(pairedStat(a, b).ci).toEqual(pairedStat(a, b).ci);
  });
});

describe('mcnemar', () => {
  it('counts discordant tasks and gives exact p', () => {
    const a = mk({ t1: [1, 1], t2: [0, 0], t3: [0, 0], t4: [0, 0], t5: [1, 1] });
    const b = mk({ t1: [1, 1], t2: [1, 1], t3: [1, 1], t4: [1, 1], t5: [0, 0] });
    const m = mcnemar(a, b)!;
    expect(m.a_only).toBe(1);
    expect(m.b_only).toBe(3);
    expect(m.p).toBeCloseTo(0.625, 3);
  });
  it('no discordant pairs -> p = 1', () => {
    const a = mk({ t1: [1], t2: [0] });
    expect(mcnemar(a, a)!.p).toBe(1);
  });
});

describe('meanCI', () => {
  it('handles empty and constant input', () => {
    expect(meanCI([]).mean).toBeNaN();
    expect(meanCI(mk({ t1: [1, 1], t2: [1, 1] })).ci).toEqual([1, 1]);
  });
});

describe('review regressions', () => {
  it('floating-point noise from unequal trial counts is not "significant"', () => {
    const a = mk({ t1: [0.1, 0.7, 0.3], t2: [0.1, 0.7, 0.3], t3: [0.1, 0.7, 0.3] });
    const b = mk({ t1: [0.1, 0.7, 0.3, 0.1, 0.7], t2: [0.1, 0.7, 0.3, 0.1, 0.7], t3: [0.1, 0.7, 0.3, 0.1, 0.7] });
    const r = pairedStat(a, b);
    expect(r.perTask.every((p) => !p.significant)).toBe(true);
  });

  it('a single trial per side can never be flagged significant (degenerate CI)', () => {
    const r = pairedStat(mk({ t1: [1] }), mk({ t1: [0] }));
    expect(r.perTask[0].delta).toBe(-1);
    expect(r.perTask[0].significant).toBe(false);
    expect(r.perTask[0].nA).toBe(1);
  });

  it('perfectly separated 5 vs 5 trials is significant', () => {
    const r = pairedStat(mk({ t1: [0, 0, 0, 0, 0] }), mk({ t1: [1, 1, 1, 1, 1] }));
    expect(r.perTask[0].significant).toBe(true);
  });

  it('fewer than 3 paired tasks is "insufficient_data", not "inconclusive"', () => {
    expect(verdict([-0.1, 0.1], 2)).toBe('insufficient_data');
    expect(verdict([NaN, NaN], 10)).toBe('insufficient_data');
    expect(verdict([-0.1, 0.1], 10)).toBe('inconclusive');
    expect(verdict([0.01, 0.2], 10)).toBe('b_better');
    expect(verdict([-0.2, -0.01], 10)).toBe('a_better');
    expect(verdict([-1e-12, 0.2], 10)).toBe('inconclusive');
  });
});
