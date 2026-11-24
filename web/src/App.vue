<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import Configs from './views/Configs.vue'
import Experiments from './views/Experiments.vue'
import Experiment from './views/Experiment.vue'
import Trial from './views/Trial.vue'

type View = 'configs' | 'experiments' | 'experiment' | 'trial'
const view = ref<View>('configs')
const expId = ref('')
const trialId = ref('')
// hash routing: #/configs  #/experiments  #/experiments/<id>  #/trials/<id>?exp=<id>
function parse() {
  const [, a = 'configs', id = ''] = location.hash.replace(/\?.*$/, '').split('/')
  if (a === 'experiments' && id) { expId.value = id; view.value = 'experiment' }
  else if (a === 'trials' && id) { trialId.value = id; expId.value = new URLSearchParams(location.hash.split('?')[1]).get('exp') ?? expId.value; view.value = 'trial' }
  else view.value = a === 'experiments' ? 'experiments' : 'configs'
}
const go = (h: string) => { location.hash = h }
onMounted(() => { parse(); window.addEventListener('hashchange', parse) })
onUnmounted(() => window.removeEventListener('hashchange', parse))
const tab = (v: 'configs' | 'experiments') => (v === 'configs' ? view.value === 'configs' : view.value !== 'configs')
</script>

<template>
  <header class="top"><div class="in">
    <div class="brand"><i></i>Agent Evals</div>
    <nav>
      <button :class="{ active: tab('configs') }" @click="go('/configs')">Configs</button>
      <button :class="{ active: tab('experiments') }" @click="go('/experiments')">Experiments</button>
    </nav>
  </div></header>
  <main>
    <Configs v-if="view === 'configs'" />
    <Experiments v-else-if="view === 'experiments'" @open="id => go('/experiments/' + id)" />
    <Experiment v-else-if="view === 'experiment'" :key="expId" :id="expId" @back="go('/experiments')" @trial="id => go('/trials/' + id + '?exp=' + expId)" />
    <Trial v-else :key="trialId" :id="trialId" @back="go('/experiments/' + expId)" />
  </main>
</template>
