# Guia de Scheduler con GitHub Actions

## Objetivo

Esta guia reemplaza `cron-job.org` por GitHub Actions para despertar el backend de Render y disparar:

- refresh cada 5 minutos
- resumen estadistico diario
- resumen diario a Telegram
- backfill semanal de recuperacion

El workflow ya quedo creado en:

- `.github/workflows/keepalive.yml`
- `.github/workflows/render-scheduler.yml`

## Secretos que debes cargar en GitHub

En tu repositorio `animalitos` abre:

- `Settings`
- `Secrets and variables`
- `Actions`

Crea estos secretos:

1. `ANIMALITOS_BACKEND_URL`
   - valor:
   - `https://animalitos-ufry.onrender.com`

2. `ANIMALITOS_SCHEDULER_TOKEN`
   - valor:
   - el mismo que tienes en Render en `SCHEDULER_SERVICE_TOKEN`

3. `ANIMALITOS_RENDER_DEPLOY_HOOK_URL`
   - valor:
   - el `Deploy Hook` del servicio en Render
   - sirve para que el workflow fuerce una recuperacion si el backend entra en `502`

## Recomendado para recuperacion automatica

- `ANIMALITOS_RENDER_DEPLOY_HOOK_URL` es el mas importante para evitar quedarte pegado cuando Render despierta mal.
- Si no lo configuras, el workflow igual hara `ping`, pero no podra forzar una recuperacion del servicio.

## Como activarlo

1. Entra a `Actions` en GitHub.
2. Si GitHub te pide habilitar Actions, pulsa `I understand my workflows, go ahead and enable them`.
3. Verifica que aparezcan estos workflows:
   - `Animalitos Keepalive`
   - `Animalitos Render Scheduler`
4. Ejecuta una corrida manual:
   - `Run workflow`
   - target: `refresh`
5. Espera a que termine en verde.

## Horarios configurados

GitHub usa UTC. El workflow ya esta convertido para `America/Caracas`.

- `refresh`: cada 5 minutos
- `possible-results`: todos los dias a las `08:05` hora Caracas
- `daily-summary`: todos los dias a las `21:15` hora Caracas
- `weekly-backfill`: domingo a las `04:10` hora Caracas

## Que hacer con cron-job.org

Cuando confirmes que GitHub Actions ya esta ejecutando bien:

1. Entra a `cron-job.org`
2. Desactiva los jobs viejos
3. No los elimines hasta validar 1 o 2 dias de corridas correctas

## Como validar que funciona

1. Abre GitHub `Actions` y confirma que el workflow `refresh` esta corriendo cada 5 minutos.
2. Abre:
   - `https://animalitos-ufry.onrender.com/health`
3. Revisa que ahora cambien estos campos:
   - `scheduler_last_received_at`
   - `scheduler_last_completed_at`
   - `scheduler_last_status`
   - `scheduler_last_kind`
   - `scheduler_stale`
4. En el panel admin revisa:
   - `Modo scheduler`
   - `Ultimo ping scheduler`
   - `Ultima finalizacion scheduler`

## Si una corrida falla

Revisa el log del workflow en GitHub:

- `Actions`
- `Animalitos Render Scheduler`
- corrida fallida

Los fallos mas comunes son:

- secreto `ANIMALITOS_SCHEDULER_TOKEN` incorrecto
- `ANIMALITOS_BACKEND_URL` mal escrita
- Render en cold start mas lento de lo normal
- timeout temporal de la pagina fuente `loteriadehoy.com`

## Limite real del plan Free de Render

Aunque este workflow ayuda a mitigar cold starts y a reanimar el backend, **no elimina por completo** los problemas del plan `free`.

Render documenta que:
- los web services `free` se duermen tras `15 minutos` de inactividad
- los servicios pueden reiniciarse en cualquier momento por mantenimiento de plataforma

Si quieres que el backend no duerma para usuarios reales, el cambio de fondo es mover el servicio a `Starter` o superior.

Aunque GitHub Actions sirve mejor que `cron-job.org` para dejar esto versionado y auditable dentro del repo, el backend tambien quedo con:

- heartbeat real del scheduler
- self-heal al entrar usuarios
- refresh del scheduler en segundo plano
- fallback interno mientras Render este despierto

Eso evita que un solo fallo del cron deje el sistema completamente inerte.
