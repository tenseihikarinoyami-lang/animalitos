@echo off
echo ========================================
echo  Starting Animalitos Monitoring Platform
echo ========================================
echo.

echo Sincronizando bootstrap admin...
start "animalitos-bootstrap" /wait cmd /c "cd /d D:\Proyectos\animalitos\backend && venv\Scripts\activate && python bootstrap_admin.py"

echo Iniciando backend FastAPI...
start "animalitos-backend" cmd /k "cd /d D:\Proyectos\animalitos\backend && venv\Scripts\activate && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

echo Esperando backend...
timeout /t 5 /nobreak >nul

echo Iniciando frontend Vue...
start "animalitos-frontend" cmd /k "cd /d D:\Proyectos\animalitos\frontend && npm run dev"

echo.
echo Backend API:  http://localhost:8000
echo API Docs:     http://localhost:8000/docs
echo Frontend:     http://localhost:5173
echo.
echo Credenciales admin y bootstrap:
echo   Revisar backend\.env y GUIA_IMPLEMENTACION_Y_OPERACION.md
echo.
pause
