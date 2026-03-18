<template>
  <AppShell
    title="Panel admin"
    subtitle="Operacion, cobertura, trazabilidad, usuarios y exportes en una sola vista."
    eyebrow="Admin Ops"
  >
    <section class="metric-grid">
      <article v-for="card in statusCards" :key="card.label" class="glass-card metric-card">
        <p class="eyebrow">{{ card.eyebrow }}</p>
        <h3 class="metric-value">{{ card.value }}</h3>
        <p class="metric-label">{{ card.label }}</p>
      </article>
    </section>

    <p v-if="lotteryStore.error" class="status-banner error">
      {{ lotteryStore.error }}
    </p>

    <section class="split-grid admin-top">
      <article class="glass-card section-card col-7">
        <p class="eyebrow">Sistema</p>
        <h3 class="section-title">Estado operativo</h3>
        <p class="section-copy">
          Salud del backend, scheduler, Telegram, ultimo backfill y ultima corrida estadistica.
        </p>
        <div class="status-grid">
          <div class="status-line">
            <span class="pill" :class="pillClass(systemStatus?.firebase_connected ? 'success' : 'danger')">
              {{ (systemStatus?.database_provider || 'base').toUpperCase() }} {{ systemStatus?.firebase_connected ? 'OK' : 'OFF' }}
            </span>
            <span class="pill" :class="pillClass(systemStatus?.telegram_configured ? 'success' : 'warning')">
              Telegram {{ systemStatus?.telegram_configured ? 'OK' : 'Pendiente' }}
            </span>
            <span class="pill" :class="pillClass(systemStatus?.scheduler_running ? 'success' : 'danger')">
              Scheduler {{ systemStatus?.scheduler_running ? 'Activo' : 'Detenido' }}
            </span>
          </div>
          <div class="status-copy">
            <p><strong>Ultimo refresh OK:</strong> {{ formatDateTime(systemStatus?.latest_successful_run?.completed_at) }}</p>
            <p><strong>Ultimo backfill:</strong> {{ formatDateTime(systemStatus?.latest_backfill_run?.completed_at) }}</p>
            <p><strong>Ultima tendencia:</strong> {{ formatDateTime(systemStatus?.latest_prediction_run?.generated_at) }}</p>
            <p><strong>Ultimo fallo:</strong> {{ formatDateTime(systemStatus?.latest_failed_run?.completed_at) }}</p>
          </div>
          <div v-if="systemStatus?.warnings?.length" class="warning-stack">
            <p v-for="warning in systemStatus.warnings" :key="warning" class="warning-pill">{{ warning }}</p>
          </div>
        </div>
      </article>

      <article class="glass-card section-card col-5">
        <p class="eyebrow">Cobertura</p>
        <h3 class="section-title">Resumen de calidad</h3>
        <div class="quality-stack">
          <div class="quality-row">
            <span>Completo</span>
            <strong>{{ qualitySummary.complete }}</strong>
          </div>
          <div class="quality-row">
            <span>Parcial</span>
            <strong>{{ qualitySummary.partial }}</strong>
          </div>
          <div class="quality-row">
            <span>Faltante</span>
            <strong>{{ qualitySummary.missing }}</strong>
          </div>
          <div class="quality-row">
            <span>Error fuente</span>
            <strong>{{ qualitySummary.sourceError }}</strong>
          </div>
        </div>
        <p class="section-copy compact-copy">
          Ventana actual: ultimos {{ lotteryStore.qualityReport?.days || 14 }} dias.
        </p>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-6">
        <p class="eyebrow">Refresh</p>
        <h3 class="section-title">Refrescar y validar</h3>
        <p class="section-copy">
          Ejecuta scraping manual, recalcula snapshots y actualiza Telegram con las predicciones si aparecen resultados nuevos.
        </p>
        <div class="button-row admin-actions">
          <button class="btn-primary" :disabled="lotteryStore.loading" @click="runRefresh">
            <span v-if="lotteryStore.loading" class="spinner"></span>
            <span v-else>Ejecutar refresh</span>
          </button>
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="runTelegramTest">
            Probar Telegram
          </button>
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="reloadAdminData">
            Recargar panel
          </button>
        </div>
      </article>

      <article class="glass-card section-card col-6">
        <p class="eyebrow">Backfill</p>
        <h3 class="section-title">Rellenar historico</h3>
        <div class="field-grid">
          <div class="form-field">
            <label>Desde</label>
            <input v-model="backfill.start_date" type="date" class="input-shell" />
          </div>
          <div class="form-field">
            <label>Hasta</label>
            <input v-model="backfill.end_date" type="date" class="input-shell" />
          </div>
        </div>
        <div class="button-row admin-actions">
          <button class="btn-secondary" :disabled="lotteryStore.loading" @click="runBackfill">
            Lanzar backfill
          </button>
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="fillBackfill90">
            Preparar 90 dias
          </button>
        </div>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-6">
        <p class="eyebrow">Tendencia</p>
        <h3 class="section-title">Resumen estadistico</h3>
        <div class="field-grid">
          <div class="form-field">
            <label>Top N</label>
            <input v-model.number="possibleResultsForm.top_n" type="number" min="1" max="10" class="input-shell" />
          </div>
          <div class="form-field">
            <label>Loterias</label>
            <select v-model="possibleResultsForm.lotteries" class="select-shell" multiple>
              <option v-for="lottery in selectableLotteries" :key="lottery" :value="lottery">{{ lottery }}</option>
            </select>
          </div>
        </div>
        <div class="button-row admin-actions">
          <button class="btn-secondary" :disabled="lotteryStore.loading" @click="loadPossibleResults">
            Ver tendencia
          </button>
          <button class="btn-primary" :disabled="lotteryStore.loading" @click="sendPossibleResults">
            Enviar a Telegram ahora
          </button>
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="previewPossibleResults">
            Guardar preview
          </button>
        </div>
        <pre class="log-box compact-log">{{ possibleResultsPreview }}</pre>
      </article>

      <article class="glass-card section-card col-6">
        <p class="eyebrow">Backtesting</p>
        <h3 class="section-title">Medicion reproducible</h3>
        <div class="quality-stack">
          <div class="quality-row">
            <span>Draws evaluados</span>
            <strong>{{ lotteryStore.backtesting?.overall_total_draws ?? 0 }}</strong>
          </div>
          <div class="quality-row">
            <span>Top 1</span>
            <strong>{{ asPercent(lotteryStore.backtesting?.overall_top_1_rate) }}</strong>
          </div>
          <div class="quality-row">
            <span>Top 3</span>
            <strong>{{ asPercent(lotteryStore.backtesting?.overall_top_3_rate) }}</strong>
          </div>
          <div class="quality-row">
            <span>Top 5</span>
            <strong>{{ asPercent(lotteryStore.backtesting?.overall_top_5_rate) }}</strong>
          </div>
        </div>
        <div class="button-row admin-actions">
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="loadBacktesting">
            Recalcular backtesting
          </button>
        </div>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-5">
        <p class="eyebrow">Usuarios</p>
        <h3 class="section-title">Crear acceso temporal</h3>
        <form class="user-form" @submit.prevent="createUser">
          <div class="field-grid">
            <div class="form-field">
              <label>Username</label>
              <input v-model="newUser.username" type="text" class="input-shell" required />
            </div>
            <div class="form-field">
              <label>Rol</label>
              <select v-model="newUser.role" class="select-shell">
                <option value="user">Usuario</option>
                <option value="admin">Admin</option>
              </select>
            </div>
          </div>
          <div class="form-field">
            <label>Nombre completo</label>
            <input v-model="newUser.full_name" type="text" class="input-shell" />
          </div>
          <div class="form-field">
            <label>Clave temporal</label>
            <input v-model="newUser.temporary_password" type="password" class="input-shell" required minlength="8" />
          </div>
          <div class="form-field">
            <label>Email opcional</label>
            <input v-model="newUser.email" type="email" class="input-shell" />
          </div>
          <button class="btn-primary" :disabled="lotteryStore.loading">
            Crear usuario temporal
          </button>
        </form>
      </article>

      <article class="glass-card section-card col-7">
        <p class="eyebrow">Usuarios activos</p>
        <h3 class="section-title">Gestion y reseteo de claves</h3>
        <div class="user-summary">
          <div class="quality-row">
            <span>Total usuarios</span>
            <strong>{{ lotteryStore.users.length }}</strong>
          </div>
          <div class="quality-row">
            <span>Con cambio obligatorio</span>
            <strong>{{ usersPendingPasswordChange }}</strong>
          </div>
        </div>

        <div v-if="!lotteryStore.users.length" class="empty-state">
          No hay usuarios para mostrar.
        </div>
        <div v-else class="user-grid">
          <article v-for="user in lotteryStore.users" :key="user.username" class="user-card">
            <div class="user-card-head">
              <div>
                <strong>{{ user.username }}</strong>
                <p>{{ user.role }} | {{ user.full_name || 'Sin nombre' }}</p>
              </div>
              <span class="pill" :class="pillClass(user.must_change_password ? 'warning' : 'success')">
                {{ user.must_change_password ? 'Cambio pendiente' : 'Activa' }}
              </span>
            </div>
            <p class="user-meta">Ultimo cambio: {{ formatDateTime(user.password_changed_at) }}</p>
            <div class="inline-reset">
              <input
                v-model="passwordResets[user.username]"
                type="password"
                class="input-shell"
                minlength="8"
                placeholder="Nueva clave temporal"
              />
              <button class="btn-ghost" :disabled="lotteryStore.loading" @click="resetPassword(user.username)">
                Resetear
              </button>
            </div>
          </article>
        </div>
      </article>
    </section>

    <section class="split-grid">
      <article class="glass-card section-card col-6">
        <p class="eyebrow">Exportes</p>
        <h3 class="section-title">CSV y PDF</h3>
        <p class="section-copy">
          Descarga historico real y el ultimo resumen estadistico para soporte y seguimiento.
        </p>
        <div class="button-row admin-actions">
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="exportHistoryCsv">
            Exportar historico CSV
          </button>
          <button class="btn-ghost" :disabled="lotteryStore.loading" @click="exportPossibleResultsCsv">
            Exportar tendencia CSV
          </button>
          <button class="btn-secondary" :disabled="lotteryStore.loading" @click="exportPossibleResultsPdf">
            Exportar tendencia PDF
          </button>
        </div>
      </article>

      <article class="glass-card section-card col-6">
        <p class="eyebrow">Auditoria</p>
        <h3 class="section-title">Ultimos eventos admin</h3>
        <div class="audit-mini-list">
          <div v-for="item in auditPreview" :key="item.id || item.created_at" class="audit-mini-item">
            <strong>{{ item.action }}</strong>
            <span>{{ item.actor_username }} | {{ item.status }}</span>
            <small>{{ formatDateTime(item.created_at) }}</small>
          </div>
        </div>
      </article>
    </section>

    <section class="glass-card section-card admin-table">
      <p class="eyebrow">Calidad diaria</p>
      <h3 class="section-title">Cobertura por fecha y loteria</h3>
      <div v-if="!qualityRows.length" class="empty-state">No hay datos de calidad todavia.</div>
      <div v-else class="table-wrap">
        <table class="table-shell">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Loteria</th>
              <th>Estado</th>
              <th>Encontrados</th>
              <th>Esperados</th>
              <th>Faltantes</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in qualityRows" :key="`${item.draw_date}-${item.canonical_lottery_name}`">
              <td>{{ item.draw_date }}</td>
              <td>{{ item.canonical_lottery_name }}</td>
              <td>
                <span class="pill" :class="pillClass(statusTone(item.status))">{{ item.status }}</span>
              </td>
              <td>{{ item.found_slots }}</td>
              <td>{{ item.expected_slots }}</td>
              <td>{{ item.missing_slots.slice(0, 3).join(', ') || 'Sin faltantes' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="glass-card section-card admin-table">
      <p class="eyebrow">Traza</p>
      <h3 class="section-title">Auditoria reciente</h3>
      <div v-if="!lotteryStore.auditLogs.length" class="empty-state">No hay eventos de auditoria.</div>
      <div v-else class="table-wrap">
        <table class="table-shell">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Accion</th>
              <th>Usuario</th>
              <th>Estado</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in lotteryStore.auditLogs" :key="item.id || item.created_at">
              <td>{{ formatDateTime(item.created_at) }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.actor_username }}</td>
              <td>
                <span class="pill" :class="pillClass(item.status === 'success' ? 'success' : item.status === 'failed' ? 'danger' : 'warning')">
                  {{ item.status }}
                </span>
              </td>
              <td>{{ item.source_ip || 'n/a' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="glass-card section-card admin-log">
      <p class="eyebrow">Salida</p>
      <h3 class="section-title">Ultima accion</h3>
      <pre class="log-box">{{ prettyLog }}</pre>
    </section>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import AppShell from '@/components/AppShell.vue'
import { useLotteryStore } from '@/stores/lottery'

const lotteryStore = useLotteryStore()
const actionLog = ref({ message: 'Aun no se ha ejecutado ninguna accion.' })

const selectableLotteries = ['Lotto Activo', 'La Granjita', 'Lotto Activo Internacional']
const today = new Date().toISOString().slice(0, 10)
const ninetyDaysAgo = new Date(Date.now() - 89 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10)

const backfill = reactive({
  start_date: ninetyDaysAgo,
  end_date: today,
})

const possibleResultsForm = reactive({
  top_n: 5,
  lotteries: [...selectableLotteries],
})

const newUser = reactive({
  username: '',
  role: 'user',
  full_name: '',
  temporary_password: '',
  email: '',
})

const passwordResets = reactive({})

const systemStatus = computed(() => lotteryStore.systemStatus)
const prettyLog = computed(() => JSON.stringify(actionLog.value, null, 2))
const possibleResultsPreview = computed(() =>
  JSON.stringify(lotteryStore.possibleResults || { message: 'Todavia no se ha generado la tendencia.' }, null, 2),
)
const qualityRows = computed(() => lotteryStore.qualityReport?.items || [])
const auditPreview = computed(() => lotteryStore.auditLogs.slice(0, 6))
const usersPendingPasswordChange = computed(() => lotteryStore.users.filter((user) => user.must_change_password).length)

const statusCards = computed(() => [
  {
    eyebrow: 'Resultados',
    value: numberOrDash(lotteryStore.systemStatus?.total_results),
    label: 'Resultados almacenados',
  },
  {
    eyebrow: 'Backfill',
    value: formatCompactDate(lotteryStore.systemStatus?.latest_backfill_run?.completed_at),
    label: 'Ultimo backfill',
  },
  {
    eyebrow: 'Tendencia',
    value: formatCompactDate(lotteryStore.systemStatus?.latest_prediction_run?.generated_at),
    label: 'Ultimo resumen estadistico',
  },
  {
    eyebrow: 'Usuarios',
    value: lotteryStore.users.length,
    label: 'Accesos registrados',
  },
])

const qualitySummary = computed(() => {
  const summary = { complete: 0, partial: 0, missing: 0, sourceError: 0 }
  for (const item of qualityRows.value) {
    if (item.status === 'complete') summary.complete += 1
    else if (item.status === 'partial') summary.partial += 1
    else if (item.status === 'source-error') summary.sourceError += 1
    else summary.missing += 1
  }
  return summary
})

onMounted(() => {
  reloadAdminData()
})

function buildPossibleResultsPayload(previewOnly = false) {
  return {
    top_n: possibleResultsForm.top_n,
    lotteries: possibleResultsForm.lotteries,
    preview_only: previewOnly,
  }
}

function statusTone(status) {
  if (status === 'complete') return 'success'
  if (status === 'partial') return 'warning'
  return 'danger'
}

function pillClass(tone) {
  return `status-pill ${tone}`
}

function numberOrDash(value) {
  return value ?? 'n/a'
}

function formatDateTime(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

function formatCompactDate(value) {
  if (!value) return 'n/a'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString()
}

function asPercent(value) {
  if (value === null || value === undefined) return '0%'
  return `${(value * 100).toFixed(1)}%`
}

async function reloadAdminData() {
  const [status, quality, audit, possible, backtesting, users] = await Promise.all([
    lotteryStore.fetchSystemStatus(),
    lotteryStore.fetchQualityReport({ days: 14 }),
    lotteryStore.fetchAuditLogs({ limit: 50 }),
    lotteryStore.fetchPossibleResults(),
    lotteryStore.fetchBacktesting(),
    lotteryStore.fetchUsers(),
  ])

  actionLog.value = {
    message: 'Panel admin recargado',
    details: {
      status_loaded: !!status,
      quality_loaded: !!quality,
      audit_loaded: !!audit,
      possible_results_loaded: !!possible,
      backtesting_loaded: !!backtesting,
      users_loaded: !!users,
    },
  }
}

async function runRefresh() {
  const response = await lotteryStore.refreshResults()
  if (response) {
    actionLog.value = response
    await reloadAdminData()
  }
}

async function runTelegramTest() {
  const response = await lotteryStore.testTelegram()
  if (response) actionLog.value = response
}

async function runBackfill() {
  const response = await lotteryStore.backfill({ ...backfill })
  if (response) {
    actionLog.value = response
    await reloadAdminData()
  }
}

function fillBackfill90() {
  backfill.start_date = ninetyDaysAgo
  backfill.end_date = today
  actionLog.value = { message: 'Rango de 90 dias cargado en el formulario.' }
}

async function loadPossibleResults() {
  const response = await lotteryStore.fetchPossibleResults({
    top_n: possibleResultsForm.top_n,
    lotteries: possibleResultsForm.lotteries.join(','),
  })
  if (response) actionLog.value = { message: 'Tendencia estadistica cargada', details: response }
}

async function sendPossibleResults() {
  const response = await lotteryStore.sendPossibleResultsToTelegram(buildPossibleResultsPayload(false))
  if (response) {
    actionLog.value = response
    await reloadAdminData()
  }
}

async function previewPossibleResults() {
  const response = await lotteryStore.sendPossibleResultsToTelegram(buildPossibleResultsPayload(true))
  if (response) {
    actionLog.value = response
    await reloadAdminData()
  }
}

async function loadBacktesting() {
  const response = await lotteryStore.fetchBacktesting({
    top_n: possibleResultsForm.top_n,
    lotteries: possibleResultsForm.lotteries.join(','),
  })
  if (response) actionLog.value = { message: 'Backtesting recalculado', details: response }
}

async function createUser() {
  const payload = {
    username: newUser.username,
    role: newUser.role,
    full_name: newUser.full_name || null,
    temporary_password: newUser.temporary_password,
    email: newUser.email || null,
  }
  const response = await lotteryStore.createTemporaryUser(payload)
  if (!response) return

  actionLog.value = { message: 'Usuario temporal creado', details: response }
  newUser.username = ''
  newUser.role = 'user'
  newUser.full_name = ''
  newUser.temporary_password = ''
  newUser.email = ''
}

async function resetPassword(username) {
  const temporaryPassword = passwordResets[username]
  if (!temporaryPassword || temporaryPassword.length < 8) {
    actionLog.value = { message: 'La clave temporal debe tener al menos 8 caracteres.', details: { username } }
    return
  }

  const response = await lotteryStore.resetUserPassword(username, { temporary_password: temporaryPassword })
  if (!response) return

  actionLog.value = response
  passwordResets[username] = ''
}

async function exportHistoryCsv() {
  const response = await lotteryStore.exportHistoryCsv({ start_date: backfill.start_date, end_date: backfill.end_date })
  if (response) actionLog.value = { message: 'Historico CSV exportado', details: response }
}

async function exportPossibleResultsCsv() {
  const response = await lotteryStore.exportPossibleResultsCsv({
    top_n: possibleResultsForm.top_n,
    lotteries: possibleResultsForm.lotteries.join(','),
  })
  if (response) actionLog.value = { message: 'Tendencia CSV exportada', details: response }
}

async function exportPossibleResultsPdf() {
  const response = await lotteryStore.exportPossibleResultsPdf({
    top_n: possibleResultsForm.top_n,
    lotteries: possibleResultsForm.lotteries.join(','),
  })
  if (response) actionLog.value = { message: 'Tendencia PDF exportada', details: response }
}
</script>

<style scoped>
.admin-top,
.admin-table,
.admin-log {
  margin-top: 1rem;
}

.status-banner {
  margin-top: 1rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
}

.status-banner.error {
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.admin-actions {
  margin-top: 1rem;
}

.status-grid,
.quality-stack,
.user-summary {
  display: grid;
  gap: 0.9rem;
  margin-top: 1rem;
}

.status-line {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
}

.status-copy {
  display: grid;
  gap: 0.55rem;
}

.status-copy p,
.quality-row {
  margin: 0;
}

.quality-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.8rem 0.9rem;
  border-radius: 16px;
  background: rgba(8, 18, 34, 0.62);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.compact-copy {
  margin-top: 1rem;
}

.warning-stack {
  display: grid;
  gap: 0.65rem;
}

.warning-pill {
  margin: 0;
  padding: 0.8rem 0.95rem;
  border-radius: 16px;
  color: #ffe1a6;
  background: rgba(248, 193, 86, 0.12);
  border: 1px solid rgba(248, 193, 86, 0.22);
}

.user-form {
  display: grid;
  gap: 0.9rem;
  margin-top: 1rem;
}

.user-grid,
.audit-mini-list {
  display: grid;
  gap: 0.85rem;
  margin-top: 1rem;
}

.user-card,
.audit-mini-item {
  display: grid;
  gap: 0.55rem;
  padding: 0.95rem;
  border-radius: 18px;
  background: rgba(8, 18, 34, 0.62);
  border: 1px solid rgba(119, 177, 232, 0.08);
}

.user-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.user-card-head p,
.user-meta,
.audit-mini-item span,
.audit-mini-item small {
  margin: 0.2rem 0 0;
  color: var(--text-muted);
}

.inline-reset {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.7rem;
}

.table-wrap {
  overflow-x: auto;
  margin-top: 1rem;
}

.log-box {
  margin: 1rem 0 0;
  padding: 1rem;
  overflow: auto;
  border-radius: 18px;
  background: rgba(6, 16, 30, 0.72);
  border: 1px solid rgba(119, 177, 232, 0.08);
  color: #d7e6ff;
  white-space: pre-wrap;
}

.compact-log {
  max-height: 26rem;
}

@media (max-width: 860px) {
  .inline-reset {
    grid-template-columns: 1fr;
  }
}
</style>
