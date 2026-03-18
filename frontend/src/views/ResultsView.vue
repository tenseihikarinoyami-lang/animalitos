<template>
  <AppShell
    title="Historico de resultados"
    subtitle="Consulta resultados por loteria, fecha y hora desde una sola pantalla."
    eyebrow="History"
  >
    <section class="glass-card section-card">
      <div class="filter-head">
        <div>
          <p class="eyebrow">Filtros</p>
          <h3 class="section-title">Busqueda operativa</h3>
        </div>
        <div class="button-row">
          <button class="btn-ghost" @click="applyQuickToday">Solo hoy</button>
          <button class="btn-primary" :disabled="lotteryStore.loading" @click="loadHistory">
            <span v-if="lotteryStore.loading" class="spinner"></span>
            <span v-else>Buscar</span>
          </button>
        </div>
      </div>

      <div class="field-grid">
        <div class="form-field">
          <label>Loteria</label>
          <select v-model="filters.lottery_name" class="select-shell">
            <option value="">Todas</option>
            <option v-for="lottery in PRIMARY_LOTTERIES" :key="lottery" :value="lottery">
              {{ lottery }}
            </option>
          </select>
        </div>
        <div class="form-field">
          <label>Desde</label>
          <input v-model="filters.start_date" type="date" class="input-shell" />
        </div>
        <div class="form-field">
          <label>Hasta</label>
          <input v-model="filters.end_date" type="date" class="input-shell" />
        </div>
        <div class="form-field">
          <label>Hora exacta</label>
          <input v-model="filters.draw_time_local" type="time" class="input-shell" />
        </div>
      </div>
    </section>

    <section class="glass-card section-card results-card">
      <div class="results-head">
        <div>
          <p class="eyebrow">Resultados</p>
          <h3 class="section-title">{{ history.length }} registros</h3>
        </div>
        <span class="pill">{{ filters.start_date || 'sin inicio' }} → {{ filters.end_date || 'sin fin' }}</span>
      </div>

      <div v-if="history.length" class="table-wrap">
        <table class="table-shell">
          <thead>
            <tr>
              <th>Loteria</th>
              <th>Fecha</th>
              <th>Hora</th>
              <th>Numero</th>
              <th>Animal</th>
              <th>Origen</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in history" :key="item.dedupe_key">
              <td>{{ item.canonical_lottery_name }}</td>
              <td>{{ item.draw_date }}</td>
              <td>{{ item.draw_time_local }}</td>
              <td><span class="number-chip">{{ item.animal_number.toString().padStart(2, '0') }}</span></td>
              <td>{{ emojiForAnimal(item.animal_name) }} {{ item.animal_name }}</td>
              <td>{{ item.source_page }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state">
        No hay resultados para los filtros actuales.
      </div>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import { emojiForAnimal, PRIMARY_LOTTERIES } from '@/utils/monitoring'

const lotteryStore = useLotteryStore()
const today = new Date().toISOString().slice(0, 10)

const filters = reactive({
  lottery_name: '',
  start_date: today,
  end_date: today,
  draw_time_local: '',
  limit: 500,
})

const history = computed(() => lotteryStore.history)

async function loadHistory() {
  const payload = { ...filters }
  if (!payload.draw_time_local) delete payload.draw_time_local
  if (!payload.lottery_name) delete payload.lottery_name
  await lotteryStore.fetchHistory(payload)
}

function applyQuickToday() {
  filters.start_date = today
  filters.end_date = today
}

onMounted(async () => {
  await loadHistory()
})
</script>

<style scoped>
.filter-head,
.results-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.results-card {
  margin-top: 1rem;
}

.table-wrap {
  overflow-x: auto;
}

@media (max-width: 720px) {
  .filter-head,
  .results-head {
    flex-direction: column;
  }
}
</style>
