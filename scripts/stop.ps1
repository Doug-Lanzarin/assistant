<# .SYNOPSIS  Encerra o JARVIS de forma segura (backend e agente). #>
. "$PSScriptRoot\_common.ps1"
exit (Invoke-JarvisCtl "stop")
