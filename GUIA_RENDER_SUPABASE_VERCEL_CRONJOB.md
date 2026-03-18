# Guia de despliegue sin tarjeta

Esta es ahora la ruta recomendada para dejar `Animalitos Monitor` funcionando en internet sin depender de tu PC ni de Google Cloud.

Arquitectura recomendada:
- Base de datos: `Supabase Postgres`
- Backend: `Render Free Web Service`
- Scheduler externo: `cron-job.org`
- Frontend: `Vercel`

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

### 8. Crear scheduler gratis en cron-job.org
1. Entra a [cron-job.org](https://cron-job.org/en/).
2. Crea una cuenta.
3. Crea estos jobs HTTP `POST`.
4. En headers agrega:

```http
X-Scheduler-Token: TU_TOKEN_PRIVADO
```

#### Job 1: refresh frecuente
- URL: `https://TU_BACKEND.onrender.com/api/internal/scheduler/refresh`
- Metodo: `POST`
- Frecuencia recomendada: cada `5 minutos`

Este job tambien ayuda a mantener despierto el backend free de Render.

#### Job 2: tendencia de la manana
- URL: `https://TU_BACKEND.onrender.com/api/internal/scheduler/possible-results`
- Metodo: `POST`
- Hora recomendada: `08:05`
- Zona horaria: `America/Caracas`

#### Job 3: resumen diario
- URL: `https://TU_BACKEND.onrender.com/api/internal/scheduler/daily-summary`
- Metodo: `POST`
- Hora recomendada: `21:15`
- Zona horaria: `America/Caracas`

#### Job 4: backfill semanal
- URL: `https://TU_BACKEND.onrender.com/api/internal/scheduler/weekly-backfill`
- Metodo: `POST`
- Frecuencia: domingo `04:10`
- Zona horaria: `America/Caracas`

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
