import { describe, expect, it } from 'vitest';
import { CATEGORIES, classify } from './failures';

const call = (kind = 'tool', input: unknown = {}, phase = 'task') => ({ type: 'tool_call', id: 'c', name: 'x', input, kind, phase });
const say = (text: string) => ({ type: 'assistant', text, phase: 'task' });
const busy = [call(), call(), say('Here is my answer.')];  // normal run: 2 calls, no give-up text
const t = (over: any = {}) => ({ status: 'failed', score: 0, events: busy, usage: null, ...over });

describe('classify', () => {
  it('timeout', () => expect(classify(t({ status: 'timeout' }), [])).toBe('timeout'));
  it('grader_error', () => expect(classify(t({ status: 'grader_error' }), [])).toBe('grader_error'));
  it('budget_exhausted', () =>
    expect(classify(t({ events: [...busy, { type: 'error', message: 'budget_exhausted: steps', phase: 'task' }] }), [])).toBe('budget_exhausted'));
  it('hallucinated_tool_args', () =>
    expect(classify(t({ events: [...busy, { type: 'tool_result', id: 'c', name: 'x', output: 'Missing required field "path"', error: true, phase: 'task' }] }), []))
      .toBe('hallucinated_tool_args'));
  it('capability_disabled: task needs a feature the config turned off', () => {
    expect(classify(t(), ['skills'], { skills: false, memory: true })).toBe('capability_disabled');
    expect(classify(t(), ['memory'], { skills: true, memory: false })).toBe('capability_disabled');
    expect(classify(t(), ['skills'], { skills: true, memory: false })).toBe('capability_unused');
  });

  it('plain "not found" tool errors are not hallucinated args', () => {
    const r = { type: 'tool_result', phase: 'task', error: true, output: 'No such file or directory: x not found' };
    expect(classify(t({ events: [r, call(), call()] }), [])).not.toBe('hallucinated_tool_args');
  });

  it('capability_unused applies to skills only', () => {
    expect(classify(t(), ['skills'])).toBe('capability_unused');
    expect(classify(t(), ['memory'])).toBe('wrong_answer');   // memory reads are implicit: cannot be 'unused'
    expect(classify(t({ events: [call('skill'), call()] }), ['skills'])).toBe('wrong_answer');
    expect(classify(t({ events: [call('tool', { path: 'skills/a/SKILL.md' }), call()] }), ['skills'])).toBe('wrong_answer');
    expect(classify(t({ events: [call('memory'), call()] }), ['memory'])).toBe('wrong_answer');
  });
  it('gave_up_early', () => {
    expect(classify(t({ events: [say('I am done.')] }), [])).toBe('gave_up_early');                       // no tool use at all
    expect(classify(t({ events: [call(), call(), say('Could you please provide the file?')] }), [])).toBe('gave_up_early');
    expect(classify(t({ events: [call(), say('done')] }), [])).toBe('wrong_answer');                    // one real write is an attempt, not giving up
    expect(classify(t({ events: [call(), call(), call(), call(), say('Could you clarify?')] }), [])).toBe('wrong_answer');
  });
  it('judge_borderline', () => {
    expect(classify(t({ score: 0.5 }), [])).toBe('judge_borderline');
    expect(classify(t({ score: 0.75 }), [])).toBe('wrong_answer');
  });
  it('wrong_answer', () => expect(classify(t(), [])).toBe('wrong_answer'));
  it('passed / infra_error / not_applicable => null', () => {
    for (const status of ['passed', 'infra_error', 'not_applicable']) expect(classify(t({ status }), [])).toBeNull();
  });
  it('first match wins', () => {
    const errs = [...busy, { type: 'error', message: 'budget_exhausted', phase: 'task' }, { type: 'tool_result', output: 'invalid', error: true, phase: 'task' }];
    expect(classify(t({ status: 'timeout', events: errs }), ['skills'])).toBe('timeout');
    expect(classify(t({ events: errs }), ['skills'])).toBe('budget_exhausted');
  });
  it('covers every category in order', () => expect(CATEGORIES).toHaveLength(9));
});
