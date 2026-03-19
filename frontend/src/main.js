import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const CHUNK_RELOAD_KEY = 'animalitos:chunk-reload'

router.onError((error, to) => {
  const message = String(error?.message || '')
  const isChunkError =
    /Failed to fetch dynamically imported module/i.test(message) ||
    /Importing a module script failed/i.test(message) ||
    /Loading chunk [\w-]+ failed/i.test(message)

  if (isChunkError) {
    const target = to?.fullPath || window.location.pathname
    if (sessionStorage.getItem(CHUNK_RELOAD_KEY) !== target) {
      sessionStorage.setItem(CHUNK_RELOAD_KEY, target)
      window.location.assign(target)
      return
    }
    sessionStorage.removeItem(CHUNK_RELOAD_KEY)
  }

  console.error(error)
})

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.config.errorHandler = (error, _instance, info) => {
  console.error('Vue runtime error:', info, error)
}

app.mount('#app')

router.isReady().then(() => {
  sessionStorage.removeItem(CHUNK_RELOAD_KEY)
})

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
