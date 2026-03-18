import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const token = ref(localStorage.getItem('token') || null)

  const isAuthenticated = computed(() => !!token.value)
  const mustChangePassword = computed(() => !!user.value?.must_change_password)

  async function login(username, password) {
    try {
      const response = await api.post('/auth/login', { username, password })
      user.value = response.data.user
      token.value = response.data.access_token
      
      localStorage.setItem('token', response.data.access_token)
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

  async function fetchUser() {
    if (!token.value) return
    
    try {
      const response = await api.get('/auth/me')
      user.value = response.data
    } catch (error) {
      logout()
    }
  }

  async function changePassword(currentPassword, newPassword) {
    try {
      const response = await api.post('/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      user.value = response.data
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
    localStorage.removeItem('token')
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
