/** Rule-based failure classification. First matching rule wins; null = not a failure. */
export const CATEGORIES = [
  'timeout', 'grader_error', 'budget_exhausted', 'capability_disabled', 'hallucinated_tool_args',
  'capability_unused', 'gave_up_early', 'judge_borderline', 'wrong_answer',
] as const;
export type Category = (typeof CATEGORIES)[number];

type Ev = { type: string; phase?: string; [k: string]: any };
export type TrialLike = { status: string; score: number | null; events: Ev[]; usage?: unknown };

// tool-call mistakes only (a plain "file not found" is an ordinary tool error, not a hallucinated argument)
const BAD_ARGS = /invalid (input|arguments?|params?|tool)|unrecognized (flag|argument|option|parameter)|missing required|unexpected (keyword|argument)|unknown (tool|argument|parameter|option|flag)|schema (validation|error)|validation error|no such (tool|function)/i;
const GAVE_UP = /please provide|could you (please )?(provide|clarify|share)|unable to (find|locate|proceed|complete)|i (cannot|can't) (find|proceed|complete)/i;

export type Settings = { skills?: boolean; memory?: boolean };

export function classify(t: TrialLike, requires: string[], settings: Settings = { skills: true, memory: true }): Category | null {
  if (!['failed', 'timeout', 'grader_error'].includes(t.status)) return null;  // passed, infra_error, not_applicable, in-flight
  if (t.status === 'timeout') return 'timeout';
  if (t.status === 'grader_error') return 'grader_error';

  const ev = t.events ?? [];
  const task = ev.filter((e) => e.phase === 'task');
  const calls = task.filter((e) => e.type === 'tool_call');

  if (ev.some((e) => e.type === 'error' && String(e.message ?? '').startsWith('budget_exhausted'))) return 'budget_exhausted';
  // the task needs a capability this config switched off: the failure is expected, not an agent mistake
  if ((requires.includes('skills') && settings.skills === false) || (requires.includes('memory') && settings.memory === false)) return 'capability_disabled';
  if (task.some((e) => e.type === 'tool_result' && e.error === true && BAD_ARGS.test(String(typeof e.output === 'string' ? e.output : JSON.stringify(e.output))))) return 'hallucinated_tool_args';

  // Skills: consulted = a skill-read tool call, or any call that touches a skills dir. (Memory reads are implicit, so a
  // failed memory task is not 'unused': the trace shows what was injected via memory_context, and it falls to wrong_answer.)
  const usedSkill = calls.some((c) => c.kind === 'skill' || /skills\/|SKILL\.md/.test(JSON.stringify(c.input ?? '')));
  if (requires.includes('skills') && !usedSkill) return 'capability_unused';

  const lastText = String([...task].reverse().find((e) => e.type === 'assistant')?.text ?? '');
  // gave up = did nothing at all, or said it could not proceed after only a few steps (a single correct-looking write is not giving up)
  if (calls.length === 0 || (GAVE_UP.test(lastText) && calls.length <= 3)) return 'gave_up_early';
  if (t.score != null && t.score > 0.25 && t.score < 0.75) return 'judge_borderline';
  return 'wrong_answer';
}
