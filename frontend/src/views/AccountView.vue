<template>
  <AppShell
    title="Mi cuenta"
    subtitle="Actualiza tu clave y completa el cambio obligatorio si entraste con una temporal."
    eyebrow="Account"
  >
    <section class="split-grid">
      <article class="glass-card section-card col-5">
        <p class="eyebrow">Perfil</p>
        <h3 class="section-title">{{ authStore.user?.username || 'Usuario' }}</h3>
        <div class="profile-meta">
          <p><strong>Rol:</strong> {{ authStore.user?.role || 'user' }}</p>
          <p><strong>Email:</strong> {{ authStore.user?.email || 'Sin email' }}</p>
          <p><strong>Clave temporal:</strong> {{ authStore.mustChangePassword ? 'Si, debes cambiarla' : 'No' }}</p>
        </div>
      </article>

      <article class="glass-card section-card col-7">
        <p class="eyebrow">Seguridad</p>
        <h3 class="section-title">Cambiar clave</h3>
        <p v-if="authStore.mustChangePassword" class="auth-warning">
          Tu usuario fue creado con una clave temporal. Debes cambiarla para seguir usando la plataforma.
        </p>
        <form class="password-form" @submit.prevent="submitPasswordChange">
          <div class="field-grid">
            <div class="form-field">
              <label>Clave actual</label>
              <input v-model="form.currentPassword" type="password" class="input-shell" required />
            </div>
            <div class="form-field">
              <label>Nueva clave</label>
              <input v-model="form.newPassword" type="password" class="input-shell" required minlength="8" />
            </div>
          </div>
          <div class="form-field">
            <label>Confirmar nueva clave</label>
            <input v-model="form.confirmPassword" type="password" class="input-shell" required minlength="8" />
          </div>
          <p v-if="error" class="auth-error">{{ error }}</p>
          <p v-if="success" class="auth-success">{{ success }}</p>
          <div class="button-row account-actions">
            <button class="btn-primary" :disabled="loading">
              <span v-if="loading" class="spinner"></span>
              <span v-else>Guardar nueva clave</span>
            </button>
          </div>
        </form>
      </article>
    </section>
  </AppShell>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '@/components/AppShell.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const router = useRouter()

const form = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

const loading = ref(false)
const error = ref('')
const success = ref('')

async function submitPasswordChange() {
  error.value = ''
  success.value = ''

  if (form.newPassword !== form.confirmPassword) {
    error.value = 'La confirmacion no coincide.'
    return
  }

  loading.value = true
  const result = await authStore.changePassword(form.currentPassword, form.newPassword)
  loading.value = false

  if (!result.success) {
    error.value = result.error
    return
  }

  success.value = 'Clave actualizada correctamente.'
  form.currentPassword = ''
  form.newPassword = ''
  form.confirmPassword = ''

  if (!authStore.mustChangePassword) {
    setTimeout(() => router.push('/'), 900)
  }
}
</script>

<style scoped>
.profile-meta {
  display: grid;
  gap: 0.7rem;
  margin-top: 1rem;
}

.profile-meta p {
  margin: 0;
  color: var(--text-muted);
}

.password-form {
  display: grid;
  gap: 1rem;
  margin-top: 1rem;
}

.account-actions {
  margin-top: 0.5rem;
}

.auth-warning,
.auth-error,
.auth-success {
  margin: 0;
  padding: 0.85rem 1rem;
  border-radius: 14px;
}

.auth-warning {
  background: rgba(248, 193, 86, 0.12);
  border: 1px solid rgba(248, 193, 86, 0.22);
  color: #ffe1a6;
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
</style>
