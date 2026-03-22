# Guia de migracion y despliegue en internet

Esta es la ruta recomendada para dejar `Animalitos Monitor` funcionando aunque tu equipo este apagado.

Arquitectura objetivo:
- Base de datos: `Supabase Postgres`
- Backend: `Google Cloud Run`
- Tareas programadas: `Google Cloud Scheduler`
- Frontend: `Vercel`

## Lo que ya hace el proyecto
- Si defines `DATABASE_PROVIDER=supabase` y `DATABASE_URL`, el backend usa `Supabase Postgres` como persistencia principal.
- El esquema se crea automaticamente al iniciar o con [`backend/init_postgres.py`](/D:/Proyectos/animalitos/backend/init_postgres.py).
- El frontend ya acepta URL remota del backend por medio de `VITE_API_BASE_URL`.
- El backend ya tiene endpoints internos para Cloud Scheduler:
  - `POST /api/internal/scheduler/refresh`
  - `POST /api/internal/scheduler/possible-results`
  - `POST /api/internal/scheduler/daily-summary`
  - `POST /api/internal/scheduler/weekly-backfill`

## Lo que debes hacer tu

### 1. Crear Supabase
1. Entra a [Supabase](https://supabase.com/).
2. Crea un proyecto nuevo.
3. Guarda estos datos:
   - `Project URL`
   - `Database password`
   - `Connection string`
4. En `Settings > Database`, copia la cadena tipo:
   - `postgresql://postgres:[PASSWORD]@db.xxx.supabase.co:5432/postgres?sslmode=require`

### 2. Pasarme o colocar estas variables en el backend
Debes tener en [`backend/.env`](/D:/Proyectos/animalitos/backend/.env):

```env
DATABASE_PROVIDER=postgres
DATABASE_URL=postgresql://postgres:TU_PASSWORD@db.TU_HOST.supabase.co:5432/postgres?sslmode=require
USE_CLOUD_SCHEDULER=True
SCHEDULER_SERVICE_TOKEN=pon_aqui_un_token_largo_y_privado
APP_ENV=production
DEBUG=False
BACKEND_PUBLIC_URL=
FRONTEND_PUBLIC_URL=
```

Tambien conservar:
- `JWT_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `BOOTSTRAP_ADMIN_PASSWORD`

### 3. Inicializar la base Postgres
Con esas variables listas, ejecuta:

```bat
cd D:\Proyectos\animalitos\backend
venv\Scripts\activate
python -m pip install -r requirements.txt
python init_postgres.py
```

Esto:
- crea tablas
- inserta horarios por defecto
- sincroniza el admin bootstrap si `BOOTSTRAP_ADMIN_PASSWORD` existe

### 4. Cargar historico en la nueva base
Cuando el backend ya este apuntando a Supabase:
1. Inicia la app localmente una vez.
2. Entra al panel admin.
3. Ejecuta un `backfill` de `90 dias`.

Eso reconstruye el historico desde la fuente web en la nueva base, sin depender de ningun proveedor legado.

### 5. Crear proyecto en Google Cloud
1. Entra a [Google Cloud Console](https://console.cloud.google.com/).
2. Crea un proyecto nuevo.
3. Habilita estas APIs:
   - `Cloud Run Admin API`
   - `Cloud Build API`
   - `Artifact Registry API`
   - `Cloud Scheduler API`
4. Instala o abre `gcloud`.
5. Ejecuta:

```bash
gcloud auth login
gcloud config set project TU_PROYECTO
```

### 6. Desplegar el backend en Cloud Run
Desde [`backend`](/D:/Proyectos/animalitos/backend):

```bash
gcloud run deploy animalitos-backend ^
  --source . ^
  --region us-central1 ^
  --allow-unauthenticated ^
  --set-env-vars DATABASE_PROVIDER=postgres,USE_CLOUD_SCHEDULER=True,APP_ENV=production,DEBUG=False ^
  --set-env-vars JWT_SECRET=TU_JWT_SECRET ^
  --set-env-vars DATABASE_URL="TU_DATABASE_URL" ^
  --set-env-vars TELEGRAM_BOT_TOKEN="TU_BOT_TOKEN" ^
  --set-env-vars TELEGRAM_CHAT_ID="TU_CHAT_ID" ^
  --set-env-vars BOOTSTRAP_ADMIN_PASSWORD="TU_BOOTSTRAP_ADMIN_PASSWORD" ^
  --set-env-vars SCHEDULER_SERVICE_TOKEN="TU_TOKEN_PRIVADO"
```

Cuando termine, Google te dara una URL parecida a:
- `https://animalitos-backend-xxxxx-uc.a.run.app`

Guarda esa URL.

### 7. Crear los jobs en Cloud Scheduler
Usa la URL del backend y el `SCHEDULER_SERVICE_TOKEN`.

Ejemplos:

Refresh frecuente:
```bash
gcloud scheduler jobs create http animalitos-refresh ^
  --location us-central1 ^
  --schedule "*/5 * * * *" ^
  --uri "https://TU_BACKEND.run.app/api/internal/scheduler/refresh" ^
  --http-method POST ^
  --headers "X-Scheduler-Token=TU_TOKEN_PRIVADO"
```

Prediccion diaria principal:
```bash
gcloud scheduler jobs create http animalitos-possible-results ^
  --location us-central1 ^
  --schedule "5 8 * * *" ^
  --time-zone "America/Caracas" ^
  --uri "https://TU_BACKEND.run.app/api/internal/scheduler/possible-results" ^
  --http-method POST ^
  --headers "X-Scheduler-Token=TU_TOKEN_PRIVADO"
```

Resumen diario:
```bash
gcloud scheduler jobs create http animalitos-daily-summary ^
  --location us-central1 ^
  --schedule "15 21 * * *" ^
  --time-zone "America/Caracas" ^
  --uri "https://TU_BACKEND.run.app/api/internal/scheduler/daily-summary" ^
  --http-method POST ^
  --headers "X-Scheduler-Token=TU_TOKEN_PRIVADO"
```

Backfill semanal:
```bash
gcloud scheduler jobs create http animalitos-weekly-backfill ^
  --location us-central1 ^
  --schedule "10 4 * * 0" ^
  --time-zone "America/Caracas" ^
  --uri "https://TU_BACKEND.run.app/api/internal/scheduler/weekly-backfill" ^
  --http-method POST ^
  --headers "X-Scheduler-Token=TU_TOKEN_PRIVADO"
```

### 8. Desplegar el frontend en Vercel
1. Sube [`frontend`](/D:/Proyectos/animalitos/frontend) a GitHub.
2. Entra a [Vercel](https://vercel.com/).
3. Importa el repositorio.
4. Configura:
   - Root Directory: `frontend`
   - Framework: `Vite`
5. En variables de entorno coloca:

```env
VITE_API_BASE_URL=https://TU_BACKEND.run.app/api
```

6. Despliega.

### 9. Actualizar CORS del backend
En Cloud Run, agrega en variables:

```env
CORS_ORIGINS=https://TU_FRONTEND.vercel.app,http://localhost:5173
BACKEND_PUBLIC_URL=https://TU_BACKEND.run.app
FRONTEND_PUBLIC_URL=https://TU_FRONTEND.vercel.app
```

### 10. Verificacion final
Debes comprobar:
1. `GET /health` del backend responde bien.
2. Puedes iniciar sesion en la web remota.
3. Admin puede hacer `refresh`.
4. Admin puede lanzar `backfill`.
5. Telegram recibe mensajes.
6. Cloud Scheduler ejecuta jobs.
7. Aunque apagues tu PC, la web y API siguen vivas.

## Lo que puedes pasarme para terminarlo mas rapido
- `DATABASE_URL` de Supabase
- URL final de Cloud Run
- URL final del frontend en Vercel
- Nombre del proyecto de Google Cloud
- Region elegida para Cloud Run / Scheduler

Con eso puedo dejarte la configuracion final ajustada al despliegue real.
