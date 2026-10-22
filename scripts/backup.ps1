<# .SYNOPSIS  Cria um backup (banco + biblioteca) em data\backups. #>
. "$PSScriptRoot\_common.ps1"
exit (Invoke-JarvisCtl "backup")
