@echo off
REM Inicia el backend (API + interfaz web) en http://localhost:8000

cd /d "%~dp0"
echo Iniciando el chatbot en http://localhost:8000 ...
echo Presiona Ctrl+C para detenerlo.
call venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
