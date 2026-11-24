/**
 * Statistics. Unit of analysis is the TASK (trials are repeated measures within a task).
 * CIs come from a hierarchical bootstrap: resample tasks, then resample trials within each task.
 * Comparisons are paired by task: only tasks scored in BOTH configs are used.
 */
export type Row = { task_id: string; value: number };
export type CI = [number, number];

const B = 2000;
const EPS = 1e-9;   // below this a difference is floating-point noise (e.g. unequal trial counts on non-dyadic scores)
const mean = (x: number[]) => x.reduce((s, v) => s + v, 0) / x.length;

function rng(seed: number) {  // mulberry32: deterministic so results are reproducible
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const group = (rows: Row[]) => {
  const m = new Map<string, number[]>();
  for (const r of rows) if (Number.isFinite(r.value)) m.set(r.task_id, [...(m.get(r.task_id) ?? []), r.value]);
  return m;
};
const resampleMean = (x: number[], r: () => number) => {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[Math.floor(r() * x.length)];
  return s / x.length;
};
const interval = (s: number[]): CI => {
  if (!s.length) return [NaN, NaN];
  const v = [...s].sort((p, q) => p - q);
  return [v[Math.floor(0.025 * v.length)], v[Math.min(v.length - 1, Math.floor(0.975 * v.length))]];
};

/** Mean over tasks of per-task means, with 95% hierarchical-bootstrap CI. */
export function meanCI(rows: Row[], seed = 1) {
  const g = [...group(rows).values()];
  if (!g.length) return { mean: NaN, ci: [NaN, NaN] as CI, tasks: 0 };
  const r = rng(seed);
  const boots = Array.from({ length: B }, () => mean(g.map(() => 0).map(() => resampleMean(g[Math.floor(r() * g.length)], r))));
  return { mean: mean(g.map(mean)), ci: interval(boots), tasks: g.length };
}

/** Paired comparison A vs B (diff = B - A) on tasks present in both. */
export function pairedStat(a: Row[], b: Row[], seed = 1) {
  const ga = group(a), gb = group(b);
  const tasks = [...ga.keys()].filter((t) => gb.has(t)).sort();
  const empty = { meanA: NaN, meanB: NaN, diff: NaN, ci: [NaN, NaN] as CI, pairedTasks: 0, perTask: [] as any[] };
  if (!tasks.length) return empty;
  const r = rng(seed);
  const A = tasks.map((t) => ga.get(t)!), Bv = tasks.map((t) => gb.get(t)!);
  const meanA = mean(A.map(mean)), meanB = mean(Bv.map(mean));
  const diffs = Array.from({ length: B }, () => {
    let s = 0;
    for (let i = 0; i < tasks.length; i++) {
      const k = Math.floor(r() * tasks.length);
      s += resampleMean(Bv[k], r) - resampleMean(A[k], r);
    }
    return s / tasks.length;
  });
  const perTask = tasks.map((t, i) => {
    const d = Array.from({ length: 1000 }, () => resampleMean(Bv[i], r) - resampleMean(A[i], r));
    const ci = interval(d);
    const delta = mean(Bv[i]) - mean(A[i]);
    // "significant" needs >= 2 trials on BOTH sides (n=1 gives a degenerate CI) and a real, not floating-point, margin
    const enough = A[i].length >= 2 && Bv[i].length >= 2;
    return { task_id: t, n: Math.min(A[i].length, Bv[i].length), nA: A[i].length, nB: Bv[i].length, meanA: mean(A[i]), meanB: mean(Bv[i]),
             delta, ci, significant: enough && Math.abs(delta) > EPS && (ci[0] > EPS || ci[1] < -EPS) };
  });
  return { meanA, meanB, diff: meanB - meanA, ci: interval(diffs), pairedTasks: tasks.length, perTask };
}

/** McNemar exact test on per-task pass/fail (task passes if mean score >= 0.5). */
export function mcnemar(a: Row[], b: Row[]) {
  const ga = group(a), gb = group(b);
  const tasks = [...ga.keys()].filter((t) => gb.has(t));
  if (!tasks.length) return null;
  let aOnly = 0, bOnly = 0;
  for (const t of tasks) {
    const pa = mean(ga.get(t)!) >= 0.5, pb = mean(gb.get(t)!) >= 0.5;
    if (pa && !pb) aOnly++;
    if (pb && !pa) bOnly++;
  }
  const n = aOnly + bOnly, k = Math.min(aOnly, bOnly);
  if (n === 0) return { a_only: 0, b_only: 0, p: 1 };
  let tail = 0, c = 1;  // sum_{i<=k} C(n,i) / 2^n, computed iteratively
  for (let i = 0; i <= k; i++) { tail += c; c = (c * (n - i)) / (i + 1); }
  return { a_only: aOnly, b_only: bOnly, p: Math.min(1, (2 * tail) / 2 ** n) };
}

/** 'insufficient_data' (fewer than 3 paired tasks or no usable CI) is deliberately distinct from 'inconclusive'
 *  (enough data, CI spans 0): "we cannot tell" and "we looked and there is no detectable difference" are not the same. */
export const verdict = (ci: CI, pairedTasks: number): 'a_better' | 'b_better' | 'inconclusive' | 'insufficient_data' =>
  pairedTasks < 3 || !Number.isFinite(ci[0]) || !Number.isFinite(ci[1]) ? 'insufficient_data'
    : ci[0] > EPS ? 'b_better' : ci[1] < -EPS ? 'a_better' : 'inconclusive';
