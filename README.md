# Animalitos Monitor

Plataforma de monitoreo, historico y analitica operativa para `Lotto Activo`, `La Granjita` y `Lotto Activo Internacional`, construida con `Vue 3`, `FastAPI`, `Telegram` y persistencia compatible con `Firestore` o `Supabase Postgres`.

## Lo que hace hoy
- Scraping estructurado de resultados actuales e historicos desde `loteriadehoy.com`.
- Normalizacion con `dedupe_key` y almacenamiento en Firestore.
- Dashboard operativo, monitoreo en vivo, historico, analitica y horarios.
- Resumen estadistico versionado de posibles resultados del dia, con actualizacion intradia conforme salen nuevos sorteos.
- Backtesting reproducible y metricas `top_1`, `top_3`, `top_5`.
- Cambio de clave desde la cuenta del usuario y usuarios temporales creados por admin.
- Panel admin con refresh, backfill, calidad diaria, auditoria, usuarios y exportes `CSV/PDF`.
- Integracion Telegram para alertas admin y envio de resumen estadistico.
- Bootstrap admin seguro por entorno o script.
- Soporte para migracion a `Supabase Postgres` y despliegue en `Render + cron-job.org + Vercel`.

## Stack
- Backend: `FastAPI`, `APScheduler`, `Firebase Admin SDK`, `BeautifulSoup`, `httpx`
- Frontend: `Vue 3`, `Pinia`, `Vue Router`, `Chart.js`, `Vite`
- Operacion: `Telegram`, `PWA shell`, exportes `CSV/PDF`

## Arranque rapido

### 1. Configurar backend
Edita [`backend/.env.example`](/D:/Proyectos/animalitos/backend/.env.example) o tu `backend/.env` con:
- Firebase real
- `JWT_SECRET`
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
- `BOOTSTRAP_ADMIN_PASSWORD`
- Opcional: `BOOTSTRAP_ADMIN_TOKEN`

### 2. Instalar dependencias
```bat
setup.bat
```

### 3. Sincronizar admin y arrancar
```bat
start.bat
```

## URLs
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`

## Endpoints clave
- `GET /api/dashboard/overview`
- `GET /api/results`
- `GET /api/results/history`
- `GET /api/analytics/trends`
- `GET /api/analytics/possible-results`
- `GET /api/analytics/backtesting`
- `POST /api/admin/results/refresh`
- `POST /api/admin/backfill`
- `POST /api/admin/telegram/possible-results`
- `GET /api/admin/system/status`
- `GET /api/admin/system/quality`
- `GET /api/admin/system/audit`

## Archivos importantes
- [`backend/app/main.py`](/D:/Proyectos/animalitos/backend/app/main.py)
- [`backend/app/services/monitoring.py`](/D:/Proyectos/animalitos/backend/app/services/monitoring.py)
- [`backend/app/services/analytics.py`](/D:/Proyectos/animalitos/backend/app/services/analytics.py)
- [`backend/bootstrap_admin.py`](/D:/Proyectos/animalitos/backend/bootstrap_admin.py)
- [`frontend/src/views/HomeView.vue`](/D:/Proyectos/animalitos/frontend/src/views/HomeView.vue)
- [`frontend/src/views/MonitoringView.vue`](/D:/Proyectos/animalitos/frontend/src/views/MonitoringView.vue)
- [`frontend/src/views/AdminView.vue`](/D:/Proyectos/animalitos/frontend/src/views/AdminView.vue)

## Guia operativa
La referencia completa de implementacion y operacion esta en [`GUIA_IMPLEMENTACION_Y_OPERACION.md`](/D:/Proyectos/animalitos/GUIA_IMPLEMENTACION_Y_OPERACION.md).

## Guia de despliegue en internet
La ruta recomendada sin tarjeta para salir de Firestore y dejar la app corriendo en la nube esta en [`GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md`](/D:/Proyectos/animalitos/GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md).
