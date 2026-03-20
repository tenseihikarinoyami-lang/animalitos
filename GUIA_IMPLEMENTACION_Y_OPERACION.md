# Guia de Implementacion y Operacion

## Estado actual
El proyecto en [`D:\Proyectos\animalitos`](/D:/Proyectos/animalitos) quedo consolidado como plataforma de monitoreo y analitica operativa para animalitos.

Capacidades activas:
- Login y registro con JWT propio.
- Cambio de clave desde cuenta del usuario.
- Creacion de usuarios admin con `username + clave temporal`.
- Reseteo admin de claves temporales con cambio obligatorio posterior.
- Bootstrap admin seguro por entorno o script.
- Firestore real como base principal.
- Scraping estructurado de resultados diarios e historicos.
- Scheduler para ventanas de sorteo, resumen diario, resumen estadistico matutino y backfill semanal.
- Calidad diaria por loteria.
- Resumen estadistico versionado con backtesting y prediccion intradia por sorteo pendiente.
- Ranking intradia v4 con coincidencias, parejas, trios, dia de semana, tramo del dia y comparacion contra baseline simple.
- Alertas previas al siguiente sorteo para Telegram cuando el scheduler entra en ventana.
- Deteccion de cambios de ranking entre corridas consecutivas.
- Auditoria admin.
- Exportacion `CSV/PDF`.
- Panel admin actualizado y shell PWA basica.
- Backfill manual asincrono con seguimiento de progreso y estado persistido en el panel admin.
- Soporte para proveedor de base `Supabase Postgres` ademas de Firestore/mock.
- Endpoints internos listos para scheduler externo.
- Heartbeat real del scheduler con deteccion de atraso.
- Auto-recuperacion cuando entra un usuario y faltan resultados por la hora del dia.
- Refresh del scheduler en segundo plano para evitar timeouts de peticiones largas.
- Fallback interno de refresh aun cuando se use scheduler externo.

## Lo que se implemento
### Backend
- Versionado del resumen estadistico en [`backend/app/services/analytics.py`](/D:/Proyectos/animalitos/backend/app/services/analytics.py).
- Soporte de persistencia `Postgres/Supabase` en [`backend/app/services/database.py`](/D:/Proyectos/animalitos/backend/app/services/database.py).
- Esquema SQL en [`backend/app/core/postgres.py`](/D:/Proyectos/animalitos/backend/app/core/postgres.py).
- Bootstrap SQL en [`backend/init_postgres.py`](/D:/Proyectos/animalitos/backend/init_postgres.py).
- Prediccion intradia por ventana de sorteo con:
  - coincidencias del patron del dia
  - frecuencia historica por hora
  - frecuencia reciente por hora
  - dia de la semana y tramo del dia
  - transicion desde el ultimo resultado observado
  - parejas y trios previos
  - repeticion intradia
  - rezago de aparicion
- Comparacion contra baseline simple de frecuencia en el backtesting.
- Guardado de `top 3`, `top 5` y `top 10` por loteria y por ventana pendiente.
- Deteccion de `rank_delta` y cambios de lider entre corridas.
- Persistencia de corridas estadisticas en `prediction_runs`.
- Persistencia de auditoria en `admin_audit_logs`.
- Endpoint de cambio de clave para usuario autenticado.
- Endpoints admin para listar usuarios, crear usuarios temporales y resetear claves.
- Endpoints internos para scheduler cloud:
  - tambien compatibles con GitHub Actions o cualquier scheduler externo
  - `POST /api/internal/scheduler/refresh`
  - `POST /api/internal/scheduler/possible-results`
  - `POST /api/internal/scheduler/daily-summary`
  - `POST /api/internal/scheduler/weekly-backfill`
- El `refresh` del scheduler ahora se encola en segundo plano y responde rapido para no depender de una sola peticion larga.
- El health y el panel admin ahora muestran:
  - `scheduler_mode`
  - `scheduler_last_received_at`
  - `scheduler_last_completed_at`
  - `scheduler_last_status`
  - `scheduler_last_kind`
  - `scheduler_stale`
- Metadatos de cobertura por corrida:
  - `coverage_start`
  - `coverage_end`
  - `missing_slots`
  - `parser_version`
  - `source_status`
- APIs nuevas:
  - `GET /api/analytics/possible-results`
  - `GET /api/analytics/backtesting`
  - `GET /api/admin/backfill/status`
  - `GET /api/admin/system/status`
  - `GET /api/admin/system/quality`
  - `GET /api/admin/system/audit`
  - `GET /api/admin/export/history.csv`
  - `GET /api/admin/export/possible-results.csv`
  - `GET /api/admin/export/possible-results.pdf`
- Rate limiting para auth y acciones admin.
- Logging operativo mas estructurado.

### Frontend
- Ruta de monitoreo renombrada a `/monitoring`.
- URL del backend configurable por `VITE_API_BASE_URL`.
- Warmup silencioso del backend desde login para reducir la espera del primer acceso en Render.
- Cache local del usuario autenticado para evitar rebootstrap pesado en cada recarga.
- Vista `Cuenta` para cambio de clave obligatorio o voluntario.
- Monitoreo en vivo con candidatos que se actualizan conforme salen resultados del dia.
- Vista de analitica reforzada con:
  - estados de carga/error
  - metodologia visible
  - backtesting
  - comparacion contra baseline
  - alertas de cambio entre corridas
  - candidatos por sorteo pendiente
- Panel admin reforzado con:
  - estado del sistema
  - resumen de cobertura
  - estado del backfill en segundo plano
  - barra de progreso y ultima fecha procesada
  - backtesting
  - auditoria reciente
  - exportes
  - preview y envio del resumen estadistico
  - creacion de usuarios temporales
  - reseteo de claves por usuario
- Manifest y service worker basicos para fase PWA.
- Recarga automatica de chunks si el navegador queda con una version vieja del frontend tras un deploy.

### Limpieza
- Se retiro legado no usado de prediccion/ML:
  - [`backend/app/api/lottery.py`](/D:/Proyectos/animalitos/backend/app/api/lottery.py)
  - [`backend/app/services/prediction.py`](/D:/Proyectos/animalitos/backend/app/services/prediction.py)
  - [`backend/app/api/telegram.py`](/D:/Proyectos/animalitos/backend/app/api/telegram.py)
- Se unifico la documentacion principal en [`README.md`](/D:/Proyectos/animalitos/README.md) y esta guia.

## Credenciales y bootstrap admin
### Flujo actual
- Ya no se usa `admin/admin123` como credencial operativa documentada.
- El admin se sincroniza desde [`backend/bootstrap_admin.py`](/D:/Proyectos/animalitos/backend/bootstrap_admin.py).
- `start.bat` ejecuta esa sincronizacion antes de levantar el backend.

### Variables relevantes
Definir en [`backend/.env`](/D:/Proyectos/animalitos/backend/.env):
- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_EMAIL`
- `BOOTSTRAP_ADMIN_FULL_NAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `BOOTSTRAP_ADMIN_TOKEN` para el endpoint protegido de bootstrap, si se quiere usar.

## Colecciones Firestore
- `results`
- `draw_schedules`
- `ingestion_runs`
- `users`
- `analytics_snapshots`
- `prediction_runs`
- `admin_audit_logs`

## Operacion diaria recomendada
1. Ejecutar [`start.bat`](/D:/Proyectos/animalitos/start.bat).
2. Confirmar salud en `GET /health`.
3. Revisar `Panel admin`:
   - estado del sistema
   - calidad diaria
   - auditoria
   - backtesting
   - usuarios pendientes de cambio de clave
4. Revisar `Monitoreo en vivo` para validar los candidatos por sorteo pendiente.
5. Lanzar backfill si hay huecos.
   - el backfill manual ahora corre en segundo plano y el panel muestra `queued`, `running`, `finalizing`, `completed`, `partial` o `failed`
6. Revisar Telegram admin para:
   - resumen estadistico del dia
   - alertas previas al siguiente sorteo
   - cambios de ranking cuando entra un resultado nuevo relevante
7. Verificar en `Analitica` si el motor sigue superando el baseline simple.

## Despliegue cloud recomendado
- Base: `Supabase Postgres`
- Backend: `Render`
- Jobs: `GitHub Actions` como opcion recomendada versionada en repo
- Frontend: `Vercel`

Guias detalladas:
- [`GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md`](/D:/Proyectos/animalitos/GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md)
- [`GUIA_GITHUB_ACTIONS_SCHEDULER.md`](/D:/Proyectos/animalitos/GUIA_GITHUB_ACTIONS_SCHEDULER.md)

## Verificaciones hechas en desarrollo
- `pytest` backend: OK.
- `npm run build` frontend: OK.
- Firestore real: OK.
- Telegram real: OK.
- Envio de mensaje de prueba: OK.
- Ranking intradia v4: OK.
- Backtesting con baseline: OK.
- Alerta previa al sorteo en pruebas: OK.
- Scheduler en cola rapida y heartbeat: OK.
- Frontend con warmup/login cache: OK.

## Pendiente recomendado
- Ejecutar backfill real amplio de `90 dias` y revisar cobertura resultante.
- Rotar periodicamente `BOOTSTRAP_ADMIN_PASSWORD` y `BOOTSTRAP_ADMIN_TOKEN`.
- Si el volumen crece, agregar cache o Redis.
- Si luego se quiere precision mas fina, medir varias versiones del resumen estadistico antes de considerar ML entrenado.
- Preparar una politica de expiracion y bloqueo para usuarios inactivos o con demasiados intentos fallidos.
