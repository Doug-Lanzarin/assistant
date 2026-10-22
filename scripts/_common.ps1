# Funções compartilhadas pelos scripts do JARVIS (Windows PowerShell 5.1+).
$ErrorActionPreference = "Stop"
$Script:Repo = Split-Path -Parent $PSScriptRoot
$Script:Backend = Join-Path $Repo "backend"
$Script:VenvPy = Join-Path $Backend ".venv\Scripts\python.exe"
$Script:Ctl = Join-Path $PSScriptRoot "jarvisctl.py"

function Get-JarvisPython {
    if (Test-Path $Script:VenvPy) { return $Script:VenvPy }
    throw "Ambiente virtual não encontrado. Rode primeiro o setup.bat (na pasta do JARVIS)"
}

function Invoke-JarvisCtl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CtlArgs)
    $py = Get-JarvisPython
    # Out-Host: a saída vai para a tela e só o código de saída é retornado.
    & $py $Script:Ctl @CtlArgs | Out-Host
    return $LASTEXITCODE
}
