<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, fmt, secs, usd, type Trial } from '../api'

const props = defineProps<{ id: string }>()
defineEmits<{ back: [] }>()
const t = ref<Trial>()
const error = ref('')
onMounted(async () => { try { t.value = await api.trial(props.id) } catch (e) { error.value = String(e) } })

const show = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))
const tokens = computed(() => (t.value?.usage ? t.value.usage.prompt_tokens + t.value.usage.completion_tokens : null))
const grade = computed(() => t.value?.events.find(e => e.type === 'grade'))
</script>

<template>
  <a class="back" role="button" tabindex="0" @click="$emit('back')" @keydown.enter="$emit('back')">&larr; Experiment</a>
  <div v-if="error" class="err">{{ error }}</div>
  <template v-if="t">
    <div class="head"><h1>{{ t.task_id }}</h1><span class="badge" :class="t.status">{{ t.status }}</span>
      <span class="muted">{{ t.config_id }} · trial #{{ t.trial_idx }}</span></div>
    <div class="tiles">
      <div class="tile"><div class="k">Score</div><div class="v">{{ fmt(t.score, 2) }}</div></div>
      <div class="tile"><div class="k">Cost</div><div class="v">{{ usd(t.cost_usd) }}</div></div>
      <div class="tile"><div class="k">Tokens</div><div class="v">{{ tokens ?? '-' }}</div></div>
      <div class="tile"><div class="k">Duration</div><div class="v">{{ secs(t.duration_ms) }}</div></div>
      <div class="tile"><div class="k">LLM calls</div><div class="v">{{ t.usage ? t.usage.calls : '-' }}</div></div>
    </div>
    <p v-if="t.meta" class="muted" style="margin: -6px 0 16px">
      {{ t.meta.harness_version }} · deployment {{ t.meta.model_deployment }}<span v-if="t.meta.model_resolved"> ({{ t.meta.model_resolved }})</span>
      · task {{ t.meta.task_hash }} · budget {{ t.meta.budget?.max_steps }} steps / {{ t.meta.budget?.max_tokens?.toLocaleString() }} tokens<span v-if="t.meta.nudge"> · nudge</span>
    </p>
    <div v-if="t.reasoning && !grade" class="ev grade fail"><b>Reasoning</b><div>{{ t.reasoning }}</div></div>

    <section>
      <h2>Trajectory</h2>
      <div v-for="(e, i) in t.events" :key="i">
        <div v-if="e.type === 'assistant'" class="ev assistant">
          <span class="who">Assistant</span><span v-if="e.phase === 'seed'" class="badge seed">seed session</span><pre>{{ e.text }}</pre>
        </div>
        <div v-else-if="e.type === 'tool_call'" class="ev tool_call">
          <span class="who">Tool call</span><code>{{ e.name }}</code>
          <span v-if="e.kind !== 'tool'" class="badge" :class="e.kind">{{ e.kind }}</span>
          <span v-if="e.phase === 'seed'" class="badge seed">seed session</span>
          <details><summary>Input</summary><pre>{{ show(e.input) }}</pre></details>
        </div>
        <div v-else-if="e.type === 'tool_result'" class="ev tool_result" :class="{ error: e.error }">
          <span class="who">Result</span><code>{{ e.name }}</code>
          <span v-if="e.error" class="badge bad">error</span>
          <details><summary>Output</summary><pre>{{ show(e.output) }}</pre></details>
        </div>
        <div v-else-if="e.type === 'error'" class="ev error">
          <span class="who err">Error</span><pre>{{ e.message }}</pre>
        </div>
        <div v-else class="ev grade" :class="{ fail: !e.passed }">
          <span class="who">Grade: {{ e.passed ? 'passed' : 'failed' }}</span><span class="muted">score {{ fmt(e.score, 2) }}</span>
          <pre>{{ e.reasoning }}</pre>
        </div>
      </div>
      <p v-if="!t.events.length" class="muted">No events recorded.</p>
    </section>

    <section>
      <h2>Output</h2>
      <h3 style="margin-top: 0">Files</h3>
      <ul v-if="t.files.length"><li v-for="f in t.files" :key="f"><code>{{ f }}</code></li></ul>
      <span v-else class="muted">none</span>
      <h3>Final message</h3>
      <pre>{{ t.final_text || '(empty)' }}</pre>
    </section>
  </template>
</template>
