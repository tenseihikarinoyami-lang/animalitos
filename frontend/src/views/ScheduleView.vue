<template>
  <AppShell
    title="Horarios sincronizados"
    subtitle="Horarios de referencia alimentados desde backend para que el countdown y la ingesta usen la misma fuente."
    eyebrow="Schedules"
  >
    <section class="glass-card section-card schedule-hero">
      <div>
        <p class="eyebrow">Timezone</p>
        <h3 class="section-title">America/Caracas</h3>
        <p class="section-copy">La aplicacion unifica countdown, historico y scheduler bajo la misma zona horaria.</p>
      </div>
      <button class="btn-ghost" :disabled="scheduleLoading" @click="loadSchedules">
        <span v-if="scheduleLoading" class="spinner"></span>
        <span v-else>Recargar horarios</span>
      </button>
    </section>

    <p v-if="scheduleError" class="schedule-error">
      {{ scheduleError }}
    </p>

    <section class="schedule-grid">
      <article v-for="schedule in schedules" :key="schedule.canonical_lottery_name" class="glass-card section-card schedule-card">
        <div class="schedule-head">
          <div>
            <p class="eyebrow">Loteria</p>
            <h3 class="title-with-icon">
              <img
                :src="lotteryIconUrl(schedule.canonical_lottery_name)"
                :alt="schedule.display_name"
                class="lottery-inline-icon"
                @error="(event) => handleIconError(event, 'lottery')"
              />
              <span>{{ schedule.display_name }}</span>
            </h3>
          </div>
          <span class="pill">{{ schedule.times.length }} slots</span>
        </div>
        <div class="time-chip-grid">
          <span v-for="time in schedule.times" :key="time" class="time-chip">
            {{ time }}
          </span>
        </div>
      </article>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import { handleIconError, lotteryIconUrl } from '@/utils/monitoring'

const lotteryStore = useLotteryStore()
const schedules = computed(() => lotteryStore.schedules)
const scheduleLoading = ref(false)
const scheduleError = ref('')

async function loadSchedules() {
  scheduleLoading.value = true
  scheduleError.value = ''
  try {
    const response = await lotteryStore.fetchSchedules({ silent: true })
    if (!response) {
      scheduleError.value = 'No se pudieron cargar los horarios desde el backend.'
    }
  } finally {
    scheduleLoading.value = false
  }
}

onMounted(async () => {
  await loadSchedules()
})
</script>

<style scoped>
.schedule-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.schedule-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.schedule-error {
  margin: 0 0 1rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.schedule-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
}

.schedule-head h3 {
  margin: 0.3rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
}

.title-with-icon {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
}

.lottery-inline-icon {
  width: 28px;
  height: 28px;
  object-fit: contain;
  background: rgba(6, 16, 30, 0.7);
  padding: 0.18rem;
  border-radius: 10px;
}

.time-chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  margin-top: 1rem;
}

.time-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 74px;
  min-height: 38px;
  padding: 0 0.8rem;
  border-radius: 12px;
  background: rgba(88, 209, 255, 0.08);
  border: 1px solid rgba(88, 209, 255, 0.18);
  color: var(--text);
  font-size: 0.92rem;
}

@media (max-width: 720px) {
  .schedule-hero {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
