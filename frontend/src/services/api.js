import axios from 'axios'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api'
const backendOrigin = configuredBaseUrl.endsWith('/api')
  ? configuredBaseUrl.slice(0, -4)
  : configuredBaseUrl
const pingUrl = backendOrigin ? `${backendOrigin}/ping` : '/ping'
const REQUEST_TIMEOUT_MS = 15000
const WARMUP_TIMEOUT_MS = 15000
const BACKEND_COOLDOWN_MS = 45000
const RETRYABLE_STATUS_CODES = new Set([502, 503, 504])
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const backendState = {
  status: 'unknown',
  lastFailureAt: 0,
  nextRetryAt: 0,
  warmupPromise: null,
}

function isWarmupRequest(url = '') {
  return url.includes('/ping') || url.includes('/health')
}

function isLoginRequest(url = '') {
  return url.includes('/auth/login')
}

function isIdempotentRequest(config = {}) {
  const method = String(config.method || 'get').toLowerCase()
  return ['get', 'head', 'options'].includes(method)
}

function markBackendHealthy() {
  backendState.status = 'healthy'
  backendState.lastFailureAt = 0
  backendState.nextRetryAt = 0
}

function markBackendDegraded() {
  const failureAt = Date.now()
  backendState.status = 'degraded'
  backendState.lastFailureAt = failureAt
  backendState.nextRetryAt = failureAt + BACKEND_COOLDOWN_MS
}

function isBackendCoolingDown() {
  return backendState.status === 'degraded' && Date.now() < backendState.nextRetryAt
}

function shouldWarmupAndRetry(error) {
  const config = error.config || {}
  const requestUrl = String(config.url || '')
  const responseStatus = error.response?.status
  const isNetworkError = !error.response
  const isRetryableStatus = RETRYABLE_STATUS_CODES.has(responseStatus)
  const isRetryableLogin = isLoginRequest(requestUrl)

  if (config.__warmupRetried || isWarmupRequest(requestUrl)) {
    return false
  }

  if (!isIdempotentRequest(config) && !isRetryableLogin) {
    return false
  }

  return isNetworkError || isRetryableStatus
}

function describeApiError(error) {
  if (error?.userMessage) {
    return error.userMessage
  }

  if (error?.code === 'BACKEND_UNAVAILABLE') {
    return 'El servicio esta temporalmente inestable. Estamos intentando reconectarlo; intenta de nuevo en unos segundos.'
  }

  if (error?.code === 'ECONNABORTED') {
    return 'El servidor esta tardando demasiado en responder. Intenta de nuevo en unos segundos.'
  }

  if (error?.response?.status === 503) {
    return error.response?.data?.detail || 'El backend esta temporalmente degradado. Intenta de nuevo en unos minutos.'
  }

  if (error?.response?.status >= 500) {
    return 'Se detecto un problema temporal en el servidor. Estamos manteniendo los ultimos datos disponibles.'
  }

  if (!error?.response) {
    return 'No se pudo conectar con el servidor. Verifica la red o intenta nuevamente en unos segundos.'
  }

  return error.response?.data?.detail || error.message || 'Unexpected error'
}

const api = axios.create({
  baseURL: configuredBaseUrl,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
})

api.interceptors.request.use(
  (config) => {
    const requestUrl = String(config.url || '')
    if (isBackendCoolingDown() && !isWarmupRequest(requestUrl) && !isLoginRequest(requestUrl)) {
      const error = new Error('Backend temporarily unavailable')
      error.code = 'BACKEND_UNAVAILABLE'
      error.config = config
      error.userMessage = describeApiError(error)
      return Promise.reject(error)
    }

    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => {
    if (!isWarmupRequest(String(response.config?.url || ''))) {
      markBackendHealthy()
    }
    return response
  },
  async (error) => {
    const config = error.config || {}
    const requestUrl = String(config.url || '')
    const isAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register')
    const isWarmupCall = isWarmupRequest(requestUrl)
    const isLoginCall = isLoginRequest(requestUrl)

    if (shouldWarmupAndRetry(error) && (!isBackendCoolingDown() || isLoginCall)) {
      config.__warmupRetried = true
      const warmed = await api.warmup({ force: isLoginCall })
      if (warmed) {
        await sleep(1200)
        return api.request(config)
      }
    }

    if (error.response?.status === 401 && !isAuthRequest) {
      localStorage.removeItem('token')
      localStorage.removeItem('auth_user')
      window.location.href = '/login'
    }

    if (!isWarmupCall && (!error.response || error.response.status >= 500)) {
      markBackendDegraded()
    }

    error.userMessage = describeApiError(error)
    return Promise.reject(error)
  }
)

api.setToken = (token) => {
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`
  } else {
    delete api.defaults.headers.common.Authorization
  }
}

api.warmup = async ({ force = false } = {}) => {
  if (backendState.warmupPromise) {
    return backendState.warmupPromise
  }

  if (!force && isBackendCoolingDown()) {
    return false
  }

  backendState.warmupPromise = (async () => {
    try {
      await axios.get(pingUrl, {
        timeout: WARMUP_TIMEOUT_MS,
        headers: {
          'Cache-Control': 'no-cache',
        },
      })
      markBackendHealthy()
      return true
    } catch (_error) {
      markBackendDegraded()
      return false
    } finally {
      backendState.warmupPromise = null
    }
  })()

  return backendState.warmupPromise
}

export { describeApiError }
export default api
