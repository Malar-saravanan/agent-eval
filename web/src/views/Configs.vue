<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, when, type Config, type Meta } from '../api'

const configs = ref<Config[]>([])
const meta = ref<Meta>({ harnesses: [], models: [] })
const error = ref('')
const f = reactive({ name: '', harness: '', model: '', skills: false, memory: false, temperature: 0.2, max_turns: 30, token_budget: 300000, nudge: false })

const caps = computed(() => meta.value.harnesses.find(h => h.name === f.harness)?.capabilities ?? [])
const hasSkills = computed(() => caps.value.includes('skills'))
const hasMemory = computed(() => caps.value.includes('memory'))
watch(() => f.harness, () => { if (!hasSkills.value) f.skills = false; if (!hasMemory.value) f.memory = false })

async function load() {
  try { configs.value = await api.configs() } catch (e) { error.value = String(e) }
}
onMounted(async () => {
  try {
    meta.value = await api.meta()
    f.harness = meta.value.harnesses[0]?.name ?? ''
    f.model = meta.value.models[0]?.id ?? ''
  } catch (e) { error.value = String(e) }
  load()
})
function clone(c: Config) {
  Object.assign(f, { name: c.name, harness: c.harness, model: c.model, ...c.settings })
  // harness watcher clears unsupported flags; restore after tick not needed since config was valid
}
async function save() {
  error.value = ''
  try {
    await api.createConfig({ name: f.name, harness: f.harness, model: f.model,
      settings: { skills: f.skills, memory: f.memory, temperature: Number(f.temperature), max_turns: Number(f.max_turns),
        token_budget: Number(f.token_budget), nudge: f.nudge } })
    await load()
  } catch (e) { error.value = String(e) }
}
</script>

<template>
  <div class="head"><h1>Configs</h1><span class="muted">Configs are immutable. Saving an existing name creates the next version.</span></div>
  <section>
    <h2>New config</h2>
    <form @submit.prevent="save">
      <div class="fields">
        <label>Name <input v-model="f.name" required placeholder="e.g. hermes-full" /></label>
        <label>Harness
          <select v-model="f.harness"><option v-for="h in meta.harnesses" :key="h.name">{{ h.name }}</option></select>
        </label>
        <label>Model
          <select v-model="f.model"><option v-for="m in meta.models" :key="m.id">{{ m.id }}</option></select>
        </label>
        <label>Temperature <input type="number" step="0.1" min="0" max="2" v-model="f.temperature" /></label>
        <label>Max steps <input type="number" min="1" v-model="f.max_turns" /></label>
        <label>Token budget <input type="number" min="1000" step="10000" v-model="f.token_budget" style="width: 110px" /></label>
      </div>
      <div class="chips" style="margin-bottom: 16px">
        <label class="chip"><input type="checkbox" v-model="f.skills" :disabled="!hasSkills" /> Skills
          <span v-if="!hasSkills" class="muted">not supported</span></label>
        <label class="chip"><input type="checkbox" v-model="f.memory" :disabled="!hasMemory" /> Memory
          <span v-if="!hasMemory" class="muted">not supported</span></label>
        <label class="chip" title="Appends a hint to the task prompt to check skills and memory first"><input type="checkbox" v-model="f.nudge" /> Nudge</label>
      </div>
      <button class="btn" type="submit">Save config</button>
    </form>
    <div v-if="error" class="err">{{ error }}</div>
  </section>
  <section>
    <h2>All configs</h2>
    <div class="tbl"><table>
      <tr><th>Config</th><th>Harness</th><th>Model</th><th>Features</th><th class="num">Temp</th><th class="num">Steps</th><th class="num">Token budget</th><th>Created</th><th></th></tr>
      <tr v-for="c in configs" :key="c.id">
        <td><b>{{ c.name }}</b> <span class="muted">v{{ c.version }}</span></td>
        <td>{{ c.harness }}</td><td>{{ c.model }}</td>
        <td>
          <span v-if="c.settings.skills" class="badge skill">skills</span>
          <span v-if="c.settings.memory" class="badge memory">memory</span>
          <span v-if="c.settings.nudge" class="badge">nudge</span>
          <span v-if="!c.settings.skills && !c.settings.memory && !c.settings.nudge" class="muted">none</span>
        </td>
        <td class="num">{{ c.settings.temperature }}</td><td class="num">{{ c.settings.max_turns }}</td><td class="num">{{ (c.settings.token_budget ?? 300000).toLocaleString() }}</td>
        <td class="muted">{{ when(c.created_at) }}</td>
        <td class="num"><a role="button" tabindex="0" @click="clone(c)" @keydown.enter="clone(c)">Clone</a></td>
      </tr>
    </table></div>
  </section>
</template>
