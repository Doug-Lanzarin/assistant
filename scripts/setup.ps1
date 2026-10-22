<#
.SYNOPSIS
  Configuração inicial do JARVIS no Windows 10/11 (chamado pelo setup.bat).
.DESCRIPTION
  Fase 1 (este script): Windows, Python, Node.js/npm, Git, ambiente virtual.
  Fase 2 (scripts/jarvis_setup.py, com o Python do ambiente virtual): dependências,
  interface, configuração, banco, IA, voz, microfone, testes e relatório.
  Pode ser executado quantas vezes quiser: só faz o que falta.
.PARAMETER NoVoice   Não instala a voz local (faster-whisper, Piper, openWakeWord; ~800 MB com modelos).
.PARAMETER WhatsApp  Instala o adaptador WhatsApp Web (Playwright + Chromium, ~150 MB).
.PARAMETER Ollama    Instala o Ollama (winget) e baixa o modelo local configurado (~1 GB + ~1,9 GB).
.PARAMETER Tests     Instala as ferramentas de teste e roda a suíte do backend.
.PARAMETER Force     Reinstala as dependências e recompila a interface.
.PARAMETER Offline   Não baixa modelos de voz.
.PARAMETER Yes       Não pergunta antes de instalar programas com o winget.
#>
param(
    [switch]$NoVoice, [switch]$WhatsApp, [switch]$Ollama, [switch]$Tests,
    [switch]$Force, [switch]$Offline, [switch]$Yes
)
$ErrorActionPreference = "Stop"
$BoundArgs = ($PSBoundParameters.Keys | ForEach-Object { "-$_" }) -join " "
$Repo = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Repo "backend"
$Venv = Join-Path $Backend ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$MinPy = [version]"3.11"
$MaxPy = [version]"3.13"   # testado até 3.13 (3.12 recomendado)
$MinNode = 20

# ------------------------------------------------------------------ log
function Get-DataDir {
    if ($env:JARVIS_DATA_DIR) { return $env:JARVIS_DATA_DIR }
    $envFile = Join-Path $Repo ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*JARVIS_DATA_DIR\s*=\s*"?([^"#]+?)"?\s*(#.*)?$') { return $Matches[1].Trim() }
        }
    }
    return (Join-Path $Repo "data")
}

function Write-Log([string]$Text) {
    if ($script:LogFile) { Add-Content -LiteralPath $script:LogFile -Value $Text -Encoding UTF8 }
}

function Write-Status([string]$Status, [string]$Text, [string]$How = "") {
    $colors = @{ OK = "Green"; AVISO = "Yellow"; FALHA = "Red"; INFO = "Cyan"; PULADO = "DarkGray" }
    $tag = ("[$Status]").PadRight(9)
    Write-Host " " -NoNewline
    Write-Host $tag -ForegroundColor $colors[$Status] -NoNewline
    Write-Host $Text
    Write-Log " $tag$Text"
    foreach ($h in ($How -split "`n")) {
        if ($h) { Write-Host "          -> $h"; Write-Log "          -> $h" }
    }
}

function Write-Section([string]$Title) {
    Write-Host "`n== $Title ==" -ForegroundColor Cyan
    Write-Log "`n== $Title =="
}

# ------------------------------------------------------------------ utilidades
function Test-Windows {
    if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) { return $false }
    return [Environment]::OSVersion.Platform -eq "Win32NT"
}

function Get-WindowsInfo {
    $v = [Environment]::OSVersion.Version
    $caption = "Windows"
    try { $caption = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).Caption.Trim() } catch { }
    [pscustomobject]@{
        Caption = $caption
        Build   = $v.Build
        Major   = $v.Major
        Is64    = [Environment]::Is64BitOperatingSystem
        Name    = $(if ($v.Major -eq 10 -and $v.Build -ge 22000) { "Windows 11" } elseif ($v.Major -eq 10) { "Windows 10" } else { "Windows $($v.Major).$($v.Minor)" })
    }
}

function Test-Admin {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Update-SessionPath {
    # Depois de instalar com o winget, o PATH novo só existe no registro.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ";"
}

function Invoke-Quiet([string]$Exe, [string[]]$Arguments) {
    # Executa um programa e devolve a saída (texto) ou $null, sem lançar exceção.
    try {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $global:LASTEXITCODE = 0   # não herdar o código de um comando anterior
        $out = & $Exe @Arguments 2>$null
        $ok = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prev
        if ($ok) { return ($out | Out-String).Trim() }
    } catch { $ErrorActionPreference = $prev }
    return $null
}

function ConvertTo-Version([string]$Text) {
    if ($Text -match '(\d+)\.(\d+)(\.(\d+))?') {
        $patch = if ($Matches[4]) { $Matches[4] } else { "0" }
        return [version]"$($Matches[1]).$($Matches[2]).$patch"
    }
    return $null
}

function Find-Python {
    # Prefere 3.12 (todos os recursos de voz têm pacotes). Ignora o atalho da Microsoft Store.
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("3.12", "3.11", "3.13")) { $candidates += , @("py", "-$v") }
    }
    foreach ($exe in @("python", "python3")) {
        $cmd = Get-Command $exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") { $candidates += , @($cmd.Source) }
    }
    foreach ($dir in @("Python312", "Python311", "Python313")) {
        $p = Join-Path $env:LOCALAPPDATA "Programs\Python\$dir\python.exe"
        if (Test-Path -LiteralPath $p) { $candidates += , @($p) }
    }
    foreach ($c in $candidates) {
        $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
        $out = Invoke-Quiet $exe ($pre + @("-c", "import sys, venv; print('%d.%d.%d' % sys.version_info[:3])"))
        $ver = ConvertTo-Version $out
        if ($ver -and $ver -ge $MinPy -and [version]"$($ver.Major).$($ver.Minor)" -le $MaxPy) {
            return [pscustomobject]@{ Exe = $exe; Pre = $pre; Version = $ver }
        }
    }
    return $null
}

function Get-NodeInfo {
    $node = Invoke-Quiet "node" @("--version")
    $npm = $null
    if (Get-Command npm.cmd -ErrorAction SilentlyContinue) { $npm = Invoke-Quiet "npm.cmd" @("--version") }
    [pscustomobject]@{ Node = (ConvertTo-Version $node); Npm = (ConvertTo-Version $npm) }
}

function Confirm-Install([string]$What) {
    if ($Yes) { return $true }
    $a = Read-Host "   Instalar $What agora com o winget (fonte oficial da Microsoft)? [S/n]"
    return ($a -eq "" -or $a -match '^(s|sim|y|yes)$')
}

function Install-WithWinget([string]$Id, [string]$Label, [string]$Scope = "") {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Status "FALHA" "winget não disponível para instalar $Label" "instale o 'Instalador de Aplicativo' pela Microsoft Store ou instale $Label manualmente"
        return $false
    }
    if (-not (Confirm-Install $Label)) { return $false }
    $wargs = @("install", "--id", $Id, "--exact", "--source", "winget", "--silent",
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity")
    if ($Scope) { $wargs += @("--scope", $Scope) }
    Write-Host "   instalando $Label ($Id)…"
    Write-Log "winget $($wargs -join ' ')"
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & winget @wargs | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    Update-SessionPath
    # -1978335189 = já instalado e sem atualização disponível
    if ($code -eq 0 -or $code -eq -1978335189) { return $true }
    Write-Status "FALHA" "o winget não conseguiu instalar $Label (código $code)"
    return $false
}

# ------------------------------------------------------------------ fase 1
function Invoke-Prerequisites {
    $missing = @()

    Write-Section "Sistema operacional"
    if (-not (Test-Windows)) {
        Write-Status "FALHA" "este instalador é para Windows 10/11" "em Linux/macOS (desenvolvimento): python scripts/jarvisctl.py setup"
        return 3
    }
    $w = Get-WindowsInfo
    if ($w.Major -lt 10 -or $w.Build -lt 17763) {
        Write-Status "FALHA" "$($w.Caption) (build $($w.Build)) não é suportado" "o JARVIS requer Windows 10 versão 1809 ou mais recente, ou Windows 11"
        return 3
    }
    if (-not $w.Is64) { Write-Status "FALHA" "Windows de 32 bits não é suportado" "os pacotes de voz e IA exigem 64 bits"; return 3 }
    Write-Status "OK" "$($w.Name) · $($w.Caption) (build $($w.Build), 64 bits)"
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        $cpu = (Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1).Name.Trim()
        $ram = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
        Write-Status "INFO" "CPU: $cpu · RAM: $ram GB"
        if ($ram -lt 7.5) { Write-Status "AVISO" "menos de 8 GB de RAM" "use o modelo de transcrição 'tiny' e evite IA local" }
    } catch { }
    if (Test-Admin) {
        Write-Status "AVISO" "o setup está rodando como Administrador" "não é necessário; prefira executar o setup.bat com dois cliques, sem 'Executar como administrador'"
    }

    Write-Section "Dependências do sistema"
    $hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
    Write-Status $(if ($hasWinget) { "OK" } else { "AVISO" }) ("winget " + $(if ($hasWinget) { "disponível" } else { "não encontrado (instalações automáticas indisponíveis)" }))

    # Python
    $py = Find-Python
    if (-not $py) {
        Write-Status "AVISO" "Python 3.11–3.13 não encontrado"
        if (Install-WithWinget "Python.Python.3.12" "Python 3.12" "user") { $py = Find-Python }
    }
    if ($py) {
        $note = if ($py.Version.Minor -eq 12) { "" } elseif ($py.Version.Minor -eq 13) { " (3.12 é o recomendado: a palavra de ativação pode não instalar no 3.13)" } else { "" }
        Write-Status "OK" "Python $($py.Version) ($($py.Exe) $($py.Pre -join ' '))$note"
    } else {
        Write-Status "FALHA" "Python 3.12 é obrigatório" "instale: winget install Python.Python.3.12   ou   https://www.python.org/downloads/windows/ (marque 'Add python.exe to PATH')"
        $missing += "Python"
    }

    # Node.js + npm (compila a interface React/Orb)
    $n = Get-NodeInfo
    $needNode = -not (Test-Path -LiteralPath (Join-Path $Repo "frontend\dist\index.html")) -or $Force
    if ((-not $n.Node -or $n.Node.Major -lt $MinNode) ) {
        $label = if ($n.Node) { "Node.js $($n.Node) é antigo (mínimo $MinNode)" } else { "Node.js não encontrado" }
        Write-Status "AVISO" $label "necessário para compilar a interface"
        if (Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS (o Windows pode pedir permissão de administrador só para este instalador)") { $n = Get-NodeInfo }
    }
    if ($n.Node -and $n.Node.Major -ge $MinNode -and $n.Npm) {
        Write-Status "OK" "Node.js $($n.Node) · npm $($n.Npm)"
    } elseif ($needNode) {
        Write-Status "FALHA" "Node.js $MinNode+ com npm é obrigatório para compilar a interface" "instale: winget install OpenJS.NodeJS.LTS   ou   https://nodejs.org (versão LTS); depois feche e abra o setup.bat"
        $missing += "Node.js"
    } else {
        Write-Status "AVISO" "Node.js indisponível; a interface já compilada será usada"
    }

    # Git (só para atualizar o projeto)
    $git = Invoke-Quiet "git" @("--version")
    if ($git) { Write-Status "OK" $git } else { Write-Status "INFO" "Git não encontrado (opcional, só para atualizar o JARVIS)" "winget install Git.Git" }

    # Runtime C++ (onnxruntime / CTranslate2 da voz local)
    if (-not $NoVoice) {
        $vc = Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\msvcp140.dll")
        if ($vc) { Write-Status "OK" "Microsoft Visual C++ Runtime" }
        else {
            Write-Status "AVISO" "Microsoft Visual C++ Runtime ausente (necessário para a voz local)"
            if (-not (Install-WithWinget "Microsoft.VCRedist.2015+.x64" "Visual C++ Runtime (pode pedir permissão de administrador)")) {
                Write-Status "AVISO" "a voz local pode não funcionar" "instale: winget install Microsoft.VCRedist.2015+.x64"
            }
        }
    }

    # Ollama (IA local) — só quando pedido explicitamente
    if ($Ollama) {
        $ol = (Get-Command ollama -ErrorAction SilentlyContinue) -or (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"))
        if ($ol) { Write-Status "OK" "Ollama instalado" }
        elseif (-not (Install-WithWinget "Ollama.Ollama" "Ollama (~1 GB)")) {
            Write-Status "AVISO" "Ollama não instalado" "https://ollama.com/download/windows"
        }
    }

    if ($missing.Count -gt 0) { return 2 }

    Write-Section "Ambiente virtual Python"
    $recreate = $false
    if (Test-Path -LiteralPath $VenvPy) {
        $vv = ConvertTo-Version (Invoke-Quiet $VenvPy @("-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"))
        if (-not $vv) {
            Write-Status "AVISO" "o ambiente virtual existente está quebrado (Python removido ou pasta movida)"
            $recreate = $true
        } elseif ($vv -lt $MinPy) {
            Write-Status "AVISO" "o ambiente virtual usa Python $vv (antigo)"
            $recreate = $true
        } else {
            Write-Status "OK" "backend\.venv (Python $vv) já existe"
        }
    } elseif (Test-Path -LiteralPath $Venv) {
        Write-Status "AVISO" "backend\.venv incompleto (instalação interrompida?)"
        $recreate = $true
    }
    if ($recreate) {
        # Não apaga nada: o ambiente antigo é renomeado e pode ser removido depois.
        $old = "$Venv.old-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item -LiteralPath $Venv -NewName (Split-Path -Leaf $old)
        Write-Status "INFO" "ambiente antigo renomeado para $(Split-Path -Leaf $old) (pode apagá-lo depois)"
    }
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        Write-Host "   criando backend\.venv com Python $($py.Version)…"
        & $py.Exe @($py.Pre + @("-m", "venv", $Venv)) | Out-Host
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPy)) {
            Write-Status "FALHA" "não foi possível criar o ambiente virtual" "verifique se o Python foi instalado com o módulo venv"
            return 1
        }
        Write-Status "OK" "backend\.venv criado"
    }
    return 0
}

function Invoke-Setup {
    $dataDir = Get-DataDir
    $logs = Join-Path $dataDir "logs"
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $script:LogFile = Join-Path $logs ("setup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
    try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Write-Host "JARVIS · configuração inicial" -ForegroundColor Cyan
    Write-Host "Pasta: $Repo"
    Write-Host "Relatório: $script:LogFile"
    Write-Log "JARVIS setup $(Get-Date -Format s) · $Repo · parâmetros: $BoundArgs"

    $code = Invoke-Prerequisites
    if ($code -ne 0) {
        Write-Section "Resultado"
        Write-Status "FALHA" "pré-requisitos ausentes: corrija os itens acima e execute setup.bat novamente"
        Write-Host "Relatório: $script:LogFile"
        return $code
    }

    $a = @((Join-Path $PSScriptRoot "jarvisctl.py"), "setup", "--log", $script:LogFile)
    if ($NoVoice) { $a += "--no-voice" }
    if ($WhatsApp) { $a += "--whatsapp" }
    if ($Ollama) { $a += "--ollama" }
    if ($Tests) { $a += "--tests" }
    if ($Force) { $a += "--force" }
    if ($Offline) { $a += "--offline" }
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    # Out-Host: a saída vai para a tela e não se mistura ao código de retorno.
    & $VenvPy @a | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return $code
}

# Ao ser carregado com ". .\setup.ps1" (testes), só define as funções.
if ($MyInvocation.InvocationName -ne ".") {
    try {
        exit (Invoke-Setup)
    } catch {
        Write-Status "FALHA" "erro inesperado: $($_.Exception.Message)" "execute setup.bat novamente; se persistir, envie o relatório em data\logs"
        Write-Log ($_ | Out-String)
        exit 1
    }
}
