# Ejecuta el backend y lo reinicia automáticamente si se cae (crash o
# cierre inesperado), en vez de quedar caído hasta que alguien lo note.
# Uso: desde PowerShell, ejecutar este script en vez de llamar a uvicorn
# directamente. Para detenerlo definitivamente: Ctrl+C.

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"

Set-Location $ProjectRoot

while ($true) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Iniciando el servidor..."
    & $Python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] El servidor se detuvo (codigo de salida: $LASTEXITCODE). Reiniciando en 3 segundos... (Ctrl+C para salir)"
    Start-Sleep -Seconds 3
}
