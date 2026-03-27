import { defineStore } from 'pinia'
import { ref } from 'vue'
import api, { describeApiError } from '@/services/api'

const CACHE_PREFIX = 'animalitos:cache:'

function cacheKey(name) {
  return `${CACHE_PREFIX}${name}`
}

function readCache(name) {
  try {
    const raw = localStorage.getItem(cacheKey(name))
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function writeCache(name, value) {
  try {
    localStorage.setItem(
      cacheKey(name),
      JSON.stringify({
        savedAt: new Date().toISOString(),
        value,
      }),
    )
  } catch {}
}

export const useLotteryStore = defineStore('lottery', () => {
  const overview = ref(readCache('overview')?.value || null)
  const results = ref(readCache('results')?.value || [])
  const history = ref([])
  const schedules = ref(readCache('schedules')?.value || [])
  const trends = ref(readCache('trends')?.value || null)
  const possibleResults = ref(readCache('possibleResults')?.value || null)
  const enjaulados = ref(readCache('enjaulados')?.value || null)
  const strategies = ref(readCache('strategies')?.value || null)
  const todayReview = ref(readCache('todayReview')?.value || null)
  const todayAnalysis = ref(readCache('todayAnalysis')?.value || null)
  const systemStatus = ref(readCache('systemStatus')?.value || null)
  const qualityReport = ref(readCache('qualityReport')?.value || null)
  const auditLogs = ref([])
  const backtesting = ref(readCache('backtesting')?.value || null)
  const modelHealth = ref(readCache('modelHealth')?.value || null)
  const backfillStatus = ref(readCache('backfillStatus')?.value || null)
  const users = ref([])
  const loading = ref(false)
  const error = ref('')
  const pendingCount = ref(0)
  const showingCachedData = ref(false)
  const cachedDataSavedAt = ref(null)

  function applyCachedValue(name, target) {
    const cached = readCache(name)
    if (!cached) return false
    target.value = cached.value
    showingCachedData.value = true
    cachedDataSavedAt.value = cached.savedAt || null
    error.value = cached.savedAt
      ? `Mostrando la ultima informacion guardada (${new Date(cached.savedAt).toLocaleString()}) mientras el servidor se recupera.`
      : 'Mostrando la ultima informacion guardada mientras el servidor se recupera.'
    return true
  }

  function rememberFreshData(name, value) {
    writeCache(name, value)
    showingCachedData.value = false
    cachedDataSavedAt.value = new Date().toISOString()
  }

  async function withLoader(fn, options = {}, onErrorFallback = null) {
    const silent = options.silent === true
    if (!silent) {
      pendingCount.value += 1
      loading.value = true
      error.value = ''
    }
    try {
      return await fn()
    } catch (err) {
      if (!silent) {
        const usedCache = typeof onErrorFallback === 'function' ? onErrorFallback(err) : false
        if (!usedCache) {
          showingCachedData.value = false
          error.value = describeApiError(err)
        }
      }
      return null
    } finally {
      if (!silent) {
        pendingCount.value = Math.max(pendingCount.value - 1, 0)
        loading.value = pendingCount.value > 0
      }
    }
  }

  async function fetchOverview() {
    return withLoader(async () => {
      const response = await api.get('/dashboard/overview')
      overview.value = response.data
      rememberFreshData('overview', response.data)
      return response.data
    }, {}, () => applyCachedValue('overview', overview))
  }

  async function fetchTodayResults(lotteryName = null, limit = 200) {
    return withLoader(async () => {
      const params = { limit }
      if (lotteryName) params.lottery_name = lotteryName
      const response = await api.get('/results/today', { params })
      results.value = response.data.items
      if (!lotteryName) {
        rememberFreshData('results', response.data.items)
      }
      return response.data
    }, {}, () => (!lotteryName ? applyCachedValue('results', results) : false))
  }

  async function fetchResults(filters = {}) {
    return withLoader(async () => {
      const response = await api.get('/results', { params: filters })
      results.value = response.data.items
      return response.data
    })
  }

  async function fetchHistory(filters = {}) {
    return withLoader(async () => {
      const response = await api.get('/results/history', { params: filters })
      history.value = response.data.items
      return response.data
    })
  }

  async function fetchSchedules(options = {}) {
    return withLoader(async () => {
      const response = await api.get('/schedules')
      schedules.value = response.data
      rememberFreshData('schedules', response.data)
      return response.data
    }, options, () => applyCachedValue('schedules', schedules))
  }

  async function fetchTrends(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/trends', { params })
      trends.value = response.data
      if (!params.lottery_name && (params.days === undefined || params.days === null)) {
        rememberFreshData('trends', response.data)
      }
      return response.data
    }, options, () => applyCachedValue('trends', trends))
  }

  async function fetchPossibleResults(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/possible-results', { params })
      possibleResults.value = response.data
      if (!params.lotteries) {
        rememberFreshData('possibleResults', response.data)
      }
      return response.data
    }, options, () => applyCachedValue('possibleResults', possibleResults))
  }

  async function fetchEnjaulados(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/enjaulados', { params })
      enjaulados.value = response.data
      rememberFreshData('enjaulados', response.data)
      return response.data
    }, options, () => applyCachedValue('enjaulados', enjaulados))
  }

  async function fetchStrategies(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/strategies', { params })
      strategies.value = response.data
      rememberFreshData('strategies', response.data)
      return response.data
    }, options, () => applyCachedValue('strategies', strategies))
  }

  async function fetchTodayReview(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/today-review', { params })
      todayReview.value = response.data
      rememberFreshData('todayReview', response.data)
      return response.data
    }, options, () => applyCachedValue('todayReview', todayReview))
  }

  async function fetchTodayAnalysis(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/today-analysis', { params })
      todayAnalysis.value = response.data
      rememberFreshData('todayAnalysis', response.data)
      return response.data
    }, options, () => applyCachedValue('todayAnalysis', todayAnalysis))
  }

  async function refreshResults() {
    return withLoader(async () => {
      const response = await api.post('/admin/results/refresh')
      overview.value = response.data.overview
      return response.data
    })
  }

  async function backfill(payload) {
    return withLoader(async () => {
      const response = await api.post('/admin/backfill', payload)
      backfillStatus.value = response.data.details?.backfill || backfillStatus.value
      if (backfillStatus.value) {
        rememberFreshData('backfillStatus', backfillStatus.value)
      }
      return response.data
    })
  }

  async function fetchBackfillStatus(options = {}) {
    return withLoader(async () => {
      const response = await api.get('/admin/backfill/status')
      backfillStatus.value = response.data
      rememberFreshData('backfillStatus', response.data)
      return response.data
    }, options, () => applyCachedValue('backfillStatus', backfillStatus))
  }

  async function testTelegram() {
    return withLoader(async () => {
      const response = await api.post('/admin/telegram/test')
      return response.data
    })
  }

  async function sendPossibleResultsToTelegram(payload = {}) {
    return withLoader(async () => {
      const response = await api.post('/admin/telegram/possible-results', payload)
      possibleResults.value = response.data.details?.summary || possibleResults.value
      backtesting.value = response.data.details?.backtesting || backtesting.value
      return response.data
    })
  }

  async function fetchSystemStatus() {
    return withLoader(async () => {
      const response = await api.get('/admin/system/status')
      systemStatus.value = response.data
      rememberFreshData('systemStatus', response.data)
      return response.data
    }, {}, () => applyCachedValue('systemStatus', systemStatus))
  }

  async function fetchQualityReport(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/admin/system/quality', { params })
      qualityReport.value = response.data
      rememberFreshData('qualityReport', response.data)
      return response.data
    }, {}, () => applyCachedValue('qualityReport', qualityReport))
  }

  async function fetchAuditLogs(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/admin/system/audit', { params })
      auditLogs.value = response.data
      return response.data
    })
  }

  async function fetchBacktesting(params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/backtesting', { params })
      backtesting.value = response.data
      rememberFreshData('backtesting', response.data)
      return response.data
    }, options, () => applyCachedValue('backtesting', backtesting))
  }

  async function fetchModelHealth(options = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/model-health')
      modelHealth.value = response.data
      rememberFreshData('modelHealth', response.data)
      return response.data
    }, options, () => applyCachedValue('modelHealth', modelHealth))
  }

  async function fetchUsers() {
    return withLoader(async () => {
      const response = await api.get('/admin/users')
      users.value = response.data
      return response.data
    })
  }

  async function createTemporaryUser(payload) {
    return withLoader(async () => {
      const response = await api.post('/admin/users', payload)
      await fetchUsers()
      return response.data
    })
  }

  async function resetUserPassword(username, payload) {
    return withLoader(async () => {
      const response = await api.post(`/admin/users/${encodeURIComponent(username)}/reset-password`, payload)
      await fetchUsers()
      return response.data
    })
  }

  async function downloadFile(url, filename, params = {}, options = {}) {
    return withLoader(async () => {
      const response = await api.get(url, {
        params,
        responseType: 'blob',
      })
      const blobUrl = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = blobUrl
      link.setAttribute('download', filename)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(blobUrl)
      return { success: true, filename }
    }, options)
  }

  async function exportHistoryCsv(params = {}, options = {}) {
    return downloadFile('/admin/export/history.csv', 'animalitos-history.csv', params, options)
  }

  async function exportPossibleResultsCsv(params = {}, options = {}) {
    return downloadFile('/admin/export/possible-results.csv', 'animalitos-possible-results.csv', params, options)
  }

  async function exportPossibleResultsPdf(params = {}, options = {}) {
    return downloadFile('/admin/export/possible-results.pdf', 'animalitos-possible-results.pdf', params, options)
  }

  return {
    overview,
    results,
    history,
    schedules,
    trends,
    possibleResults,
    enjaulados,
    strategies,
    todayReview,
    todayAnalysis,
    systemStatus,
    qualityReport,
    auditLogs,
    backtesting,
    modelHealth,
    backfillStatus,
    users,
    loading,
    error,
    showingCachedData,
    cachedDataSavedAt,
    fetchOverview,
    fetchTodayResults,
    fetchResults,
    fetchHistory,
    fetchSchedules,
    fetchTrends,
    fetchPossibleResults,
    fetchEnjaulados,
    fetchStrategies,
    fetchTodayReview,
    fetchTodayAnalysis,
    fetchSystemStatus,
    fetchQualityReport,
    fetchAuditLogs,
    fetchBacktesting,
    fetchModelHealth,
    fetchBackfillStatus,
    fetchUsers,
    refreshResults,
    backfill,
    testTelegram,
    sendPossibleResultsToTelegram,
    createTemporaryUser,
    resetUserPassword,
    exportHistoryCsv,
    exportPossibleResultsCsv,
    exportPossibleResultsPdf,
  }
})
