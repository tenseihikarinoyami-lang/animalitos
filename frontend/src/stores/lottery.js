import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export const useLotteryStore = defineStore('lottery', () => {
  const overview = ref(null)
  const results = ref([])
  const history = ref([])
  const schedules = ref([])
  const trends = ref(null)
  const possibleResults = ref(null)
  const systemStatus = ref(null)
  const qualityReport = ref(null)
  const auditLogs = ref([])
  const backtesting = ref(null)
  const users = ref([])
  const loading = ref(false)
  const error = ref('')
  const pendingCount = ref(0)

  async function withLoader(fn) {
    pendingCount.value += 1
    loading.value = true
    error.value = ''
    try {
      return await fn()
    } catch (err) {
      error.value = err.response?.data?.detail || err.message || 'Unexpected error'
      return null
    } finally {
      pendingCount.value = Math.max(pendingCount.value - 1, 0)
      loading.value = pendingCount.value > 0
    }
  }

  async function fetchOverview() {
    return withLoader(async () => {
      const response = await api.get('/dashboard/overview')
      overview.value = response.data
      return response.data
    })
  }

  async function fetchTodayResults(lotteryName = null, limit = 200) {
    return withLoader(async () => {
      const params = { limit }
      if (lotteryName) params.lottery_name = lotteryName
      const response = await api.get('/results/today', { params })
      results.value = response.data.items
      return response.data
    })
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

  async function fetchSchedules() {
    return withLoader(async () => {
      const response = await api.get('/schedules')
      schedules.value = response.data
      return response.data
    })
  }

  async function fetchTrends(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/trends', { params })
      trends.value = response.data
      return response.data
    })
  }

  async function fetchPossibleResults(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/possible-results', { params })
      possibleResults.value = response.data
      return response.data
    })
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
      return response.data
    })
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
      return response.data
    })
  }

  async function fetchQualityReport(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/admin/system/quality', { params })
      qualityReport.value = response.data
      return response.data
    })
  }

  async function fetchAuditLogs(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/admin/system/audit', { params })
      auditLogs.value = response.data
      return response.data
    })
  }

  async function fetchBacktesting(params = {}) {
    return withLoader(async () => {
      const response = await api.get('/analytics/backtesting', { params })
      backtesting.value = response.data
      return response.data
    })
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

  async function downloadFile(url, filename, params = {}) {
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
    })
  }

  async function exportHistoryCsv(params = {}) {
    return downloadFile('/admin/export/history.csv', 'animalitos-history.csv', params)
  }

  async function exportPossibleResultsCsv(params = {}) {
    return downloadFile('/admin/export/possible-results.csv', 'animalitos-possible-results.csv', params)
  }

  async function exportPossibleResultsPdf(params = {}) {
    return downloadFile('/admin/export/possible-results.pdf', 'animalitos-possible-results.pdf', params)
  }

  return {
    overview,
    results,
    history,
    schedules,
    trends,
    possibleResults,
    systemStatus,
    qualityReport,
    auditLogs,
    backtesting,
    users,
    loading,
    error,
    fetchOverview,
    fetchTodayResults,
    fetchResults,
    fetchHistory,
    fetchSchedules,
    fetchTrends,
    fetchPossibleResults,
    fetchSystemStatus,
    fetchQualityReport,
    fetchAuditLogs,
    fetchBacktesting,
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
