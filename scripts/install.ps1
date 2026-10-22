<#
.SYNOPSIS
  Compatibilidade: o instalador agora é o setup.bat (scripts\setup.ps1).
  Este atalho repassa as opções antigas para o novo instalador.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -WhatsApp
#>
param([switch]$Voice, [switch]$WhatsApp, [switch]$NoDesktop, [switch]$SkipFrontend, [switch]$NoVoice)
# -Voice era opcional; agora a voz local é instalada por padrão (use -NoVoice para pular).
# -NoDesktop e -SkipFrontend não existem mais: o setup só refaz o que mudou.
$a = @{}
if ($NoVoice) { $a.NoVoice = $true }
if ($WhatsApp) { $a.WhatsApp = $true }
& (Join-Path $PSScriptRoot "setup.ps1") @a
exit $LASTEXITCODE
