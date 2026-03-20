import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'

function loadStoredUser() {
  try {
    const raw = localStorage.getItem('auth_user')
    return raw ? JSON.parse(raw) : null
  } catch (_error) {
    localStorage.removeItem('auth_user')
    return null
  }
}

function persistUser(user) {
  if (user) {
    localStorage.setItem('auth_user', JSON.stringify(user))
    return
  }
  localStorage.removeItem('auth_user')
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(loadStoredUser())
  const token = ref(localStorage.getItem('token') || null)
  let bootstrapRequestToken = null

  const isAuthenticated = computed(() => !!token.value)
  const mustChangePassword = computed(() => !!user.value?.must_change_password)

  async function login(username, password) {
    try {
      const response = await api.post('/auth/login', { username, password })
      user.value = response.data.user
      token.value = response.data.access_token
      
      localStorage.setItem('token', response.data.access_token)
      persistUser(response.data.user)
      api.setToken(response.data.access_token)
      
      return { success: true }
    } catch (error) {
      return { 
        success: false, 
        error: error.response?.data?.detail || 'Error al iniciar sesión' 
      }
    }
  }

  async function register(userData) {
    try {
      const response = await api.post('/auth/register', userData)
      return { success: true, data: response.data }
    } catch (error) {
      return { 
        success: false, 
        error: error.response?.data?.detail || 'Error al registrar' 
      }
    }
  }

  async function fetchUser(expectedToken = token.value) {
    if (!expectedToken) return
    bootstrapRequestToken = expectedToken
    
    try {
      api.setToken(expectedToken)
      const response = await api.get('/auth/me')
      if (token.value !== expectedToken) return
      user.value = response.data
      persistUser(response.data)
    } catch (error) {
      if (token.value === expectedToken) {
        logout()
      }
    } finally {
      if (bootstrapRequestToken === expectedToken) {
        bootstrapRequestToken = null
      }
    }
  }

  async function changePassword(currentPassword, newPassword) {
    try {
      const response = await api.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      user.value = response.data
      persistUser(response.data)
      return { success: true, data: response.data }
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.detail || 'Error al cambiar la contrasena',
      }
    }
  }

  function logout() {
    user.value = null
    token.value = null
    bootstrapRequestToken = null
    localStorage.removeItem('token')
    persistUser(null)
    api.setToken(null)
  }

  // Initialize user if token exists
  if (token.value) {
    api.setToken(token.value)
    fetchUser()
  }

  return {
    user,
    token,
    isAuthenticated,
    mustChangePassword,
    login,
    register,
    changePassword,
    logout,
    fetchUser
  }
})
