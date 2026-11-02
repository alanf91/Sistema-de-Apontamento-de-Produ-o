$ErrorActionPreference = "Stop"

$ArquivoChave = Join-Path $env:LOCALAPPDATA "J2I_PCP_SYNC\api_key.xml"

$Segredo = Import-Clixml -Path $ArquivoChave

$Credencial = [System.Net.NetworkCredential]::new("", $Segredo)

$env:J2I_SYNC_API_KEY = $Credencial.Password

Set-Location "C:\J2I_SERVER\apps\j2i_mes\app"

& ".\.venv\Scripts\python.exe" -m uvicorn j2i_sync_api:app --host 127.0.0.1 --port 8001
