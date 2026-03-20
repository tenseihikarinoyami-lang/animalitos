import axios from 'axios'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api'
const backendOrigin = configuredBaseUrl.endsWith('/api')
  ? configuredBaseUrl.slice(0, -4)
  : configuredBaseUrl
const healthUrl = backendOrigin ? `${backendOrigin}/health` : '/health'

const api = axios.create({
  baseURL: configuredBaseUrl,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor to add token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = String(error.config?.url || '')
    const isAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register')
    if (error.response?.status === 401 && !isAuthRequest) {
      localStorage.removeItem('token')
      localStorage.removeItem('auth_user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Method to set token
api.setToken = (token) => {
  if (token) {
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`
  } else {
    delete api.defaults.headers.common['Authorization']
  }
}

api.warmup = async () => {
  try {
    await axios.get(healthUrl, {
      timeout: 12000,
      headers: {
        'Cache-Control': 'no-cache',
      },
    })
  } catch (_error) {
    return null
  }
  return true
}

export default api
