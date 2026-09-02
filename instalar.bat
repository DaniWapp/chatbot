@echo off
REM Instala el entorno virtual y las dependencias del proyecto.
REM Ejecutar una sola vez (o de nuevo si cambia requirements.txt).

cd /d "%~dp0"

echo === Creando entorno virtual (venv) ===
py -m venv venv
if errorlevel 1 (
    echo ERROR: no se encontro el lanzador "py". Instala Python desde https://www.python.org/downloads/
    pause
    exit /b 1
)

echo === Instalando dependencias ===
call venv\Scripts\python.exe -m pip install --upgrade pip
call venv\Scripts\python.exe -m pip install -r requirements.txt

if not exist ".env" (
    echo === Creando archivo .env a partir de .env.example ===
    copy .env.example .env
    echo IMPORTANTE: abre el archivo .env y agrega tu GROQ_API_KEY antes de continuar.
)

echo.
echo Instalacion completa.
echo Siguiente paso: edita .env con tu GROQ_API_KEY y luego ejecuta "ingestar.bat"
pause
