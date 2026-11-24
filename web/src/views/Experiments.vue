<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, usd, when, type Config, type Experiment, type Task } from '../api'

defineEmits<{ open: [id: string] }>()
const exps = ref<Experiment[]>([])
const configs = ref<Config[]>([])
const tasks = ref<Task[]>([])
const error = ref('')
const f = reactive({ name: '', trials: 5, subset: false, category: '' })
const selConfigs = ref<string[]>([])
const selTasks = ref<string[]>([])
let timer: number

const categories = computed(() => [...new Set(tasks.value.map(t => t.category))])
const shownTasks = computed(() => tasks.value.filter(t => !f.category || t.category === f.category))

async function load() { try { exps.value = await api.experiments() } catch (e) { error.value = String(e) } }
onMounted(() => {
  timer = window.setInterval(load, 3000)   // registered synchronously, so onUnmounted always clears it
  load()
  Promise.all([api.configs(), api.tasks()]).then(([c, t]) => { configs.value = c; tasks.value = t }).catch(e => { error.value = String(e) })
})
onUnmounted(() => clearInterval(timer))

async function start() {
  error.value = ''
  if (!selConfigs.value.length) { error.value = 'Select at least one config'; return }
  if (f.subset && !selTasks.value.length) { error.value = 'Select at least one task or uncheck subset'; return }
  try {
    await api.createExperiment({ name: f.name, config_ids: selConfigs.value, trials: Number(f.trials),
      ...(f.subset ? { task_ids: selTasks.value } : {}) })
    await load()
  } catch (e) { error.value = String(e) }
}
</script>

<template>
  <div class="head"><h1>Experiments</h1></div>
  <section>
    <h2>New experiment</h2>
    <form @submit.prevent="start">
      <div class="fields">
        <label>Name <input v-model="f.name" required placeholder="e.g. memory on vs off" style="width: 280px" /></label>
        <label>Trials per task <input type="number" min="1" v-model="f.trials" /></label>
      </div>
      <div class="fieldset"><div class="k">Configs</div>
        <div class="chips">
          <label v-for="c in configs" :key="c.id" class="chip"><input type="checkbox" :value="c.id" v-model="selConfigs" /> {{ c.id }}</label>
          <span v-if="!configs.length" class="muted">Create a config first.</span>
        </div>
      </div>
      <div class="fieldset"><div class="k">Tasks</div>
        <label class="inline"><input type="checkbox" v-model="f.subset" /> Select a subset <span class="muted">(default: all {{ tasks.length }})</span></label>
        <template v-if="f.subset">
          <div class="toolbar" style="margin-top: 10px">
            <select v-model="f.category"><option value="">all categories</option><option v-for="c in categories" :key="c">{{ c }}</option></select>
            <a role="button" tabindex="0" @click="selTasks = [...new Set([...selTasks, ...shownTasks.map(t => t.id)])]" @keydown.enter="selTasks = [...new Set([...selTasks, ...shownTasks.map(t => t.id)])]">Select shown</a>
            <a role="button" tabindex="0" @click="selTasks = []" @keydown.enter="selTasks = []">Clear</a>
          </div>
          <div class="chips">
            <label v-for="t in shownTasks" :key="t.id" class="chip"><input type="checkbox" :value="t.id" v-model="selTasks" /> {{ t.title }} <span class="muted">{{ t.category }}</span></label>
          </div>
        </template>
      </div>
      <button class="btn" type="submit">Start experiment</button>
    </form>
    <div v-if="error" class="err">{{ error }}</div>
  </section>
  <section>
    <h2>History</h2>
    <div class="tbl"><table>
      <tr><th>Name</th><th>Status</th><th style="min-width: 200px">Progress</th><th>Configs</th><th class="num">Cost</th><th>Created</th></tr>
      <tr v-for="e in exps" :key="e.id">
        <td><a role="button" tabindex="0" @click="$emit('open', e.id)" @keydown.enter="$emit('open', e.id)">{{ e.name }}</a></td>
        <td><span class="badge" :class="e.status">{{ e.status }}</span></td>
        <td><div class="prog"><div class="bar"><div :style="{ width: (e.progress.total ? 100 * e.progress.done / e.progress.total : 0) + '%' }"></div></div>
          <span class="muted num">{{ e.progress.done }}/{{ e.progress.total }}</span>
          <span v-if="e.progress.infra_errors" class="err">{{ e.progress.infra_errors }} infra</span></div></td>
        <td class="muted">{{ e.config_ids.join(', ') }}</td><td class="num">{{ usd(e.total_cost) }}</td><td class="muted">{{ when(e.created_at) }}</td>
      </tr>
    </table></div>
    <p v-if="!exps.length" class="muted">No experiments yet.</p>
  </section>
</template>
