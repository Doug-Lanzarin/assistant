<# .SYNOPSIS  Executa os testes automatizados do backend e da interface. #>
. "$PSScriptRoot\_common.ps1"
exit (Invoke-JarvisCtl "test")
