<#
.SYNOPSIS  Inicia o JARVIS (backend + agente local) em segundo plano e abre o painel.
.PARAMETER Dev           Modo de desenvolvimento (recarrega ao editar o código).
.PARAMETER NoAgent       Não inicia o agente local (sem clipboard/voz/apps).
.PARAMETER WhatsAppWeb   Habilita o adaptador WhatsApp Web no agente.
.PARAMETER NoBrowser     Não abre o navegador.
#>
param([switch]$Dev, [switch]$NoAgent, [switch]$WhatsAppWeb, [switch]$NoBrowser)
. "$PSScriptRoot\_common.ps1"
$a = @("start")
if ($Dev) { $a += "--dev" }
if ($NoAgent) { $a += "--no-agent" }
if ($WhatsAppWeb) { $a += "--whatsapp-web" }
$code = Invoke-JarvisCtl @a
$port = if ($env:JARVIS_PORT) { $env:JARVIS_PORT } else { "8765" }
if ($code -eq 0 -and -not $NoBrowser) { Start-Process "http://127.0.0.1:$port/" }
exit $code
