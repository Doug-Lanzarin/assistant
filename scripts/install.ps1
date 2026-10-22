<#
.SYNOPSIS
  Instala o JARVIS no Windows (sem privilégios de administrador).
.PARAMETER Voice
  Instala voz local (faster-whisper, openWakeWord, Piper, SAPI) e baixa os modelos (~250 MB).
.PARAMETER WhatsApp
  Instala o adaptador WhatsApp Web (Playwright + Chromium, ~150 MB).
.PARAMETER NoDesktop
  Não instala bandeja/atalho/notificações do agente.
.PARAMETER SkipFrontend
  Não compila a interface (requer Node.js 20+ quando não pulado).
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Voice
#>
param([switch]$Voice, [switch]$WhatsApp, [switch]$NoDesktop, [switch]$SkipFrontend)
. "$PSScriptRoot\_common.ps1"

Write-Host "== JARVIS: diagnóstico do ambiente ==" -ForegroundColor Cyan
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$disk = Get-PSDrive -Name ($Repo.Substring(0, 1))
$report = [ordered]@{
    windows        = "$($os.Caption) $($os.Version) (build $($os.BuildNumber))"
    cpu            = $cpu.Name.Trim()
    cores          = $cpu.NumberOfCores
    threads        = $cpu.NumberOfLogicalProcessors
    ram_total_gb   = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    ram_free_gb    = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    disk_free_gb   = [math]::Round($disk.Free / 1GB, 1)
    gpu            = (Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join "; "
    python         = $null
    node           = $null
    git            = [bool](Get-Command git -ErrorAction SilentlyContinue)
}
$report.GetEnumerator() | ForEach-Object { Write-Host ("  {0,-14} {1}" -f $_.Key, $_.Value) }
if ($report.ram_total_gb -lt 7.5) { Write-Warning "Menos de 8 GB de RAM: use stt_model=tiny e evite modelos locais grandes." }
if ($report.disk_free_gb -lt 3) { throw "Pouco espaço em disco (menos de 3 GB livres)." }

# Python 3.12 é o recomendado (openWakeWord ainda não publica tudo para 3.13)
$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("3.12", "3.11", "3.13")) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & py "-$v" -c "import sys" 2>$null | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prev
        if ($ok) { $pyExe = "py"; $pyArgs = @("-$v"); break }
    }
}
if (-not $pyExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $ver = & python -c "import sys;print('%d.%d' % sys.version_info[:2])"
    if ([version]$ver -ge [version]"3.11") { $pyExe = "python" }
}
if (-not $pyExe) { throw "Python 3.11+ não encontrado. Instale o Python 3.12 em https://www.python.org/downloads/windows/ (marque 'Add to PATH')." }
$report.python = (& $pyExe @pyArgs --version) -join ""
Write-Host "  python         $($report.python)"

Write-Host "`n== Ambiente virtual e dependências ==" -ForegroundColor Cyan
if (-not (Test-Path $VenvPy)) { & $pyExe @pyArgs -m venv (Join-Path $Backend ".venv") }
& $VenvPy -m pip install --upgrade pip --quiet
& $VenvPy -m pip install -r (Join-Path $Backend "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências do backend." }
if (-not $NoDesktop) { & $VenvPy -m pip install -r (Join-Path $Backend "requirements-desktop.txt") --quiet }
if ($Voice) { & $VenvPy -m pip install -r (Join-Path $Backend "requirements-voice.txt") --quiet }
if ($WhatsApp) {
    & $VenvPy -m pip install -r (Join-Path $Backend "requirements-whatsapp.txt") --quiet
    & $VenvPy -m playwright install chromium
}

Write-Host "`n== Interface (PWA) ==" -ForegroundColor Cyan
$node = Get-Command node -ErrorAction SilentlyContinue
if ($SkipFrontend) {
    Write-Host "  pulado (-SkipFrontend)"
} elseif (-not $node) {
    Write-Warning "Node.js não encontrado: instale o Node.js LTS (https://nodejs.org) e rode novamente para compilar a interface."
} else {
    $report.node = (& node --version)
    Push-Location (Join-Path $Repo "frontend")
    try {
        & npm ci --no-audit --no-fund
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar a interface." }
    } finally { Pop-Location }
}

Write-Host "`n== Configuração ==" -ForegroundColor Cyan
$cfg = Join-Path $Repo "config\jarvis.toml"
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $Repo "config\jarvis.example.toml") $cfg
    Write-Host "  criado config\jarvis.toml (revise os caminhos dos apps e pastas)"
}
$envFile = Join-Path $Repo ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $Repo ".env.example") $envFile; Write-Host "  criado .env" }
$dataDir = Join-Path $Repo "data"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$report | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $dataDir "environment-report.json")

if ($Voice) {
    Write-Host "`n== Modelos de voz ==" -ForegroundColor Cyan
    & $VenvPy (Join-Path $PSScriptRoot "download_voice_models.py")
}

Write-Host "`n== Verificação ==" -ForegroundColor Cyan
& $VenvPy $Ctl doctor
Write-Host "`nPronto. Inicie com: scripts\start.ps1" -ForegroundColor Green
