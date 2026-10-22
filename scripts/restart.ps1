<# .SYNOPSIS  Reinicia o JARVIS. Aceita os mesmos parâmetros de start.ps1. #>
param([switch]$Dev, [switch]$NoAgent, [switch]$WhatsAppWeb)
. "$PSScriptRoot\_common.ps1"
$a = @("restart")
if ($Dev) { $a += "--dev" }
if ($NoAgent) { $a += "--no-agent" }
if ($WhatsAppWeb) { $a += "--whatsapp-web" }
exit (Invoke-JarvisCtl @a)
