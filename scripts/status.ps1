<# .SYNOPSIS  Mostra se o JARVIS está em execução. #>
. "$PSScriptRoot\_common.ps1"
exit (Invoke-JarvisCtl "status")
