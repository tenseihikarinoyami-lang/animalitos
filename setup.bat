@echo off
echo ========================================
echo  Animalitos Monitoring Platform Setup
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en PATH
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js no esta instalado o no esta en PATH
    pause
    exit /b 1
)

echo [OK] Python y Node.js detectados
echo.

cd backend

if not exist "venv" (
    echo Creando entorno virtual...
    python -m venv venv
)

echo Instalando dependencias backend...
call venv\Scripts\activate.bat
python -m pip install -r requirements.txt

if not exist ".env" (
    copy .env.example .env >nul
)

cd ..
cd frontend

echo Instalando dependencias frontend...
call npm install

cd ..

echo.
echo ========================================
echo  Setup finalizado
echo ========================================
echo.
echo Estado esperado:
echo - Base de datos: usa SUPABASE con DATABASE_PROVIDER=supabase o mock local con DATABASE_PROVIDER=mock
echo - Telegram: configurado cuando completes BOT TOKEN y CHAT ID
echo - Bootstrap admin: define BOOTSTRAP_ADMIN_PASSWORD y opcionalmente BOOTSTRAP_ADMIN_TOKEN
echo - Sin demo admin por defecto
echo.
echo Ejecuta start.bat para iniciar backend y frontend.
echo.
pause
