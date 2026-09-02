@echo off
REM Procesa los documentos en /documents y (re)construye la base vectorial.
REM Ejecutar cada vez que agregues, quites o modifiques documentos.

cd /d "%~dp0"
call venv\Scripts\python.exe scripts\ingest.py
pause
