<template>
  <div class="auth-page">
    <div class="auth-copy">
      <p class="eyebrow">Nuevo usuario</p>
      <h1>Acceso para monitoreo y consulta historica.</h1>
      <p>
        Crea tu cuenta para revisar resultados, analitica y horarios sincronizados desde la misma interfaz.
      </p>
    </div>

    <section class="glass-card auth-card">
      <p class="eyebrow">Registro</p>
      <h2>Crear cuenta</h2>
      <form class="auth-form" @submit.prevent="handleRegister">
        <div class="field-grid">
          <div class="form-field">
            <label>Usuario</label>
            <input v-model="formData.username" type="text" class="input-shell" required />
          </div>
          <div class="form-field">
            <label>Email opcional</label>
            <input v-model="formData.email" type="email" class="input-shell" />
          </div>
        </div>
        <div class="form-field">
          <label>Nombre completo</label>
          <input v-model="formData.full_name" type="text" class="input-shell" />
        </div>
        <div class="field-grid">
          <div class="form-field">
            <label>Contrasena</label>
            <input v-model="formData.password" type="password" class="input-shell" required minlength="6" />
          </div>
          <div class="form-field">
            <label>Confirmar</label>
            <input v-model="formData.confirm_password" type="password" class="input-shell" required minlength="6" />
          </div>
        </div>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <p v-if="success" class="auth-success">{{ success }}</p>
        <button class="btn-primary auth-button" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <span v-else>Crear acceso</span>
        </button>
      </form>
      <div class="auth-footer">
        <router-link to="/login">Ya tengo cuenta</router-link>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const formData = ref({
  username: '',
  email: '',
  full_name: '',
  password: '',
  confirm_password: '',
})

const loading = ref(false)
const error = ref('')
const success = ref('')

async function handleRegister() {
  if (formData.value.password !== formData.value.confirm_password) {
    error.value = 'Las contrasenas no coinciden.'
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''

  const payload = {
    username: formData.value.username,
    email: formData.value.email || null,
    full_name: formData.value.full_name,
    password: formData.value.password,
  }

  const result = await authStore.register(payload)
  loading.value = false

  if (!result.success) {
    error.value = result.error
    return
  }

  success.value = 'Cuenta creada. Redirigiendo al login...'
  setTimeout(() => router.push('/login'), 1200)
}
</script>

<style scoped>
.auth-page {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(360px, 470px);
  align-items: center;
  gap: 2rem;
  min-height: 100vh;
  padding: clamp(1.2rem, 4vw, 3rem);
}

.auth-copy h1 {
  max-width: 14ch;
  margin: 0.8rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(2.2rem, 5vw, 4.4rem);
  line-height: 1.02;
}

.auth-copy p:last-child {
  max-width: 36rem;
  margin: 1rem 0 0;
  color: var(--text-muted);
  line-height: 1.75;
}

.auth-card {
  padding: 1.5rem;
}

.auth-card h2 {
  margin: 0.4rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
}

.auth-form {
  display: grid;
  gap: 1rem;
  margin-top: 1.25rem;
}

.auth-button {
  width: 100%;
}

.auth-error,
.auth-success {
  margin: 0;
  padding: 0.85rem 1rem;
  border-radius: 14px;
}

.auth-error {
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.auth-success {
  background: rgba(61, 213, 152, 0.12);
  border: 1px solid rgba(61, 213, 152, 0.22);
  color: #d0ffe9;
}

.auth-footer {
  display: flex;
  justify-content: flex-start;
  margin-top: 1rem;
  color: var(--text-muted);
}

.auth-footer a {
  color: var(--brand);
  text-decoration: none;
}

@media (max-width: 920px) {
  .auth-page {
    grid-template-columns: 1fr;
  }

  .auth-copy h1 {
    max-width: none;
  }
}
</style>
