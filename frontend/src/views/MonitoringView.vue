<template>
  <AppShell
    title="Monitoreo en vivo"
    subtitle="Seguimiento diario de resultados y candidatos que se actualizan conforme avanza la jornada."
    eyebrow="Live Monitoring"
  >
    <template #actions>
      <span class="pill status-pill" :class="lotteryStore.loading ? 'warning' : 'success'">
        {{ lotteryStore.loading ? 'Actualizando' : 'Auto refresh activo' }}
      </span>
      <button class="btn-secondary" :disabled="lotteryStore.loading" @click="refreshNow">
        <span v-if="lotteryStore.loading" class="spinner"></span>
        <span v-else>Refrescar ingesta</span>
      </button>
    </template>

    <section class="glass-card section-card monitor-top">
      <div>
        <p class="eyebrow">Ventana activa</p>
        <h3 class="section-title title-with-icon">
          <img
            v-if="nextDraw?.canonical_lottery_name"
            :src="lotteryIconUrl(nextDraw.canonical_lottery_name)"
            :alt="nextDraw.canonical_lottery_name"
            class="lottery-inline-icon"
            @error="(event) => handleIconError(event, 'lottery')"
          />
          <span>{{ nextDraw?.canonical_lottery_name || 'Sin siguiente sorteo' }}</span>
        </h3>
        <p class="section-copy">
          {{ nextDraw ? `Proximo corte ${nextDraw.draw_date} a las ${nextDraw.draw_time_local}.` : 'Sin horarios disponibles.' }}
        </p>
      </div>
      <div class="monitor-kpis">
        <div>
          <span>Countdown</span>
          <strong>{{ countdownLabel(nextDraw?.minutes_until) }}</strong>
        </div>
        <div>
          <span>Resultados cargados</span>
          <strong>{{ results.length }}</strong>
        </div>
        <div>
          <span>Predicciones activas</span>
          <strong>{{ predictionRows.length }}</strong>
        </div>
      </div>
    </section>

    <p v-if="lotteryStore.error" class="monitor-error">
      {{ lotteryStore.error }}
    </p>

    <section class="monitor-grid">
      <article v-for="lotteryName in PRIMARY_LOTTERIES" :key="lotteryName" class="glass-card section-card monitor-card">
        <div class="monitor-card-head">
          <div>
            <p class="eyebrow">Loteria</p>
            <h3 class="title-with-icon">
              <img
                :src="lotteryIconUrl(lotteryName)"
                :alt="lotteryName"
                class="lottery-inline-icon"
                @error="(event) => handleIconError(event, 'lottery')"
              />
              <span>{{ lotteryName }}</span>
            </h3>
          </div>
          <span class="pill">{{ groupedResults[lotteryName]?.length || 0 }} draws</span>
        </div>

        <div v-if="groupedResults[lotteryName]?.length" class="stream-list">
          <div v-for="item in groupedResults[lotteryName]" :key="item.dedupe_key" class="stream-item">
            <div>
              <strong class="title-with-icon">
                <img
                  :src="animalIconUrl(item.animal_name, lotteryName)"
                  :alt="item.animal_name"
                  class="animal-inline-icon"
                  @error="handleIconError"
                />
                <span>{{ item.animal_name }}</span>
              </strong>
              <p>{{ item.draw_date }} | {{ item.draw_time_local }}</p>
            </div>
            <span class="number-chip">{{ item.animal_number.toString().padStart(2, '0') }}</span>
          </div>
        </div>
        <div v-else class="empty-state">
          Sin resultados disponibles para esta loteria todavia.
        </div>
      </article>
    </section>

    <section class="glass-card section-card prediction-section">
      <p class="eyebrow">Prediccion dinamica</p>
      <h3 class="section-title">Posibles resultados de hoy por sorteo pendiente</h3>
      <p class="section-copy">
        Cada bloque usa historico por hora, dia de la semana, contexto intradia, parejas, trios y cambios frente a la corrida anterior.
      </p>

      <div v-if="lotteryStore.possibleResults?.change_alerts?.length" class="change-banner">
        <strong>Cambios recientes:</strong>
        <span>{{ lotteryStore.possibleResults.change_alerts.join(' | ') }}</span>
      </div>

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
              <p>Proximo: {{ item.next_draw_time_local || 'Sin ventana pendiente' }}</p>
            </div>
            <span class="pill">{{ item.remaining_draws_today }} pendientes</span>
          </div>

          <div v-if="item.draw_predictions?.length" class="window-stack">
            <div
              v-for="window in item.draw_predictions.slice(0, 2)"
              :key="`${item.canonical_lottery_name}-${window.draw_time_local}`"
              class="window-card"
            >
              <div class="window-head">
                <strong>Sorteo {{ window.draw_time_local }}</strong>
                <span>
                  Patron de hoy: {{ window.observed_prefix.join(', ') || 'sin base aun' }} |
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
                      ens {{ candidate.ensemble_score?.toFixed(3) || '0.000' }} | ml {{ candidate.model_probability?.toFixed(3) || '0.000' }} |
                      regla {{ candidate.rule_score?.toFixed(2) || '0.00' }} | prior {{ candidate.external_prior?.toFixed(3) || '0.000' }} |
                      conf {{ candidate.confidence_band || 'baja' }} | estabilidad {{ candidate.stability_score?.toFixed(2) || '0.00' }}
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
                    <span class="pill">{{ candidate.segment_key || 'segmento' }}</span>
                    <span class="movement-pill" :class="movementTone(candidate.rank_delta, candidate.score_delta)">
                      Δ {{ formatDelta(candidate.rank_delta) }} | {{ formatScoreDelta(candidate.score_delta) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">
            No hay sorteos pendientes para esta loteria.
          </div>
        </article>
      </div>
      <div v-else class="empty-state">
        {{ lotteryStore.loading ? 'Calculando tendencia...' : 'Todavia no hay candidatos disponibles.' }}
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import {
  animalIconUrl,
  countdownLabel,
  formatSignedNumber,
  handleIconError,
  lotteryIconUrl,
  movementTone,
  PRIMARY_LOTTERIES,
  signalSummary,
  signalTone,
} from '@/utils/monitoring'

const AUTO_REFRESH_MS = 120000

const lotteryStore = useLotteryStore()
let refreshTimer = null

const results = computed(() => lotteryStore.results)
const nextDraw = computed(() => lotteryStore.overview?.next_draw || null)
const predictionRows = computed(() => lotteryStore.possibleResults?.lotteries || [])
const groupedResults = computed(() => {
  const grouped = {}
  for (const lotteryName of PRIMARY_LOTTERIES) {
    grouped[lotteryName] = results.value
      .filter((item) => item.canonical_lottery_name === lotteryName)
      .slice(0, 8)
  }
  return grouped
})

async function refreshNow() {
  await Promise.all([
    lotteryStore.fetchOverview(),
    lotteryStore.fetchTodayResults(),
    lotteryStore.fetchPossibleResults({ top_n: 10 }),
  ])
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
  await refreshNow()
  refreshTimer = window.setInterval(() => {
    if (!lotteryStore.loading) {
      refreshNow()
    }
  }, AUTO_REFRESH_MS)
})

onUnmounted(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.monitor-top,
.prediction-section {
  margin-bottom: 1rem;
}

.monitor-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.monitor-kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.8rem;
  min-width: 360px;
}

.monitor-kpis div,
.window-card,
.candidate-item {
  padding: 0.9rem 1rem;
  border-radius: 18px;
  background: rgba(6, 16, 30, 0.55);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.monitor-kpis span,
.stream-item p,
.candidate-item p,
.window-head span,
.prediction-head p {
  color: var(--text-muted);
  font-size: 0.82rem;
}

.monitor-kpis strong {
  display: block;
  margin-top: 0.35rem;
  font-size: 1.1rem;
}

.monitor-error {
  margin: 0 0 1rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.change-banner,
.window-change {
  margin-top: 0.85rem;
  padding: 0.8rem 1rem;
  border-radius: 16px;
  background: rgba(88, 209, 255, 0.08);
  border: 1px solid rgba(88, 209, 255, 0.12);
  color: var(--text-soft);
}

.change-banner strong {
  color: #eaf6ff;
  margin-right: 0.5rem;
}

.monitor-grid,
.prediction-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.monitor-card-head,
.prediction-head,
.window-head,
.candidate-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
}

.monitor-card-head h3,
.prediction-head h4 {
  margin: 0.3rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
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

.candidate-side {
  display: grid;
  gap: 0.45rem;
  justify-items: end;
}

.candidate-movement {
  margin-top: 0.35rem;
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

.stream-list,
.window-stack,
.candidate-list {
  display: grid;
  gap: 0.75rem;
  margin-top: 1.1rem;
}

.stream-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.95rem 1rem;
  border-radius: 18px;
  background: rgba(6, 16, 30, 0.55);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.stream-item strong,
.candidate-item strong {
  display: block;
}

.stream-item p {
  margin: 0.25rem 0 0;
}

.prediction-card {
  padding: 1rem;
  border-radius: 22px;
  background: rgba(8, 18, 34, 0.6);
  border: 1px solid rgba(119, 177, 232, 0.1);
}

.score-chip {
  display: inline-grid;
  place-items: center;
  min-width: 2.6rem;
  height: 2rem;
  border-radius: 999px;
  background: rgba(88, 209, 255, 0.12);
  border: 1px solid rgba(88, 209, 255, 0.16);
  font-weight: 700;
  color: #eaf6ff;
}

@media (max-width: 720px) {
  .monitor-top {
    flex-direction: column;
    align-items: stretch;
  }

  .monitor-kpis {
    min-width: 0;
    grid-template-columns: 1fr;
  }
}
</style>
