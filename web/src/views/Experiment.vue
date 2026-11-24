<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, fmt, secs, usd, type Comparison, type Experiment, type Failures, type Stat, type Summary, type TrialRow } from '../api'

const props = defineProps<{ id: string }>()
defineEmits<{ back: []; trial: [id: string] }>()

const exp = ref<Experiment>()
const summary = ref<Summary>()
const trials = ref<TrialRow[]>([])
const cmp = ref<Comparison>()
const failures = ref<Failures>()
const error = ref('')
const a = ref('')
const b = ref('')
const fCfg = ref('')
const fTask = ref('')
const fStatus = ref('')
let timer = 0
let disposed = false   // set on unmount so a request that was in flight can never start a timer afterwards
let busy = false       // one refresh at a time: a slow server must not stack overlapping polls

async function loadCompare() {
  if (!a.value || !b.value || a.value === b.value) { cmp.value = undefined; return }
  try { cmp.value = await api.compare(props.id, a.value, b.value) } catch (e) { error.value = String(e) }
}
function stop() { clearInterval(timer); timer = 0 }
async function refresh() {
  if (busy || disposed) return
  busy = true
  try {
    exp.value = await api.experiment(props.id)
    if (!a.value && !b.value && exp.value.config_ids.length >= 2) [a.value, b.value] = exp.value.config_ids
    ;[summary.value, trials.value, failures.value] = await Promise.all([api.summary(props.id), api.trials(props.id), api.failures(props.id)])
    await loadCompare()   // the verdict must follow the data while the experiment is still running
    if (exp.value.status === 'done') stop()
  } catch (e) { error.value = String(e) } finally { busy = false }
}
onMounted(async () => {
  await refresh()
  if (!disposed && exp.value?.status === 'running') timer = window.setInterval(refresh, 3000)
})
onUnmounted(() => { disposed = true; stop() })

watch([a, b], () => { cmp.value = undefined; loadCompare() })

const pct = computed(() => (exp.value && exp.value.progress.total ? (100 * exp.value.progress.done) / exp.value.progress.total : 0))
const ci = (s: { ci: [number, number] }, d = 3) => `[${fmt(s.ci[0], d)}, ${fmt(s.ci[1], d)}]`
const taskIds = computed(() => [...new Set(trials.value.map(t => t.task_id))])
const shown = computed(() => trials.value.filter(t =>
  (!fCfg.value || t.config_id === fCfg.value) && (!fTask.value || t.task_id === fTask.value) && (!fStatus.value || t.status === fStatus.value)))
const statuses = ['queued', 'running', 'passed', 'failed', 'timeout', 'infra_error', 'grader_error', 'not_applicable']

const LEGEND: Record<string, string> = {
  timeout: 'trial hit its time limit',
  grader_error: 'the grader itself failed',
  budget_exhausted: 'step or token budget ran out',
  hallucinated_tool_args: 'a tool call was rejected for bad arguments (flags, schema, unknown tool)',
  capability_disabled: 'task needs skills/memory but this config has them switched off (expected failure)',
  capability_unused: 'skills/memory were available but the agent never used them',
  gave_up_early: 'no tool use at all, or said it could not proceed after at most 3 steps',
  judge_borderline: 'judge gave a partial score (0.25-0.75)',
  wrong_answer: 'completed normally, grader said no',
}
const failCats = computed(() => failures.value?.categories.filter(c => failures.value!.configs.some(r => r.counts[c])) ?? [])
const catOf = computed(() => new Map(failures.value?.trials.map(t => [t.id, t.category])))

const verdict = computed(() => {
  switch (cmp.value?.verdict) {
    case 'b_better': return { cls: 'good', text: 'B better' }
    case 'a_better': return { cls: 'bad', text: 'A better' }
    case 'insufficient_data': return { cls: 'noise', text: `NOT ENOUGH DATA YET (${cmp.value.pairedTasks} paired task${cmp.value.pairedTasks === 1 ? '' : 's'}, need at least 3)` }
    default: return { cls: 'noise', text: '≈ WITHIN NOISE (no significant difference)' }
  }
})
const stats = computed<[string, Stat, number][]>(() => cmp.value
  ? [['Score', cmp.value.score, 3], ['Cost (USD)', cmp.value.cost, 5], ['Latency (ms)', cmp.value.latency_ms, 0], ['Tokens', cmp.value.tokens, 0]] : [])

// forest plot: shared scale across rows
const W = 220
const range = computed(() => {
  const pt = cmp.value?.perTask ?? []
  const lo = Math.min(0, ...pt.map(p => p.ci[0])), hi = Math.max(0, ...pt.map(p => p.ci[1]))
  return { lo, span: hi - lo || 1 }
})
const x = (v: number) => 6 + ((v - range.value.lo) / range.value.span) * (W - 12)
</script>

<template>
  <a class="back" role="button" tabindex="0" @click="$emit('back')" @keydown.enter="$emit('back')">&larr; Experiments</a>
  <div v-if="error" class="err">{{ error }}</div>
  <template v-if="exp">
    <div class="head">
      <h1>{{ exp.name }}</h1><span class="badge" :class="exp.status">{{ exp.status }}</span>
      <span class="grow"></span>
      <a :href="`/api/experiments/${exp.id}/export.json`">Export JSON</a>
      <a :href="`/api/experiments/${exp.id}/export.csv`">Export CSV</a>
    </div>
    <div class="tiles">
      <div class="tile"><div class="k">Progress</div><div class="v">{{ exp.progress.done }}/{{ exp.progress.total }}</div>
        <div class="bar" style="margin-top: 6px"><div :style="{ width: pct + '%' }"></div></div></div>
      <div class="tile"><div class="k">Trials per task</div><div class="v">{{ exp.trials_per_task }}</div></div>
      <div class="tile"><div class="k">Infra errors</div><div class="v" :class="{ err: exp.progress.infra_errors }" style="margin: 0">{{ exp.progress.infra_errors }}</div></div>
      <div class="tile"><div class="k">Cost</div><div class="v">{{ usd(exp.total_cost) }}</div></div>
    </div>

    <section v-if="summary">
      <h2>Summary</h2>
      <div class="tbl"><table>
        <tr><th>Config</th><th class="num">Mean score</th><th class="num">95% CI</th><th class="num">Scored</th><th class="num">Infra</th><th class="num">Timeouts</th><th class="num">N/A</th><th class="num">Cost / trial</th><th class="num">Latency</th><th class="num">Tokens</th></tr>
        <tr v-for="c in summary.configs" :key="c.config_id">
          <td><b>{{ c.config_id }}</b><div class="muted">{{ c.harness }} · {{ c.model }}</div></td>
          <td class="num"><b>{{ c.meanScore == null ? '-' : fmt(c.meanScore) }}</b></td>
          <td class="num muted">{{ c.meanScore == null ? '-' : ci(c) }}</td>
          <td class="num">{{ c.scored }}/{{ c.trials }}</td><td class="num">{{ c.infraErrors }}</td><td class="num">{{ c.timeouts }}</td><td class="num">{{ c.notApplicable }}</td>
          <td class="num">{{ usd(c.meanCostUsd) }}</td><td class="num">{{ secs(c.meanLatencyMs) }}</td><td class="num">{{ fmt(c.meanTokens, 0) }}</td>
        </tr>
      </table></div>
    </section>

    <section>
      <h2>Compare</h2>
      <div class="toolbar">
        <label class="inline">A <select v-model="a"><option value="">select…</option><option v-for="c in exp.config_ids" :key="c">{{ c }}</option></select></label>
        <label class="inline">B <select v-model="b"><option value="">select…</option><option v-for="c in exp.config_ids" :key="c">{{ c }}</option></select></label>
        <span v-if="a && a === b" class="muted">Pick two different configs.</span>
      </div>
      <div v-if="cmp">
        <p><span class="verdict" :class="verdict.cls">{{ verdict.text }}</span>
          <span class="muted"> &nbsp;{{ cmp.pairedTasks }} paired tasks · {{ cmp.trialsUsed.a }} vs {{ cmp.trialsUsed.b }} trials used · diff = B − A</span></p>
        <p v-if="cmp.running" class="muted">Partial result: the experiment is still running and this updates as trials finish.</p>
        <div class="tbl"><table>
          <tr><th>Metric</th><th class="num">A</th><th class="num">B</th><th class="num">Diff (B−A)</th><th class="num">95% CI</th></tr>
          <tr v-for="[label, s, d] in stats" :key="label">
            <td>{{ label }}</td><td class="num">{{ fmt(s.meanA, d) }}</td><td class="num">{{ fmt(s.meanB, d) }}</td>
            <td class="num"><b>{{ fmt(s.diff, d) }}</b></td><td class="num muted">{{ ci(s, d) }}</td>
          </tr>
        </table></div>
        <p v-if="cmp.mcnemar" class="muted" style="margin-top: 10px">McNemar: A-only passes {{ cmp.mcnemar.a_only }}, B-only passes {{ cmp.mcnemar.b_only }}, p = {{ fmt(cmp.mcnemar.p) }}</p>
        <h3>Per-task delta</h3>
        <div class="tbl"><table>
          <tr><th>Task</th><th>Category</th><th class="num">n</th><th class="num">A</th><th class="num">B</th><th class="num">Delta</th><th class="num">95% CI</th><th>Δ and CI</th></tr>
          <tr v-for="p in cmp.perTask" :key="p.task_id">
            <td>{{ p.title }}</td><td class="muted">{{ p.category }}</td><td class="num">{{ p.nA === p.nB ? p.nA : p.nA + '/' + p.nB }}</td><td class="num">{{ fmt(p.meanA, 2) }}</td><td class="num">{{ fmt(p.meanB, 2) }}</td>
            <td class="num"><b>{{ fmt(p.delta, 2) }}</b> <span v-if="p.significant" class="badge" :class="p.delta > 0 ? 'good' : 'bad'">sig</span></td>
            <td class="num muted">{{ ci(p, 2) }}</td>
            <td>
              <svg :width="W" height="18">
                <line :x1="x(0)" :x2="x(0)" y1="0" y2="18" stroke="currentColor" stroke-opacity=".35" stroke-dasharray="2" />
                <line :x1="x(p.ci[0])" :x2="x(p.ci[1])" y1="9" y2="9" :stroke="p.significant ? (p.delta > 0 ? '#16a34a' : '#dc2626') : '#a1a1aa'" stroke-width="2" />
                <circle :cx="x(p.delta)" cy="9" r="4" :fill="p.significant ? (p.delta > 0 ? '#16a34a' : '#dc2626') : '#a1a1aa'" />
              </svg>
            </td>
          </tr>
        </table></div>
      </div>
      <p v-else class="muted">Choose two configs to see the verdict, confidence intervals and per-task deltas.</p>
    </section>

    <section v-if="failures">
      <h2>Failure analysis</h2>
      <p v-if="!failCats.length" class="muted">No failed trials.</p>
      <div v-else class="tbl"><table>
        <tr><th>Config</th><th class="num">Failed</th><th v-for="c in failCats" :key="c" class="num">{{ c }}</th></tr>
        <tr v-for="r in failures.configs" :key="r.config_id">
          <td><b>{{ r.config_id }}</b></td><td class="num">{{ r.failed }}</td>
          <td v-for="c in failCats" :key="c" class="num">{{ r.counts[c] }}</td>
        </tr>
      </table></div>
      <div v-if="failCats.length" class="muted" style="margin-top: 8px">
        <div v-for="c in failCats" :key="c"><b>{{ c }}</b>: {{ LEGEND[c] }}</div>
      </div>
    </section>

    <section>
      <h2>Trials</h2>
      <div class="toolbar">
        <select v-model="fCfg"><option value="">All configs</option><option v-for="c in exp.config_ids" :key="c">{{ c }}</option></select>
        <select v-model="fTask"><option value="">All tasks</option><option v-for="t in taskIds" :key="t">{{ t }}</option></select>
        <select v-model="fStatus"><option value="">All statuses</option><option v-for="s in statuses" :key="s">{{ s }}</option></select>
        <span class="muted">{{ shown.length }} shown</span>
      </div>
      <div class="tbl"><table>
        <tr><th>Config</th><th>Task</th><th class="num">#</th><th>Status</th><th class="num">Score</th><th class="num">Cost</th><th class="num">Duration</th><th></th></tr>
        <tr v-for="t in shown" :key="t.id">
          <td>{{ t.config_id }}</td><td>{{ t.task_id }}</td><td class="num">{{ t.trial_idx }}</td>
          <td><span class="badge" :class="t.status">{{ t.status }}</span>
            <span v-if="catOf.get(t.id)" class="muted"> {{ catOf.get(t.id) }}</span></td>
          <td class="num">{{ fmt(t.score, 2) }}</td><td class="num">{{ usd(t.cost_usd) }}</td><td class="num">{{ secs(t.duration_ms) }}</td>
          <td class="num"><a role="button" tabindex="0" @click="$emit('trial', t.id)" @keydown.enter="$emit('trial', t.id)">View</a></td>
        </tr>
      </table></div>
    </section>
  </template>
</template>
