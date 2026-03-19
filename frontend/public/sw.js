const CACHE_NAME = 'animalitos-monitor-v2'
const APP_SHELL = ['/', '/manifest.webmanifest']

self.addEventListener('install', (event) => {
  self.skipWaiting()
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const requestUrl = new URL(event.request.url)
  // Ignorar requests que no sean http/https (extensiones, chrome-devtools, etc.)
  if (!['http:', 'https:'].includes(requestUrl.protocol)) return
  if (event.request.method !== 'GET') return
  // Evitar cachear recursos ajenos al dominio de la app.
  if (requestUrl.origin !== self.location.origin) return
  // Evitar errores conocidos del navegador con only-if-cached fuera de same-origin.
  if (event.request.cache === 'only-if-cached' && event.request.mode !== 'same-origin') return

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type !== 'basic') {
          return response
        }
        const cloned = response.clone()
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned))
        return response
      })
    }),
  )
})
