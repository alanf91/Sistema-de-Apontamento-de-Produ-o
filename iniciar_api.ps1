$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:J2I_EXCEL_PATH = Join-Path $PSScriptRoot 'PPCP_ACOMPAN.xlsx'
$env:J2I_SYNC_STATE = Join-Path $PSScriptRoot 'j2i_sync_data'
if (-not $env:J2I_SYNC_API_KEY) {
    $env:J2I_SYNC_API_KEY = Read-Host 'Cole a chave secreta da API (minimo 32 caracteres)'
}
& '.\.venv\Scripts\python.exe' -m uvicorn j2i_sync_api:app --host 127.0.0.1 --port 8001 --workers 1
