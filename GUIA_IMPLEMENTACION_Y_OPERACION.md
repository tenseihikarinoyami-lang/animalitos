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
- Auditoria admin.
- Exportacion `CSV/PDF`.
- Panel admin actualizado y shell PWA basica.
- Soporte para proveedor de base `Supabase Postgres` ademas de Firestore/mock.
- Endpoints internos listos para scheduler externo.

## Lo que se implemento
### Backend
- Versionado del resumen estadistico en [`backend/app/services/analytics.py`](/D:/Proyectos/animalitos/backend/app/services/analytics.py).
- Soporte de persistencia `Postgres/Supabase` en [`backend/app/services/database.py`](/D:/Proyectos/animalitos/backend/app/services/database.py).
- Esquema SQL en [`backend/app/core/postgres.py`](/D:/Proyectos/animalitos/backend/app/core/postgres.py).
- Bootstrap SQL en [`backend/init_postgres.py`](/D:/Proyectos/animalitos/backend/init_postgres.py).
- Prediccion intradia por ventana de sorteo con:
  - coincidencias del patron del dia
  - frecuencia historica por hora
  - transicion desde el ultimo resultado observado
  - rezago de aparicion
- Persistencia de corridas estadisticas en `prediction_runs`.
- Persistencia de auditoria en `admin_audit_logs`.
- Endpoint de cambio de clave para usuario autenticado.
- Endpoints admin para listar usuarios, crear usuarios temporales y resetear claves.
- Endpoints internos para scheduler cloud:
  - tambien compatibles con `cron-job.org`
  - `POST /api/internal/scheduler/refresh`
  - `POST /api/internal/scheduler/possible-results`
  - `POST /api/internal/scheduler/daily-summary`
  - `POST /api/internal/scheduler/weekly-backfill`
- Metadatos de cobertura por corrida:
  - `coverage_start`
  - `coverage_end`
  - `missing_slots`
  - `parser_version`
  - `source_status`
- APIs nuevas:
  - `GET /api/analytics/possible-results`
  - `GET /api/analytics/backtesting`
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
- Vista `Cuenta` para cambio de clave obligatorio o voluntario.
- Monitoreo en vivo con candidatos que se actualizan conforme salen resultados del dia.
- Vista de analitica reforzada con:
  - estados de carga/error
  - metodologia visible
  - backtesting
  - candidatos por sorteo pendiente
- Panel admin reforzado con:
  - estado del sistema
  - resumen de cobertura
  - backtesting
  - auditoria reciente
  - exportes
  - preview y envio del resumen estadistico
  - creacion de usuarios temporales
  - reseteo de claves por usuario
- Manifest y service worker basicos para fase PWA.

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
6. Revisar Telegram admin para fallos o resumenes.

## Despliegue cloud recomendado
- Base: `Supabase Postgres`
- Backend: `Render`
- Jobs: `cron-job.org`
- Frontend: `Vercel`

La guia detallada esta en [`GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md`](/D:/Proyectos/animalitos/GUIA_RENDER_SUPABASE_VERCEL_CRONJOB.md).

## Verificaciones hechas en desarrollo
- `pytest` backend: OK.
- `npm run build` frontend: OK.
- Firestore real: OK.
- Telegram real: OK.
- Envio de mensaje de prueba: OK.

## Pendiente recomendado
- Ejecutar backfill real amplio de `90 dias` y revisar cobertura resultante.
- Rotar periodicamente `BOOTSTRAP_ADMIN_PASSWORD` y `BOOTSTRAP_ADMIN_TOKEN`.
- Si el volumen crece, agregar cache o Redis.
- Si luego se quiere precision mas fina, medir varias versiones del resumen estadistico antes de considerar ML entrenado.
- Preparar una politica de expiracion y bloqueo para usuarios inactivos o con demasiados intentos fallidos.
