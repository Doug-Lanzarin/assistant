<#
.SYNOPSIS  Ativa/desativa o início do JARVIS junto com o Windows (pasta Inicializar do usuário, sem admin).
.EXAMPLE   scripts\autostart.ps1 -Enable
#>
param([switch]$Enable, [switch]$Disable)
. "$PSScriptRoot\_common.ps1"
if ($Enable) { exit (Invoke-JarvisCtl "autostart" "enable") }
if ($Disable) { exit (Invoke-JarvisCtl "autostart" "disable") }
exit (Invoke-JarvisCtl "autostart" "status")
