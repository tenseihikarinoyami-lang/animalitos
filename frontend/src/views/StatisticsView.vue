<template>
  <AppShell
    title="Analitica y tendencia"
    subtitle="Frecuencias historicas, distribucion por hora, medicion reproducible y candidatos por sorteo pendiente."
    eyebrow="Analytics"
  >
    <section class="glass-card section-card">
      <div class="filter-head">
        <div>
          <p class="eyebrow">Parametros</p>
          <h3 class="section-title">Analisis por rango</h3>
          <p class="section-copy compact-copy">
            La tendencia se recalcula con historico, coincidencias por sorteo y resultados ya observados en el dia.
          </p>
        </div>
        <button class="btn-primary" :disabled="analyticsLoading" @click="loadAnalytics">
          <span v-if="analyticsLoading" class="spinner"></span>
          <span v-else>Actualizar analisis</span>
        </button>
      </div>

      <div class="field-grid">
        <div class="form-field">
          <label>Loteria</label>
          <select v-model="query.lottery_name" class="select-shell">
            <option value="">Todas</option>
            <option v-for="lottery in PRIMARY_LOTTERIES" :key="lottery" :value="lottery">
              {{ lottery }}
            </option>
          </select>
        </div>
        <div class="form-field">
          <label>Dias</label>
          <select v-model.number="query.days" class="select-shell">
            <option :value="7">7 dias</option>
            <option :value="30">30 dias</option>
            <option :value="60">60 dias</option>
            <option :value="90">90 dias</option>
          </select>
        </div>
      </div>

      <p v-if="analyticsError" class="status-banner error">
        {{ analyticsError }}
      </p>
    </section>

    <section class="metric-grid analytics-metrics">
      <article class="glass-card metric-card">
        <p class="eyebrow">Historial</p>
        <h3 class="metric-value">{{ possibleResults?.history_days_covered || 0 }}</h3>
        <p class="metric-label">Dias considerados</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Base</p>
        <h3 class="metric-value">{{ possibleResults?.history_results_considered || 0 }}</h3>
        <p class="metric-label">Resultados evaluados</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Backtesting</p>
        <h3 class="metric-value">{{ backtestingLoading && !backtesting ? '...' : asPercent(backtesting?.overall_top_3_rate) }}</h3>
        <p class="metric-label">Top 3 global</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Baseline</p>
        <h3 class="metric-value">{{ backtestingLoading && !backtesting ? '...' : asPercent(backtesting?.baseline_overall_top_3_rate) }}</h3>
        <p class="metric-label">Top 3 simple</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Metodo</p>
        <h3 class="metric-value">{{ possibleResults?.methodology_version || 'n/a' }}</h3>
        <p class="metric-label">Version estadistica</p>
      </article>
      <article class="glass-card metric-card">
        <p class="eyebrow">Lift</p>
        <h3 class="metric-value">{{ backtestingLoading && !backtesting ? '...' : formatLift(overallLiftValue) }}</h3>
        <p class="metric-label">Top 3 vs baseline</p>
      </article>
    </section>

    <section class="split-grid stats-grid">
      <article class="glass-card section-card col-7">
        <p class="eyebrow">Frecuencia</p>
        <h3 class="section-title">Animalitos mas repetidos</h3>
        <div class="chart-box">
          <Bar v-if="frequencyChartData" :data="frequencyChartData" :options="barOptions" />
          <div v-else class="empty-state">
            {{ chartStatusMessage }}
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-5">
        <p class="eyebrow">Hora</p>
        <h3 class="section-title">Distribucion por sorteo</h3>
        <div class="chart-box">
          <Bar v-if="hourlyChartData" :data="hourlyChartData" :options="barOptions" />
          <div v-else class="empty-state">
            {{ chartStatusMessage }}
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-8">
        <p class="eyebrow">Volumen</p>
        <h3 class="section-title">Resultados por dia</h3>
        <div class="chart-box">
          <Line v-if="dailyChartData" :data="dailyChartData" :options="lineOptions" />
          <div v-else class="empty-state">
            {{ chartStatusMessage }}
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-4">
        <p class="eyebrow">Anomalias</p>
        <h3 class="section-title">Dias con huecos</h3>
        <div v-if="trends?.anomalies?.length" class="anomaly-list">
          <div
            v-for="item in trends.anomalies.slice(0, 8)"
            :key="`${item.lottery_name}-${item.draw_date}`"
            class="anomaly-item"
          >
            <strong>{{ item.lottery_name }}</strong>
            <p>{{ item.draw_date }} | faltan {{ item.missing_results }}</p>
          </div>
        </div>
        <div v-else class="empty-state">
          {{ analyticsLoading ? 'Cargando anomalias...' : 'Sin anomalias detectadas para este rango.' }}
        </div>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-12">
        <p class="eyebrow">Calibracion</p>
        <h3 class="section-title">Estado del motor con data real</h3>
        <p class="section-copy">
          {{ backtesting?.calibration_summary || (backtestingLoading ? 'Calibrando backtesting y resumiendo fortalezas...' : 'Todavia no hay una lectura de calibracion disponible.') }}
        </p>
        <div v-if="backtesting?.calibration_notes?.length" class="method-stack calibration-notes">
          <div v-for="note in backtesting.calibration_notes" :key="note" class="anomaly-item">
            <strong>Nota operativa</strong>
            <p>{{ note }}</p>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-4">
        <p class="eyebrow">Resumen</p>
        <h3 class="section-title">Metodologia activa</h3>
        <p class="section-copy">
          {{ possibleResults?.methodology || 'Todavia no hay metodologia cargada.' }}
        </p>
        <div class="method-stack">
          <div v-for="component in possibleResults?.score_components || []" :key="component.key" class="method-line">
            <span>{{ component.label }}</span>
            <strong>{{ asWeight(component.weight) }}</strong>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-4">
        <p class="eyebrow">Backtesting</p>
        <h3 class="section-title">Medicion global</h3>
        <div class="method-stack">
          <div class="method-line">
            <span>Draws evaluados</span>
            <strong>{{ backtestingLoading && !backtesting ? '...' : (backtesting?.overall_total_draws ?? 0) }}</strong>
          </div>
          <div class="method-line">
            <span>Top 1</span>
            <strong>{{ asPercent(backtesting?.overall_top_1_rate) }}</strong>
          </div>
          <div class="method-line">
            <span>Top 3</span>
            <strong>{{ asPercent(backtesting?.overall_top_3_rate) }}</strong>
          </div>
          <div class="method-line">
            <span>Top 5</span>
            <strong>{{ asPercent(backtesting?.overall_top_5_rate) }}</strong>
          </div>
          <div class="method-line">
            <span>Baseline Top 3</span>
            <strong>{{ asPercent(backtesting?.baseline_overall_top_3_rate) }}</strong>
          </div>
          <div class="method-line">
            <span>Supera baseline</span>
            <strong>{{ backtesting?.beats_baseline ? 'Si' : 'No' }}</strong>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-4">
        <p class="eyebrow">Trazabilidad</p>
        <h3 class="section-title">Ultima corrida</h3>
        <div class="method-stack">
          <div class="method-line">
            <span>Generado</span>
            <strong>{{ formatDateTime(possibleResults?.generated_at) }}</strong>
          </div>
          <div class="method-line">
            <span>Ultimo backfill</span>
            <strong>{{ formatDateTime(possibleResults?.last_backfill_at) }}</strong>
          </div>
          <div class="method-line">
            <span>Loterias analizadas</span>
            <strong>{{ possibleResults?.lotteries?.length || 0 }}</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-6">
        <p class="eyebrow">Fortalezas</p>
        <h3 class="section-title">Loterias y horas mas fuertes</h3>
        <div class="method-stack">
          <div
            v-for="item in strongestLotteryRows"
            :key="`strong-lottery-${item.lottery_name}`"
            class="method-line expanded-line"
          >
            <span>{{ item.lottery_name }}</span>
            <strong>{{ asPercent(item.top_3_rate) }} | {{ formatLift(item.lift_top_3) }}</strong>
          </div>
          <div
            v-for="item in strongestHourRows"
            :key="`strong-hour-${item.lottery_name}-${item.draw_time_local}`"
            class="method-line expanded-line"
          >
            <span>{{ item.lottery_name }} {{ item.draw_time_local }}</span>
            <strong>{{ asPercent(item.top_3_rate - item.baseline_top_3_rate) }} sobre baseline</strong>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-6">
        <p class="eyebrow">Riesgos</p>
        <h3 class="section-title">Loterias y horas a vigilar</h3>
        <div class="method-stack">
          <div
            v-for="item in weakestLotteryRows"
            :key="`weak-lottery-${item.lottery_name}`"
            class="method-line expanded-line"
          >
            <span>{{ item.lottery_name }}</span>
            <strong>{{ asPercent(item.top_3_rate) }} | {{ formatLift(item.lift_top_3) }}</strong>
          </div>
          <div
            v-for="item in weakestHourRows"
            :key="`weak-hour-${item.lottery_name}-${item.draw_time_local}`"
            class="method-line expanded-line"
          >
            <span>{{ item.lottery_name }} {{ item.draw_time_local }}</span>
            <strong>{{ asPercent(item.top_3_rate - item.baseline_top_3_rate) }} sobre baseline</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="glass-card section-card">
      <p class="eyebrow">Ajustes</p>
      <h3 class="section-title">Pesos recalibrados aplicados</h3>
      <div v-if="backtesting?.weight_adjustments?.length" class="adjustment-grid">
        <article
          v-for="adjustment in backtesting.weight_adjustments"
          :key="adjustment.key"
          class="anomaly-item adjustment-card"
        >
          <strong>{{ adjustment.label }}</strong>
          <p>
            {{ asWeight(adjustment.previous_weight) }} -> {{ asWeight(adjustment.current_weight) }}
            | delta {{ formatSignedNumber(adjustment.delta * 100, 1) }} pts
          </p>
          <p>{{ adjustment.rationale }}</p>
        </article>
      </div>
      <div v-else class="empty-state">
        Sin ajustes de pesos registrados para esta version.
      </div>
    </section>

    <section class="glass-card section-card">
      <p class="eyebrow">Cambios</p>
      <h3 class="section-title">Alertas de movimiento intradia</h3>
      <div v-if="possibleResults?.change_alerts?.length" class="anomaly-list">
        <div
          v-for="alert in possibleResults.change_alerts"
          :key="alert"
          class="anomaly-item"
        >
          <strong>Cambio detectado</strong>
          <p>{{ alert }}</p>
        </div>
      </div>
      <div v-else class="empty-state">
        {{ analyticsLoading ? 'Comparando con la corrida anterior...' : 'Sin cambios fuertes entre corridas recientes.' }}
      </div>
    </section>

    <section class="glass-card section-card">
      <p class="eyebrow">Prediccion operativa</p>
      <h3 class="section-title">Candidatos por sorteo pendiente</h3>
      <div v-if="predictionRows.length" class="prediction-grid">
        <article v-for="item in predictionRows" :key="item.canonical_lottery_name" class="prediction-card">
          <div class="prediction-head">
            <div>
              <h4 class="title-with-icon">
                <img
                  :src="lotteryIconUrl(item.canonical_lottery_name)"
                  :alt="item.canonical_lottery_name"
                  class="lottery-inline-icon"
                  @error="(event) => handleIconError(event, 'lottery')"
                />
                <span>{{ item.canonical_lottery_name }}</span>
              </h4>
              <p>Proximo: {{ item.next_draw_time_local || 'Sin sorteo pendiente' }}</p>
            </div>
            <span class="pill">{{ item.remaining_draws_today }} pendientes</span>
          </div>

          <div v-if="item.draw_predictions?.length" class="window-stack">
            <div
              v-for="window in item.draw_predictions.slice(0, 3)"
              :key="`${item.canonical_lottery_name}-${window.draw_time_local}`"
              class="window-card"
            >
              <div class="window-head">
                <strong>{{ window.draw_time_local }}</strong>
                <span>
                  Patron del dia: {{ window.observed_prefix.join(', ') || 'sin base aun' }} |
                  {{ window.daypart || 'sin tramo' }} |
                  {{ countdownText(window.minutes_until) }}
                </span>
              </div>
              <p v-if="window.change_summary" class="window-change">{{ window.change_summary }}</p>
              <div class="candidate-list">
                <div
                  v-for="candidate in window.candidates.slice(0, 5)"
                  :key="`${window.draw_time_local}-${candidate.animal_number}`"
                  class="candidate-item"
                >
                  <div>
                    <strong class="title-with-icon">
                      <img
                        :src="animalIconUrl(candidate.animal_name, item.canonical_lottery_name)"
                        :alt="candidate.animal_name"
                        class="animal-inline-icon"
                        @error="handleIconError"
                      />
                      <span>{{ candidate.animal_number.toString().padStart(2, '0') }} {{ candidate.animal_name }}</span>
                    </strong>
                    <p class="candidate-movement" :class="movementTone(candidate.rank_delta, candidate.score_delta)">
                      {{ candidate.movement_summary || `Movimiento ${formatDelta(candidate.rank_delta)} | score ${formatScoreDelta(candidate.score_delta)}` }}
                    </p>
                    <p>
                      coincid {{ candidate.coincidence_hits }} | trans {{ candidate.transition_hits }} |
                      pareja {{ candidate.pair_context_hits }} | trio {{ candidate.trio_context_hits }} |
                      weekday {{ candidate.weekday_slot_hits }} | overdue {{ candidate.draws_since_last_seen }}
                    </p>
                    <div class="signal-chip-row">
                      <span
                        v-for="signal in candidate.strongest_signals.slice(0, 3)"
                        :key="`${candidate.animal_number}-${signal.key}`"
                        class="signal-chip"
                        :class="signalTone(signal)"
                      >
                        {{ signal.label }} {{ signal.contribution.toFixed(1) }}
                      </span>
                    </div>
                    <details class="candidate-details">
                      <summary>Ver explicacion</summary>
                      <p>{{ signalSummary(candidate, 4) }}</p>
                      <div class="breakdown-grid">
                        <span v-for="signal in candidate.strongest_signals" :key="signal.key">
                          {{ signal.label }}: {{ signal.contribution.toFixed(1) }}
                          <template v-if="signal.raw_value !== null && signal.raw_value !== undefined">
                            | dato {{ signal.raw_value }}
                          </template>
                        </span>
                      </div>
                    </details>
                  </div>
                  <div class="candidate-side">
                    <span class="score-chip">{{ candidate.score.toFixed(2) }}</span>
                    <span class="movement-pill" :class="movementTone(candidate.rank_delta, candidate.score_delta)">
                      Δ {{ formatDelta(candidate.rank_delta) }} | {{ formatScoreDelta(candidate.score_delta) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">
            No hay ventanas pendientes para esta loteria.
          </div>
        </article>
      </div>
      <div v-else class="empty-state">
        {{ analyticsLoading ? 'Calculando tendencia...' : 'Todavia no hay candidatos disponibles.' }}
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Bar, Line } from 'vue-chartjs'
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import {
  animalIconUrl,
  formatLift,
  formatSignedNumber,
  handleIconError,
  lotteryIconUrl,
  movementTone,
  PRIMARY_LOTTERIES,
  formatDateTime,
  signalSummary,
  signalTone,
} from '@/utils/monitoring'

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Title, Tooltip, Legend)

const lotteryStore = useLotteryStore()
const query = reactive({
  lottery_name: '',
  days: 30,
})
const analyticsLoading = ref(false)
const backtestingLoading = ref(false)
const analyticsError = ref('')

const trends = computed(() => lotteryStore.trends)
const possibleResults = computed(() => lotteryStore.possibleResults)
const backtesting = computed(() => lotteryStore.backtesting)
const predictionRows = computed(() => possibleResults.value?.lotteries || [])
const overallLiftValue = computed(() => {
  if (!backtesting.value) return 0
  return (backtesting.value.overall_top_3_rate || 0) - (backtesting.value.baseline_overall_top_3_rate || 0)
})
const strongestLotteryRows = computed(() => backtesting.value?.strongest_lotteries || [])
const weakestLotteryRows = computed(() => backtesting.value?.weakest_lotteries || [])
const strongestHourRows = computed(() => backtesting.value?.strongest_hours || [])
const weakestHourRows = computed(() => backtesting.value?.weakest_hours || [])

const chartPalette = {
  cyan: '#58d1ff',
  amber: '#ff8a30',
  mint: '#3dd598',
  fog: '#c8dcff',
}

const chartStatusMessage = computed(() => {
  if (analyticsLoading.value) return 'Cargando datos analiticos...'
  if (analyticsError.value) return 'No se pudo renderizar la grafica con la consulta actual.'
  return 'No hay suficientes datos para este rango.'
})

const frequencyChartData = computed(() => {
  if (!trends.value?.frequency?.length) return null
  return {
    labels: trends.value.frequency.map((item) => `${item.label} ${item.animal_name || ''}`.trim()),
    datasets: [
      {
        label: 'Frecuencia',
        data: trends.value.frequency.map((item) => item.value),
        backgroundColor: chartPalette.cyan,
        borderRadius: 12,
      },
    ],
  }
})

const hourlyChartData = computed(() => {
  if (!trends.value?.hourly_distribution?.length) return null
  return {
    labels: trends.value.hourly_distribution.map((item) => `${item.lottery_name || ''} ${item.label}`.trim()),
    datasets: [
      {
        label: 'Resultados',
        data: trends.value.hourly_distribution.map((item) => item.value),
        backgroundColor: chartPalette.amber,
        borderRadius: 12,
      },
    ],
  }
})

const dailyChartData = computed(() => {
  if (!trends.value?.daily_volume?.length) return null
  return {
    labels: trends.value.daily_volume.map((item) => `${item.label} ${item.lottery_name || ''}`.trim()),
    datasets: [
      {
        label: 'Volumen diario',
        data: trends.value.daily_volume.map((item) => item.value),
        borderColor: chartPalette.mint,
        backgroundColor: 'rgba(61, 213, 152, 0.18)',
        fill: true,
        tension: 0.28,
      },
    ],
  }
})

const baseOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      labels: {
        color: chartPalette.fog,
      },
    },
  },
  scales: {
    x: {
      ticks: { color: chartPalette.fog },
      grid: { color: 'rgba(119, 177, 232, 0.08)' },
    },
    y: {
      ticks: { color: chartPalette.fog },
      grid: { color: 'rgba(119, 177, 232, 0.08)' },
    },
  },
}

const barOptions = baseOptions
const lineOptions = baseOptions

function buildTrendParams() {
  const params = { days: query.days }
  if (query.lottery_name) {
    params.lottery_name = query.lottery_name
  }
  return params
}

function buildSharedLotteryParam() {
  return query.lottery_name ? query.lottery_name : null
}

async function loadAnalytics() {
  const trendParams = buildTrendParams()
  const selectedLottery = buildSharedLotteryParam()
  analyticsLoading.value = true
  analyticsError.value = ''
  try {
    const analyticsPayload = selectedLottery ? { lotteries: selectedLottery, top_n: 5 } : { top_n: 5 }
    const backtestingPayload = selectedLottery
      ? { days: query.days, lotteries: selectedLottery, top_n: 5 }
      : { days: query.days, top_n: 5 }

    await Promise.all([
      lotteryStore.fetchTrends(trendParams, { silent: true }),
      lotteryStore.fetchPossibleResults(analyticsPayload, { silent: true }),
    ])

    backtestingLoading.value = true
    lotteryStore.fetchBacktesting(backtestingPayload, { silent: true })
      .catch(() => {
        if (!lotteryStore.backtesting) {
          analyticsError.value = 'El backtesting sigue procesandose o no pudo cargarse con este rango.'
        }
      })
      .finally(() => {
        backtestingLoading.value = false
      })
  } catch (_error) {
    analyticsError.value = 'No se pudieron cargar las tendencias o predicciones para este rango.'
  } finally {
    analyticsLoading.value = false
  }
}

function asPercent(value) {
  if (value === null || value === undefined) return '0%'
  return `${(value * 100).toFixed(1)}%`
}

function asWeight(value) {
  if (value === null || value === undefined) return '0%'
  return `${Math.round(value * 100)}%`
}

function countdownText(value) {
  if (value === null || value === undefined) return 'sin countdown'
  return value <= 0 ? 'sorteo en curso' : `faltan ${value} min`
}

function formatDelta(value) {
  return formatSignedNumber(value, 0)
}

function formatScoreDelta(value) {
  return formatSignedNumber(value, 2)
}

onMounted(async () => {
  await loadAnalytics()
})
</script>

<style scoped>
.filter-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.compact-copy {
  margin-top: 0.5rem;
}

.calibration-notes {
  margin-top: 1rem;
}

.analytics-metrics,
.stats-grid {
  margin-top: 1rem;
}

.window-change {
  margin: 0.6rem 0 0;
  color: var(--brand);
  font-size: 0.88rem;
}

.status-banner {
  margin: 1rem 0 0;
  padding: 0.9rem 1rem;
  border-radius: 16px;
}

.status-banner.error {
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.chart-box {
  height: 320px;
  margin-top: 1rem;
}

.anomaly-list,
.method-stack,
.window-stack,
.candidate-list {
  display: grid;
  gap: 0.75rem;
  margin-top: 1rem;
}

.anomaly-item,
.method-line,
.window-card,
.candidate-item {
  padding: 0.95rem 1rem;
  border-radius: 18px;
  background: rgba(6, 16, 30, 0.55);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.anomaly-item p,
.candidate-item p,
.prediction-head p,
.window-head span {
  margin: 0.25rem 0 0;
  color: var(--text-muted);
}

.method-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.prediction-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-top: 1rem;
}

.prediction-card {
  padding: 1rem;
  border-radius: 22px;
  background: rgba(8, 18, 34, 0.6);
  border: 1px solid rgba(119, 177, 232, 0.1);
}

.prediction-head,
.window-head,
.candidate-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
}

.prediction-head h4 {
  margin: 0;
  font-family: 'Space Grotesk', sans-serif;
}

.expanded-line {
  align-items: flex-start;
}

.adjustment-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.8rem;
  margin-top: 1rem;
}

.adjustment-card p + p {
  margin-top: 0.5rem;
}

.title-with-icon {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}

.lottery-inline-icon,
.animal-inline-icon {
  object-fit: contain;
  background: rgba(6, 16, 30, 0.7);
}

.lottery-inline-icon {
  width: 28px;
  height: 28px;
  padding: 0.18rem;
  border-radius: 10px;
}

.animal-inline-icon {
  width: 30px;
  height: 30px;
  padding: 0.15rem;
  border-radius: 10px;
}

.score-chip {
  display: inline-grid;
  place-items: center;
  min-width: 4.6rem;
  height: 2rem;
  border-radius: 999px;
  background: rgba(88, 209, 255, 0.12);
  border: 1px solid rgba(88, 209, 255, 0.16);
  font-weight: 700;
  color: #eaf6ff;
}

.candidate-side {
  display: grid;
  gap: 0.45rem;
  justify-items: end;
}

.candidate-movement {
  margin: 0.35rem 0 0;
}

.candidate-movement.up,
.movement-pill.up {
  color: #86efac;
}

.candidate-movement.down,
.movement-pill.down {
  color: #fca5a5;
}

.candidate-movement.flat,
.movement-pill.flat {
  color: #c8dcff;
}

.signal-chip-row,
.breakdown-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.6rem;
}

.signal-chip,
.movement-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.28rem 0.7rem;
  border-radius: 999px;
  font-size: 0.74rem;
  border: 1px solid rgba(119, 177, 232, 0.12);
  background: rgba(88, 209, 255, 0.08);
}

.signal-chip.signal-strong {
  background: rgba(61, 213, 152, 0.16);
  border-color: rgba(61, 213, 152, 0.22);
}

.signal-chip.signal-high {
  background: rgba(88, 209, 255, 0.14);
}

.signal-chip.signal-medium {
  background: rgba(255, 138, 48, 0.12);
  border-color: rgba(255, 138, 48, 0.18);
}

.signal-chip.signal-low {
  background: rgba(148, 163, 184, 0.14);
  border-color: rgba(148, 163, 184, 0.18);
}

.candidate-details {
  margin-top: 0.7rem;
  color: var(--text-soft);
}

.candidate-details summary {
  cursor: pointer;
  color: #eaf6ff;
}

.breakdown-grid span {
  padding: 0.35rem 0.65rem;
  border-radius: 12px;
  background: rgba(6, 16, 30, 0.48);
  border: 1px solid rgba(119, 177, 232, 0.08);
  font-size: 0.75rem;
}

@media (max-width: 720px) {
  .filter-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
