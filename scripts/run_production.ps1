$ErrorActionPreference = "Stop"

if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

Remove-Item Env:NOW_OVERRIDE -ErrorAction SilentlyContinue
Remove-Item Env:TARGET_SENDER_NAME -ErrorAction SilentlyContinue

$env:RSS_URL = "https://idapfile.mdr.gov.br/idap/api/rss/cap"
$env:OUT_DIR = "out"
$env:HISTORY_PATH = ".cache/historico_alertas.json"
$env:STATE_PATH = ".cache/state.json"
$env:ALERTS_GEOJSON_PATH = "site/data/alertas_idap.geojson"
$env:UF_GEOJSON_PATH = "site/data/geojs-es.json"
$env:MUN_GEOJSON_PATH = "site/data/geojs-es.json"
$env:SITE_DIR = "site"
$env:WINDOW_HOURS = "24"
$env:RETENTION_HOURS = "72"
$env:RSS_TIMEOUT_SECONDS = "15"
$env:RSS_RETRIES = "2"

$venvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    Write-Host "[RUN] $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description falhou com codigo $LASTEXITCODE"
    }
    Write-Host "[OK] $Description"
}

Write-Host "[INFO] Modo: producao"
Write-Host "[INFO] RSS_URL=$env:RSS_URL"
Write-Host "[INFO] Timeout por tentativa: $env:RSS_TIMEOUT_SECONDS s"
Write-Host "[INFO] Tentativas: $env:RSS_RETRIES"

if (Get-Command poetry -ErrorAction SilentlyContinue) {
    Write-Host "[INFO] Runtime: poetry"
    Invoke-Checked { poetry run python scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { poetry run python scripts\build_dashboard.py } "Geracao do dashboard"
} elseif (Test-Path $venvPython) {
    Write-Host "[INFO] Runtime: .venv"
    Invoke-Checked { & $venvPython scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { & $venvPython scripts\build_dashboard.py } "Geracao do dashboard"
} else {
    Write-Host "[INFO] Runtime: python do PATH"
    Invoke-Checked { python scripts\idap_daily_maps.py } "Coleta CAP/IDAP oficial"
    Invoke-Checked { python scripts\build_dashboard.py } "Geracao do dashboard"
}

Write-Host "[OK] Producao finalizada"
