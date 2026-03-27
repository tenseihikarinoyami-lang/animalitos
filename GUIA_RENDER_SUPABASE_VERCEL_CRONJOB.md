# Guia de despliegue sin tarjeta

Esta es ahora la ruta recomendada para dejar `Animalitos Monitor` funcionando en internet sin depender de tu PC ni de Google Cloud.

Arquitectura recomendada:
- Base de datos: `Supabase Postgres`
- Backend: `Render Free Web Service`
- Scheduler externo: `GitHub Actions`
- Frontend: `Vercel`

## Limite real del plan Free de Render

El plan `free` de Render es util para arrancar sin costo, pero tiene dos limites importantes:

- el backend se duerme despues de `15 minutos` sin trafico
- Render puede reiniciar la instancia durante mantenimiento de plataforma

Eso significa que con `free` solo puedes **mitigar** el problema con keepalive y auto-recuperacion. Si quieres eliminar el sleep para usuarios, debes cambiar el servicio a `Starter` o superior.

## Importante sobre los datos que me pasaste
- La URL `https://supabase.com/dashboard/project/ubzgjbpyposrsbjzjcew` **no es** tu `DATABASE_URL`.
- Esa es solo la URL del dashboard del proyecto.
- La contrasena que compartiste es sensible. Te recomiendo **rotarla** en Supabase porque ya quedo expuesta en el chat.

## Que ya quedo implementado
- El backend soporta `Supabase Postgres` con `DATABASE_URL`.
- El backend puede desactivar el scheduler local con `USE_EXTERNAL_SCHEDULER=True`.
- Ya existen endpoints internos para que un scheduler externo dispare procesos:
  - `POST /api/internal/scheduler/refresh`
  - `POST /api/internal/scheduler/possible-results`
  - `POST /api/internal/scheduler/daily-summary`
  - `POST /api/internal/scheduler/weekly-backfill`
- El frontend acepta una API remota con `VITE_API_BASE_URL`.
- Ya existe [`render.yaml`](/D:/Proyectos/animalitos/render.yaml) para desplegar el backend en Render.
- Ya existen workflows en GitHub para:
  - despertar el backend cada 5 minutos
  - reintentar cuando Render responde `502`
  - disparar tareas programadas del scheduler

## Paso a paso que debes hacer tu

### 1. Obtener la conexion real de Supabase
En tu proyecto Supabase:
1. Haz clic en `Connect`.
2. Busca `Session pooler`.
3. Copia la cadena completa de Postgres.
4. Reemplaza `[YOUR-PASSWORD]` por tu clave real.

Debe verse parecida a esta:

```env
postgresql://postgres.TU_PROYECTO:TU_PASSWORD@aws-0-TU_REGION.pooler.supabase.com:5432/postgres
```

Ese es el valor real recomendado para `DATABASE_URL` en este despliegue.

### 2. Rotar la contrasena del proyecto
Como ya la compartiste en el chat, te recomiendo:
1. Ir a `Supabase > Settings > Database`.
2. Cambiar la contrasena.
3. Copiar de nuevo la `Connection string` actualizada.

### 3. Crear backend en Render
1. Entra a [Render](https://render.com/).
2. Crea una cuenta.
3. Conecta tu repositorio GitHub.
4. En Render elige `New +` -> `Blueprint`.
5. Selecciona el repo donde esta [`render.yaml`](/D:/Proyectos/animalitos/render.yaml).
6. Deja que Render cree el servicio `animalitos-backend`.

Si prefieres crearlo manual:
- Tipo: `Web Service`
- Root Directory: `backend`
- Runtime: `Docker`
- Plan: `Free`

### 4. Configurar variables en Render
Debes colocar estas variables:

```env
DATABASE_PROVIDER=postgres
DATABASE_URL=TU_DATABASE_URL_REAL
USE_EXTERNAL_SCHEDULER=true
SCHEDULER_SERVICE_TOKEN=UN_TOKEN_LARGO_Y_PRIVADO
APP_ENV=production
DEBUG=false
JWT_SECRET=TU_JWT_SECRET
TELEGRAM_BOT_TOKEN=TU_BOT_TOKEN
TELEGRAM_CHAT_ID=TU_CHAT_ID
BOOTSTRAP_ADMIN_PASSWORD=TU_PASSWORD_ADMIN
```

Luego, cuando tengas la URL final del frontend:

```env
CORS_ORIGINS=https://TU_FRONTEND.vercel.app,http://localhost:5173
BACKEND_PUBLIC_URL=https://TU_BACKEND.onrender.com
FRONTEND_PUBLIC_URL=https://TU_FRONTEND.vercel.app
```

### Como agregar o editar variables en Render despues del despliegue
Render no vuelve a pedir automaticamente las variables secretas despues de crear el servicio. Si te falto una o luego necesitas cambiarla, hazlo desde el mismo servicio.

Paso a paso:
1. Entra al dashboard de Render.
2. Abre el servicio `animalitos-backend`.
3. Ve a la pestana `Environment`.
4. Busca la seccion `Environment Variables`.
5. Si la variable ya existe, edita el valor.
6. Si no existe, pulsa `Add Environment Variable`.
7. Escribe `Key` y `Value`.
8. Guarda los cambios.
9. Haz `Manual Deploy` o `Save, rebuild and deploy`, segun la opcion que te muestre Render.

Variables que normalmente completas despues del primer despliegue:

```env
BACKEND_PUBLIC_URL=https://TU_BACKEND.onrender.com
FRONTEND_PUBLIC_URL=https://TU_FRONTEND.vercel.app
CORS_ORIGINS=http://localhost:5173,https://TU_FRONTEND.vercel.app
```

### 5. Inicializar la base Postgres
Tienes dos formas:

#### Opcion A: desde local
```bat
cd D:\Proyectos\animalitos\backend
venv\Scripts\activate
python -m pip install -r requirements.txt
python init_postgres.py
```

#### Opcion B: dejando que Render la inicialice al arrancar
El `Dockerfile` ya corre `bootstrap_admin.py` al iniciar, y el esquema SQL se crea automaticamente cuando `DATABASE_URL` esta activo.

### 6. Cargar historico en Supabase
Cuando el backend en Render ya este arriba:
1. Entra al panel admin de la web.
2. Ejecuta un `backfill` de `90 dias`.

Eso reconstruye el historico directamente en Supabase.

### 7. Crear frontend en Vercel
1. Entra a [Vercel](https://vercel.com/).
2. Importa el repositorio.
3. Usa:
   - Root Directory: `frontend`
   - Framework: `Vite`
4. En variables de entorno agrega:

```env
VITE_API_BASE_URL=https://TU_BACKEND.onrender.com/api
```

5. Despliega.

### Configuracion recomendada en Vercel
En el formulario de importacion o luego en `Settings`:
- Project name: `animalitos-frontend`
- Root Directory: `frontend`
- Framework Preset: `Vite`
- Build Command: `npm run build`
- Output Directory: `dist`
- Install Command: dejar automatico o `npm install`

### Como agregar o editar variables en Vercel despues del despliegue
1. Entra al dashboard de Vercel.
2. Abre tu proyecto.
3. Ve a `Settings`.
4. Entra a `Environment Variables`.
5. Pulsa `Add New`.
6. En `Name` coloca `VITE_API_BASE_URL`.
7. En `Value` coloca `https://TU_BACKEND.onrender.com/api`.
8. Marca al menos `Production`.
9. Guarda.
10. Ve a `Deployments` y pulsa `Redeploy` en el ultimo deployment.

Cuando Vercel termine, copia la URL final y regresa a Render para completar:

```env
FRONTEND_PUBLIC_URL=https://TU_FRONTEND.vercel.app
CORS_ORIGINS=http://localhost:5173,https://TU_FRONTEND.vercel.app
```

### 8. Configurar GitHub Actions para keepalive y scheduler
1. Entra a tu repositorio en GitHub.
2. Abre `Settings` -> `Secrets and variables` -> `Actions`.
3. Crea estos secretos:

```env
ANIMALITOS_BACKEND_URL=https://TU_BACKEND.onrender.com
ANIMALITOS_SCHEDULER_TOKEN=TU_TOKEN_PRIVADO
ANIMALITOS_RENDER_DEPLOY_HOOK_URL=TU_DEPLOY_HOOK_DE_RENDER
```

4. Entra a `Actions`.
5. Habilita Actions si GitHub todavia no esta activado.
6. Verifica que existan estos workflows:
   - `Animalitos Keepalive`
   - `Animalitos Render Scheduler`

### Para que sirve cada workflow

#### Animalitos Keepalive
- hace `ping` al backend cada `5 minutos`
- intenta aguantar cold starts lentos
- si Render responde `502` por demasiado tiempo, usa el `Deploy Hook` para forzar recuperacion

#### Animalitos Render Scheduler
- despierta el backend antes de cada tarea importante
- dispara:
  - `refresh` cada 5 minutos
  - `possible-results`
  - `today-analysis`
  - `daily-summary`
  - `weekly-backfill`

### Como obtener el Deploy Hook de Render
1. Entra al servicio `animalitos-backend` en Render.
2. Ve a `Settings`.
3. Busca `Deploy Hook`.
4. Crea uno nuevo si aun no existe.
5. Copia la URL y guardala en GitHub como:

```env
ANIMALITOS_RENDER_DEPLOY_HOOK_URL=...
```

### Prueba minima recomendada
Antes de dejarlo corriendo solo:
1. Ejecuta manualmente el workflow `Animalitos Keepalive`.
2. Ejecuta manualmente el workflow `Animalitos Render Scheduler` con target `refresh`.
3. Revisa los logs de GitHub y confirma que terminan en verde.
4. Revisa en el backend:
   - `/ping`
   - `/health`
5. Verifica en el admin que cambien:
   - `scheduler_last_received_at`
   - `scheduler_last_completed_at`
   - `scheduler_last_status`
   - `scheduler_last_kind`

## Lo que necesito que me pases ahora
Para seguir ayudandote sin bloquear nada, enviame solo esto:

1. `DATABASE_URL` real de Supabase
2. URL del backend cuando Render lo cree
3. URL del frontend cuando Vercel lo cree
4. El `SCHEDULER_SERVICE_TOKEN` que quieras usar

## Verificacion final
Cuando todo este arriba, debes poder:
- abrir la web desde internet
- iniciar sesion
- ver resultados y analitica
- ejecutar refresh y backfill
- recibir Telegram
- apagar tu PC y que el sistema siga funcionando

## Si quieres eliminar el sleep de verdad
Debes cambiar en Render:

- `plan: free` -> `Starter` o superior

Eso ya no depende del codigo ni de GitHub Actions. El keepalive ayuda, pero no reemplaza un servicio siempre activo.
