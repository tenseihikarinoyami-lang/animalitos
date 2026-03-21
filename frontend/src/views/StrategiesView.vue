<template>
  <AppShell
    title="Estrategias y consenso"
    subtitle="Cruce entre fuentes externas, review de hoy y coincidencias con el top 5 actual del sistema."
    eyebrow="Estrategias"
  >
    <section class="glass-card section-card hero-card">
      <div>
        <p class="eyebrow">Lectura bajo demanda</p>
        <h3 class="section-title">Interpretar estrategias externas</h3>
        <p class="section-copy">
          La vista abre primero con snapshots ya guardados por el backend. Si quieres releer las fuentes externas y refrescar el consenso, usa el boton de actualizacion manual.
        </p>
      </div>
      <button class="btn-primary" :disabled="loadingState" @click="refreshStrategies">
        <span v-if="loadingState" class="spinner"></span>
        <span v-else>{{ hasLoaded ? 'Actualizar desde fuentes' : 'Leer estrategias ahora' }}</span>
      </button>
    </section>

    <p v-if="errorState" class="status-banner error">
      {{ errorState }}
    </p>

    <section v-if="hasLoaded" class="glass-card section-card filter-card">
      <div class="form-field">
        <label>Estrategia visible</label>
        <select v-model="selectedStrategyKey" class="select-shell">
          <option value="">Todas</option>
          <option
            v-for="source in strategiesSummary?.sources || []"
            :key="source.key"
            :value="source.key"
          >
            {{ source.title }}
          </option>
        </select>
      </div>
    </section>

    <section v-if="hasLoaded" class="metric-grid analytics-metrics">
      <article class="glass-card metric-card">
        <p class="eyebrow">Review</p>
        <h3 class="metric-value">{{ reviewSummary?.evaluated_draws || 0 }}</h3>
        <p class="metric-label">Sorteos evaluados hoy</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Top 1</p>
        <h3 class="metric-value">{{ formatPercent(reviewSummary?.hit_top_1_rate) }}</h3>
        <p class="metric-label">Acierto inmediato</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Top 3</p>
        <h3 class="metric-value">{{ formatPercent(reviewSummary?.hit_top_3_rate) }}</h3>
        <p class="metric-label">Acierto ampliado</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Top 5</p>
        <h3 class="metric-value">{{ formatPercent(reviewSummary?.hit_top_5_rate) }}</h3>
        <p class="metric-label">Cobertura del sistema</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Fuentes</p>
        <h3 class="metric-value">{{ strategiesSummary?.sources?.length || 0 }}</h3>
        <p class="metric-label">Estrategias leidas</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Consenso</p>
        <h3 class="metric-value">{{ strategiesSummary?.consensus?.length || 0 }}</h3>
        <p class="metric-label">Animales destacados</p>
      </article>
    </section>

    <section v-if="hasLoaded" class="split-grid">
      <article class="glass-card section-card col-5">
        <p class="eyebrow">Hoy</p>
        <h3 class="section-title">Resumen de aciertos del sistema</h3>
        <div class="method-stack">
          <div
            v-for="lottery in reviewSummary?.by_lottery || []"
            :key="lottery.canonical_lottery_name"
            class="method-line expanded-line"
          >
            <span>{{ lottery.canonical_lottery_name }}</span>
            <strong>{{ formatPercent(lottery.hit_top_5_rate) }} en top 5</strong>
          </div>
        </div>
        <div v-if="reviewSummary?.notes?.length" class="note-stack">
          <p v-for="note in reviewSummary.notes" :key="note" class="section-copy compact-copy">
            {{ note }}
          </p>
        </div>
      </article>

      <article class="glass-card section-card col-7">
        <p class="eyebrow">Fuentes</p>
        <h3 class="section-title">Rendimiento diario de estrategias externas</h3>
        <div class="strategy-grid">
          <div
            v-for="item in filteredPerformance"
            :key="item.key"
            class="strategy-card"
          >
            <div class="strategy-head">
              <strong>{{ item.title }}</strong>
              <span class="pill">{{ formatPercent(item.hit_rate_today) }}</span>
            </div>
            <p class="section-copy compact-copy">
              {{ item.hit_count_today }} coincidencias sobre {{ item.evaluated_results_today }} resultados ya confirmados hoy.
            </p>
            <p v-if="item.overlap_with_system_top5?.length" class="section-copy compact-copy">
              Cruce con top 5 actual: {{ item.overlap_with_system_top5.join(' | ') }}
            </p>
            <div class="signal-chip-row">
              <span
                v-for="animal in item.matching_animals_today.slice(0, 6)"
                :key="`${item.key}-${animal.animal_number}`"
                class="signal-chip signal-high"
              >
                {{ `${animal.animal_number.toString().padStart(2, '0')} ${animal.animal_name}` }}
              </span>
            </div>
          </div>
        </div>
      </article>
    </section>

    <section v-if="hasLoaded" class="split-grid">
      <article class="glass-card section-card col-12">
        <p class="eyebrow">Consenso</p>
        <h3 class="section-title">Animales repetidos entre estrategias</h3>
        <div class="strategy-grid">
          <div
            v-for="item in strategiesSummary?.consensus || []"
            :key="`consensus-${item.animal_number}`"
            class="strategy-card"
          >
            <div class="strategy-head">
              <div class="title-with-icon">
                <img
                  :src="animalIconUrl(item.animal_name)"
                  :alt="item.animal_name"
                  class="animal-inline-icon"
                  @error="handleIconError"
                />
                <strong>{{ `${item.animal_number.toString().padStart(2, '0')} ${item.animal_name}` }}</strong>
              </div>
              <span class="pill">{{ item.mention_count }} fuentes</span>
            </div>
            <p class="section-copy compact-copy">
              {{ item.sources.join(', ') }}
            </p>
            <p class="section-copy compact-copy">
              Cruce con top 5 actual: {{ item.overlap_with_system_top5?.length ? item.overlap_with_system_top5.join(', ') : 'Sin cruce directo' }}
            </p>
            <p class="section-copy compact-copy">
              Hits hoy: {{ item.hits_today }}
            </p>
          </div>
        </div>
      </article>
    </section>

    <section v-if="hasLoaded" class="glass-card section-card">
      <p class="eyebrow">Review puntual</p>
      <h3 class="section-title">Cruce del dia: resultado vs ultima prediccion previa</h3>
      <div class="review-grid">
        <div
          v-for="window in (reviewSummary?.windows || []).slice(0, 18)"
          :key="`${window.canonical_lottery_name}-${window.draw_time_local}`"
          class="review-card"
        >
          <div class="strategy-head">
            <strong>{{ `${window.canonical_lottery_name} ${window.draw_time_local}` }}</strong>
            <span class="pill" :class="{ success: window.hit_top_5, muted: !window.hit_top_5 }">
              {{ window.hit_top_5 ? 'Top 5 hit' : 'Miss' }}
            </span>
          </div>
          <p class="section-copy compact-copy">
            Salio {{ `${window.actual_animal_number.toString().padStart(2, '0')} ${window.actual_animal_name}` }}
          </p>
          <p class="section-copy compact-copy">
            Top 5 previo: {{ joinNumbers(window.top_5) }}
          </p>
          <p class="section-copy compact-copy">
            Rank real: {{ window.actual_rank || 'Fuera del top 5' }}
          </p>
        </div>
      </div>
    </section>

    <section v-if="hasLoaded && strategiesSummary?.notes?.length" class="glass-card section-card">
      <p class="eyebrow">Notas</p>
      <h3 class="section-title">Uso recomendado</h3>
      <div class="note-stack">
        <p v-for="note in strategiesSummary.notes" :key="note" class="section-copy compact-copy">
          {{ note }}
        </p>
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import { animalIconUrl, formatPercent, handleIconError } from '@/utils/monitoring'

const lotteryStore = useLotteryStore()
const strategiesSummary = computed(() => lotteryStore.strategies)
const reviewSummary = computed(() => lotteryStore.todayReview)
const loadingState = ref(false)
const errorState = ref('')
const hasLoaded = ref(false)
const selectedStrategyKey = ref('')
const filteredPerformance = computed(() => {
  const items = strategiesSummary.value?.performance || []
  if (!selectedStrategyKey.value) return items
  return items.filter((item) => item.key === selectedStrategyKey.value)
})

function joinNumbers(items = []) {
  if (!items.length) return 'Sin top previo'
  return items.map((value) => value.toString().padStart(2, '0')).join(', ')
}

async function loadStrategies() {
  loadingState.value = true
  errorState.value = ''
  try {
    const [strategiesResponse, reviewResponse] = await Promise.all([
      lotteryStore.fetchStrategies({}, { silent: true }),
      lotteryStore.fetchTodayReview({}, { silent: true }),
    ])
    if (!strategiesResponse || !reviewResponse) {
      errorState.value = 'No se pudieron cargar los snapshots de estrategias o el review del dia.'
      return
    }
    hasLoaded.value = true
  } finally {
    loadingState.value = false
  }
}

async function refreshStrategies() {
  loadingState.value = true
  errorState.value = ''
  try {
    const [strategiesResponse, reviewResponse] = await Promise.all([
      lotteryStore.fetchStrategies({ force_refresh: true }, { silent: true }),
      lotteryStore.fetchTodayReview({}, { silent: true }),
    ])
    if (!strategiesResponse || !reviewResponse) {
      errorState.value = 'No se pudieron interpretar las estrategias externas o el review del dia.'
      return
    }
    hasLoaded.value = true
  } finally {
    loadingState.value = false
  }
}

onMounted(() => {
  loadStrategies()
})
</script>

<style scoped>
.hero-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.filter-card {
  margin-bottom: 1rem;
}

.status-banner.error {
  margin: 0 0 1rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.strategy-grid,
.review-grid,
.note-stack {
  display: grid;
  gap: 0.9rem;
  margin-top: 1rem;
}

.strategy-grid {
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

.review-grid {
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

.strategy-card,
.review-card {
  padding: 1rem;
  border-radius: 20px;
  background: rgba(8, 18, 34, 0.6);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.strategy-head,
.title-with-icon {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
}

.title-with-icon {
  justify-content: flex-start;
}

.signal-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.7rem;
}

.signal-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.28rem 0.7rem;
  border-radius: 999px;
  font-size: 0.74rem;
  border: 1px solid rgba(119, 177, 232, 0.12);
  background: rgba(88, 209, 255, 0.08);
}

.signal-chip.signal-high {
  background: rgba(88, 209, 255, 0.14);
}

.animal-inline-icon {
  width: 30px;
  height: 30px;
  object-fit: contain;
  background: rgba(6, 16, 30, 0.7);
  padding: 0.15rem;
  border-radius: 10px;
}

.pill.success {
  background: rgba(61, 213, 152, 0.16);
  color: #b6f5d5;
}

.pill.muted {
  background: rgba(148, 163, 184, 0.16);
  color: #d6e3f7;
}

@media (max-width: 720px) {
  .hero-card {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
