<# .SYNOPSIS  Restaura um backup .zip (pare o JARVIS antes). #>
param([Parameter(Mandatory = $true)][string]$File)
. "$PSScriptRoot\_common.ps1"
exit (Invoke-JarvisCtl "restore" (Resolve-Path $File).Path)
