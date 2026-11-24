export interface Settings { skills: boolean; memory: boolean; temperature: number; max_turns: number; token_budget?: number; nudge?: boolean }
export interface Config { id: string; name: string; version: number; hash: string; harness: string; model: string; settings: Settings; created_at: string }
export interface Meta { harnesses: { name: string; capabilities: string[] }[]; models: { id: string; price_per_1m: { input: number; output: number } }[] }
export interface Task { id: string; title: string; category: string; grader: string; requires: string[] }
export interface Experiment {
  id: string; name: string; status: 'running' | 'done'; trials_per_task: number; config_ids: string[]; task_ids: string[]
  created_at: string; progress: { total: number; done: number; infra_errors: number }; total_cost: number
}
export type Status = 'queued' | 'running' | 'passed' | 'failed' | 'timeout' | 'infra_error' | 'grader_error' | 'not_applicable'
export interface Usage { prompt_tokens: number; completion_tokens: number; calls: number; latency_ms: number }
export interface TrialRow {
  id: string; experiment_id: string; config_id: string; task_id: string; trial_idx: number; status: Status
  score: number | null; reasoning: string | null; duration_ms: number | null; cost_usd: number | null; usage: Usage | null
}
export type Phase = 'seed' | 'task'
export type TEvent =
  | { type: 'assistant'; text: string; phase: Phase }
  | { type: 'tool_call'; id: string; name: string; input: unknown; kind: 'tool' | 'skill' | 'memory'; phase: Phase }
  | { type: 'tool_result'; id: string; name: string; output: unknown; error: boolean; phase: Phase }
  | { type: 'error'; message: string; phase: Phase }
  | { type: 'grade'; score: number | null; passed: boolean; reasoning: string }
export interface TrialMeta { harness_version?: string; model_deployment?: string; model_resolved?: string; task_hash?: string; nudge?: boolean; budget?: { max_steps: number; max_tokens: number } }
export interface Trial extends TrialRow { final_text: string; files: string[]; events: TEvent[]; meta?: TrialMeta | null }
export interface ConfigSummary {
  config_id: string; name: string; harness: string; model: string; trials: number; scored: number; meanScore: number | null
  ci: [number, number]; infraErrors: number; timeouts: number; notApplicable: number
  meanCostUsd: number; totalCostUsd: number; meanLatencyMs: number; meanTokens: number
}
export interface Summary { experiment: Experiment; configs: ConfigSummary[] }
export interface Stat { meanA: number; meanB: number; diff: number; ci: [number, number] }
export interface Comparison {
  a: string; b: string; pairedTasks: number; score: Stat; cost: Stat; latency_ms: Stat; tokens: Stat
  verdict: 'b_better' | 'a_better' | 'inconclusive' | 'insufficient_data'
  running: boolean; trialsUsed: { a: number; b: number }
  mcnemar: { a_only: number; b_only: number; p: number } | null
  perTask: { task_id: string; title: string; category: string; n: number; nA: number; nB: number; meanA: number; meanB: number; delta: number; ci: [number, number]; significant: boolean }[]
}
export type Category = 'timeout' | 'grader_error' | 'budget_exhausted' | 'capability_disabled' | 'hallucinated_tool_args' | 'capability_unused' | 'gave_up_early' | 'judge_borderline' | 'wrong_answer'
export interface Failures {
  categories: Category[]
  configs: { config_id: string; failed: number; counts: Record<Category, number> }[]
  trials: { id: string; config_id: string; task_id: string; category: Category }[]
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 300)}`)
  return r.json()
}
const post = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const q = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString()

export const api = {
  meta: () => req<Meta>('/api/meta'),
  tasks: () => req<Task[]>('/api/tasks'),
  configs: () => req<Config[]>('/api/configs'),
  createConfig: (b: { name: string; harness: string; model: string; settings: Settings }) => req<Config>('/api/configs', post(b)),
  experiments: () => req<Experiment[]>('/api/experiments'),
  createExperiment: (b: { name: string; config_ids: string[]; task_ids?: string[]; trials: number }) => req<Experiment>('/api/experiments', post(b)),
  experiment: (id: string) => req<Experiment>(`/api/experiments/${id}`),
  summary: (id: string) => req<Summary>(`/api/experiments/${id}/summary`),
  compare: (id: string, a: string, b: string) => req<Comparison>(`/api/experiments/${id}/compare?${q({ a, b })}`),
  trials: (id: string, config_id = '', task_id = '') => req<TrialRow[]>(`/api/experiments/${id}/trials?${q({ config_id, task_id })}`),
  failures: (id: string) => req<Failures>(`/api/experiments/${id}/failures`),
  trial: (id: string) => req<Trial>(`/api/trials/${id}`),
}

export const fmt = (n: number | null | undefined, d = 3) => (n == null ? '-' : n.toFixed(d))
export const usd = (n: number | null | undefined) => (n == null ? '-' : '$' + n.toFixed(4))
export const when = (s?: string) => (s ? new Date(s).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '-')
export const secs = (ms?: number | null) => (ms == null ? '-' : (ms / 1000).toFixed(1) + 's')
