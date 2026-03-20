<template>
  <div class="app-shell">
    <aside class="shell-sidebar" :class="{ open: menuOpen }">
      <div class="sidebar-brand">
        <div class="brand-mark">A</div>
        <div>
          <p class="eyebrow">Realtime Ops</p>
          <h1>Animalitos Monitor</h1>
        </div>
      </div>

      <nav class="sidebar-nav">
        <router-link v-for="item in visibleNavItems" :key="item.to" :to="item.to" class="sidebar-link">
          <span class="sidebar-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer glass-card">
        <div class="sidebar-user">
          <div class="user-avatar">{{ initials }}</div>
          <div>
            <strong>{{ authStore.user?.username || "usuario" }}</strong>
            <p>{{ authStore.user?.role || "viewer" }}</p>
          </div>
        </div>
        <button class="btn-ghost sidebar-logout" @click="logout">
          Cerrar sesion
        </button>
      </div>
    </aside>

    <div class="shell-main">
      <header class="shell-header">
        <div class="shell-heading">
          <button class="mobile-toggle" @click="menuOpen = !menuOpen">
            {{ menuOpen ? "Cerrar" : "Menu" }}
          </button>
          <div>
            <p class="eyebrow">{{ eyebrow }}</p>
            <h2>{{ title }}</h2>
            <p class="section-copy">{{ subtitle }}</p>
          </div>
        </div>
        <div class="shell-actions">
          <slot name="actions" />
        </div>
      </header>

      <main class="shell-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  eyebrow: { type: String, default: 'Animalitos Analytics' },
})

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const menuOpen = ref(false)

const navItems = [
  { to: '/', label: 'Dashboard', icon: '01' },
  { to: '/monitoring', label: 'Monitoreo', icon: '02' },
  { to: '/results', label: 'Historico', icon: '03' },
  { to: '/statistics', label: 'Analitica', icon: '04' },
  { to: '/enjaulados', label: 'Enjaulados', icon: '05' },
  { to: '/strategies', label: 'Estrategias', icon: '06' },
  { to: '/schedule', label: 'Horarios', icon: '07' },
  { to: '/admin', label: 'Admin', icon: '08', adminOnly: true },
  { to: '/account', label: 'Cuenta', icon: '09' },
]

const visibleNavItems = computed(() =>
  navItems.filter((item) => !item.adminOnly || authStore.user?.role === 'admin'),
)

const initials = computed(() => (authStore.user?.username || 'A').slice(0, 1).toUpperCase())

watch(
  () => route.fullPath,
  () => {
    menuOpen.value = false
  },
)

function logout() {
  authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  min-height: 100vh;
}

.shell-sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 100vh;
  padding: 1.2rem;
  border-right: 1px solid rgba(119, 177, 232, 0.12);
  background:
    linear-gradient(180deg, rgba(8, 16, 29, 0.96), rgba(7, 14, 25, 0.94)),
    radial-gradient(circle at top, rgba(88, 209, 255, 0.16), transparent 30%);
  backdrop-filter: blur(22px);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  padding: 0.4rem 0.15rem 1rem;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(88, 209, 255, 0.18), rgba(255, 138, 48, 0.24));
  border: 1px solid rgba(88, 209, 255, 0.2);
  font-family: 'Space Grotesk', sans-serif;
  font-size: 1.2rem;
  font-weight: 700;
}

.sidebar-brand h1 {
  margin: 0.15rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 1.15rem;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.sidebar-link {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.9rem 1rem;
  border-radius: 16px;
  color: var(--text-muted);
  text-decoration: none;
  transition: background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.sidebar-link.router-link-exact-active,
.sidebar-link:hover {
  color: var(--text);
  background: rgba(88, 209, 255, 0.09);
  transform: translateX(2px);
}

.sidebar-icon {
  display: inline-grid;
  place-items: center;
  min-width: 36px;
  height: 36px;
  border-radius: 12px;
  background: rgba(88, 209, 255, 0.08);
  border: 1px solid rgba(88, 209, 255, 0.14);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--brand);
}

.sidebar-footer {
  margin-top: auto;
  padding: 1rem;
}

.sidebar-user {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  margin-bottom: 1rem;
}

.user-avatar {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(88, 209, 255, 0.2), rgba(255, 138, 48, 0.2));
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
}

.sidebar-user p {
  margin: 0.2rem 0 0;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.sidebar-logout {
  width: 100%;
}

.shell-main {
  min-width: 0;
  padding: 1.2rem;
}

.shell-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.2rem 0;
}

.shell-heading {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.shell-heading h2 {
  margin: 0.18rem 0 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(1.8rem, 3vw, 2.8rem);
}

.shell-actions {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  flex-wrap: wrap;
}

.shell-content {
  padding: 1.2rem;
}

.mobile-toggle {
  display: none;
  min-height: 42px;
  padding: 0 0.9rem;
  border-radius: 14px;
  border: 1px solid rgba(88, 209, 255, 0.18);
  background: rgba(88, 209, 255, 0.08);
  color: var(--text);
}

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .shell-sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: 280px;
    transform: translateX(-104%);
    z-index: 40;
    transition: transform 0.2s ease;
  }

  .shell-sidebar.open {
    transform: translateX(0);
  }

  .shell-main {
    padding: 0.8rem;
  }

  .mobile-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .shell-header {
    padding: 0.5rem 0.2rem 0;
    flex-direction: column;
  }

  .shell-content {
    padding: 1rem 0.2rem;
  }
}
</style>
