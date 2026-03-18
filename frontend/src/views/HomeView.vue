<template>
  <AppShell
    title="Centro de control"
    subtitle="Resultados en tiempo real, salud del scraper y foco en las tres loterias principales."
    eyebrow="Animalitos Monitoring"
  >
    <template #actions>
      <span class="pill status-pill" :class="statusClass">
        {{ runLabel }}
      </span>
      <button class="btn-primary" :disabled="lotteryStore.loading" @click="reload">
        <span v-if="lotteryStore.loading" class="spinner"></span>
        <span v-else>Actualizar tablero</span>
      </button>
    </template>

    <section class="split-grid hero-grid">
      <article class="glass-card section-card col-7 hero-panel">
        <p class="eyebrow">Siguiente ventana</p>
        <h3 class="hero-title">
          {{ nextDraw?.canonical_lottery_name || 'Esperando horarios cargados' }}
        </h3>
        <p class="hero-copy">
          {{ nextDraw ? `Proximo sorteo ${nextDraw.draw_date} a las ${nextDraw.draw_time_local}.` : 'Sin datos del proximo sorteo.' }}
        </p>
        <div class="hero-stat-row">
          <div>
            <span class="hero-label">Cuenta regresiva</span>
            <strong>{{ countdownLabel(nextDraw?.minutes_until) }}</strong>
          </div>
          <div>
            <span class="hero-label">Resultados hoy</span>
            <strong>{{ overview?.total_results_today || 0 }}</strong>
          </div>
          <div>
            <span class="hero-label">Faltantes estimados</span>
            <strong>{{ overview?.missing_draws_today || 0 }}</strong>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-5">
        <p class="eyebrow">Ultima corrida</p>
        <h3 class="section-title">Salud operativa</h3>
        <p class="section-copy">
          {{ latestRun ? `${latestRun.trigger} finalizo en ${latestRun.duration_seconds}s.` : 'Aun no hay corridas registradas.' }}
        </p>
        <div class="run-grid">
          <div>
            <span>Encontrados</span>
            <strong>{{ latestRun?.results_found || 0 }}</strong>
          </div>
          <div>
            <span>Nuevos</span>
            <strong>{{ latestRun?.new_results || 0 }}</strong>
          </div>
          <div>
            <span>Duplicados</span>
            <strong>{{ latestRun?.duplicates || 0 }}</strong>
          </div>
          <div>
            <span>Errores</span>
            <strong>{{ latestRun?.errors?.length || 0 }}</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="metric-grid dashboard-metrics">
      <article class="glass-card metric-card">
        <p class="eyebrow">Hoy</p>
        <h3 class="metric-value">{{ overview?.total_results_today || 0 }}</h3>
        <p class="metric-label">Resultados consolidados</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Ventanas</p>
        <h3 class="metric-value">{{ nextDraw ? countdownLabel(nextDraw.minutes_until) : '--' }}</h3>
        <p class="metric-label">Tiempo al proximo sorteo</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Scraper</p>
        <h3 class="metric-value">{{ runStateText }}</h3>
        <p class="metric-label">Estado mas reciente</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Cobertura</p>
        <h3 class="metric-value">{{ completedCount }}/3</h3>
        <p class="metric-label">Loterias con resultados hoy</p>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-7">
        <p class="eyebrow">Loterias foco</p>
        <h3 class="section-title">Estado por loteria</h3>
        <div class="lottery-grid">
          <article v-for="card in overview?.primary_lotteries || []" :key="card.canonical_lottery_name" class="lottery-card">
            <div class="lottery-card-head">
              <div>
                <h4>{{ card.canonical_lottery_name }}</h4>
                <p>{{ card.total_results_today }}/{{ card.expected_results_today }} sorteos guardados</p>
              </div>
              <span class="pill">{{ formatPercent(card.completion_ratio) }}</span>
            </div>
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: formatPercent(card.completion_ratio) }"></div>
            </div>
            <dl class="lottery-meta">
              <div>
                <dt>Ultimo</dt>
                <dd>
                  {{ card.last_result ? `${card.last_result.animal_number.toString().padStart(2, '0')} ${card.last_result.animal_name}` : 'Sin registro' }}
                </dd>
              </div>
              <div>
                <dt>Hora</dt>
                <dd>{{ card.last_result?.draw_time_local || '--:--' }}</dd>
              </div>
              <div>
                <dt>Esperados a esta hora</dt>
                <dd>{{ card.expected_by_now }}</dd>
              </div>
              <div>
                <dt>Proximo</dt>
                <dd>{{ card.next_draw_time_local || '--:--' }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </article>

      <article class="glass-card section-card col-5">
        <p class="eyebrow">Actividad reciente</p>
        <h3 class="section-title">Ultimos resultados</h3>
        <div v-if="latestResults.length" class="latest-stack">
          <div v-for="item in latestResults" :key="item.dedupe_key" class="result-line">
            <div>
              <strong>{{ item.canonical_lottery_name }}</strong>
              <p>{{ item.draw_date }} · {{ item.draw_time_local }}</p>
            </div>
            <span class="number-chip">
              {{ item.animal_number.toString().padStart(2, '0') }}
            </span>
          </div>
        </div>
        <div v-else class="empty-state">
          Aun no hay resultados listos para mostrar.
        </div>
      </article>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import { countdownLabel, formatPercent } from '@/utils/monitoring'

const lotteryStore = useLotteryStore()

const overview = computed(() => lotteryStore.overview)
const nextDraw = computed(() => overview.value?.next_draw || null)
const latestRun = computed(() => overview.value?.latest_ingestion_run || null)
const latestResults = computed(() => overview.value?.latest_results || [])
const completedCount = computed(
  () => (overview.value?.primary_lotteries || []).filter((item) => item.total_results_today > 0).length,
)

const statusClass = computed(() => {
  const status = latestRun.value?.status
  if (status === 'success') return 'success'
  if (status === 'partial' || status === 'empty') return 'warning'
  if (status === 'failed') return 'danger'
  return 'warning'
})

const runLabel = computed(() => {
  if (!latestRun.value) return 'Sin corridas'
  return `Estado ${latestRun.value.status}`
})

const runStateText = computed(() => {
  if (!latestRun.value) return '--'
  return latestRun.value.status.toUpperCase()
})

async function reload() {
  await Promise.all([lotteryStore.fetchOverview(), lotteryStore.fetchTodayResults()])
}

onMounted(async () => {
  await reload()
})
</script>

<style scoped>
.hero-grid,
.dashboard-metrics {
  margin-bottom: 1rem;
}

.hero-panel {
  position: relative;
  overflow: hidden;
}

.hero-panel::after {
  content: '';
  position: absolute;
  inset: auto -10% -45% 25%;
  height: 220px;
  background: radial-gradient(circle, rgba(88, 209, 255, 0.2), transparent 60%);
  pointer-events: none;
}

.hero-title {
  margin: 0.5rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(2rem, 4vw, 3.5rem);
}

.hero-copy {
  max-width: 45rem;
  color: var(--text-muted);
  line-height: 1.7;
}

.hero-stat-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  margin-top: 1.4rem;
}

.hero-stat-row span,
.run-grid span,
.lottery-meta dt,
.result-line p {
  color: var(--text-muted);
  font-size: 0.82rem;
}

.hero-stat-row strong,
.run-grid strong {
  display: block;
  margin-top: 0.35rem;
  font-size: 1.2rem;
}

.run-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.95rem;
  margin-top: 1.2rem;
}

.lottery-grid {
  display: grid;
  gap: 0.9rem;
  margin-top: 1.2rem;
}

.lottery-card {
  padding: 1rem;
  border-radius: 20px;
  border: 1px solid rgba(119, 177, 232, 0.1);
  background: rgba(6, 16, 30, 0.5);
}

.lottery-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.lottery-card-head h4 {
  margin: 0;
  font-size: 1.05rem;
}

.lottery-card-head p {
  margin: 0.25rem 0 0;
  color: var(--text-muted);
}

.progress-track {
  height: 10px;
  margin: 1rem 0;
  border-radius: 999px;
  background: rgba(88, 209, 255, 0.08);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(135deg, #58d1ff, #ff8a30);
}

.lottery-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0;
}

.lottery-meta dd {
  margin: 0.2rem 0 0;
}

.latest-stack {
  display: grid;
  gap: 0.7rem;
  margin-top: 1.2rem;
}

.result-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.95rem 1rem;
  border-radius: 18px;
  background: rgba(6, 16, 30, 0.55);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.result-line strong {
  display: block;
}

.result-line p {
  margin: 0.2rem 0 0;
}

@media (max-width: 720px) {
  .hero-stat-row,
  .run-grid,
  .lottery-meta {
    grid-template-columns: 1fr;
  }
}
</style>
