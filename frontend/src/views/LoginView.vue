<template>
  <div class="auth-page">
    <div class="auth-copy">
      <p class="eyebrow">Animalitos Monitoring</p>
      <h1>Operacion, historico y analitica en un solo panel.</h1>
      <p>
        Inicia sesion para seguir Lotto Activo, La Granjita y Lotto Activo Internacional con horarios y corridas sincronizadas.
      </p>
    </div>

    <section class="glass-card auth-card">
      <p class="eyebrow">Acceso</p>
      <h2>Iniciar sesion</h2>
      <form class="auth-form" @submit.prevent="handleLogin">
        <div class="form-field">
          <label>Usuario</label>
          <input v-model="formData.username" type="text" class="input-shell" required />
        </div>
        <div class="form-field">
          <label>Contrasena</label>
          <input v-model="formData.password" type="password" class="input-shell" required />
        </div>
        <p v-if="error" class="auth-error">{{ error }}</p>
        <button class="btn-primary auth-button" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <span v-else>Entrar al tablero</span>
        </button>
      </form>
      <div class="auth-footer">
        <router-link to="/register">Crear una cuenta</router-link>
        <span>Acceso admin por bootstrap seguro</span>
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
  password: '',
})

const loading = ref(false)
const error = ref('')

async function handleLogin() {
  loading.value = true
  error.value = ''
  const result = await authStore.login(formData.value.username, formData.value.password)
  loading.value = false

  if (!result.success) {
    error.value = result.error
    return
  }

  router.push('/')
}
</script>

<style scoped>
.auth-page {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(360px, 430px);
  align-items: center;
  gap: 2rem;
  min-height: 100vh;
  padding: clamp(1.2rem, 4vw, 3rem);
}

.auth-copy h1 {
  max-width: 14ch;
  margin: 0.8rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(2.4rem, 6vw, 4.8rem);
  line-height: 1;
}

.auth-copy p:last-child {
  max-width: 38rem;
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

.auth-error {
  margin: 0;
  padding: 0.85rem 1rem;
  border-radius: 14px;
  background: rgba(255, 107, 107, 0.12);
  border: 1px solid rgba(255, 107, 107, 0.22);
  color: #ffd0d0;
}

.auth-footer {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 1rem;
  color: var(--text-muted);
  font-size: 0.92rem;
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
