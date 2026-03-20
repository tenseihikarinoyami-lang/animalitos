<template>
  <AppShell
    title="Animalitos enjaulados"
    subtitle="Lectura diaria de los animalitos que llevan mas tiempo sin salir en las loterias foco."
    eyebrow="Enjaulados"
  >
    <section class="glass-card section-card hero-card">
      <div>
        <p class="eyebrow">Fuente</p>
        <h3 class="section-title">LoteriaDeHoy</h3>
        <p class="section-copy">
          Esta vista se alimenta de las estadisticas publicas y te deja ver rezagos por loteria, fecha de ultima salida y dias sin salir.
        </p>
      </div>
      <button class="btn-primary" :disabled="loadingState" @click="loadEnjaulados(true)">
        <span v-if="loadingState" class="spinner"></span>
        <span v-else>Actualizar enjaulados</span>
      </button>
    </section>

    <p v-if="errorState" class="status-banner error">
      {{ errorState }}
    </p>

    <section class="enjaulados-grid">
      <article
        v-for="lottery in enjauladosResponse?.lotteries || []"
        :key="lottery.canonical_lottery_name"
        class="glass-card section-card"
      >
        <div class="lottery-head">
          <div>
            <p class="eyebrow">Loteria</p>
            <h3 class="title-with-icon">
              <img
                :src="lotteryIconUrl(lottery.canonical_lottery_name)"
                :alt="lottery.canonical_lottery_name"
                class="lottery-inline-icon"
                @error="(event) => handleIconError(event, 'lottery')"
              />
              <span>{{ lottery.canonical_lottery_name }}</span>
            </h3>
          </div>
          <span class="pill">{{ lottery.items.length }} enjaulados</span>
        </div>

        <div class="enjaulados-list">
          <div
            v-for="item in lottery.items.slice(0, 12)"
            :key="`${lottery.canonical_lottery_name}-${item.animal_number}`"
            class="enjaulado-item"
          >
            <div class="animal-title">
              <img
                :src="animalIconUrl(item.animal_name, lottery.canonical_lottery_name)"
                :alt="item.animal_name"
                class="animal-inline-icon"
                @error="handleIconError"
              />
              <div>
                <strong>{{ `${item.animal_number.toString().padStart(2, '0')} ${item.animal_name}` }}</strong>
                <p>Ultima salida: {{ item.last_seen_date || 'Sin fecha' }}</p>
              </div>
            </div>
            <span class="days-badge">{{ item.days_without_hit }} dias</span>
          </div>
        </div>
      </article>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'
import { animalIconUrl, handleIconError, lotteryIconUrl } from '@/utils/monitoring'

const lotteryStore = useLotteryStore()
const enjauladosResponse = computed(() => lotteryStore.enjaulados)
const loadingState = ref(false)
const errorState = ref('')

async function loadEnjaulados(force = false) {
  if (loadingState.value && !force) return
  loadingState.value = true
  errorState.value = ''
  try {
    const response = await lotteryStore.fetchEnjaulados({ force_refresh: force }, { silent: true })
    if (!response) {
      errorState.value = 'No se pudieron cargar los enjaulados desde la fuente externa.'
    }
  } finally {
    loadingState.value = false
  }
}

onMounted(async () => {
  await loadEnjaulados()
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

.status-banner.error {
  margin: 0 0 1rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.enjaulados-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
}

.lottery-head,
.enjaulado-item,
.animal-title,
.title-with-icon {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.8rem;
}

.title-with-icon,
.animal-title {
  justify-content: flex-start;
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

.enjaulados-list {
  display: grid;
  gap: 0.75rem;
  margin-top: 1rem;
}

.enjaulado-item {
  padding: 0.9rem 1rem;
  border-radius: 18px;
  background: rgba(8, 18, 34, 0.6);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.enjaulado-item p {
  margin: 0.2rem 0 0;
  color: var(--text-muted);
}

.days-badge {
  display: inline-grid;
  place-items: center;
  min-width: 76px;
  min-height: 38px;
  padding: 0 0.7rem;
  border-radius: 14px;
  background: rgba(255, 138, 48, 0.14);
  border: 1px solid rgba(255, 138, 48, 0.18);
  color: #ffd8b6;
  font-weight: 700;
}

@media (max-width: 720px) {
  .hero-card {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
