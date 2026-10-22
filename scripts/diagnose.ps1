<# .SYNOPSIS  Diagnóstico completo: dependências, configuração, banco, portas e ambiente. #>
. "$PSScriptRoot\_common.ps1"
$code = Invoke-JarvisCtl "doctor"
Invoke-JarvisCtl "env-report" | Out-Null
$logs = Join-Path $Repo "data\logs"
if (Test-Path $logs) {
    Write-Host "`nÚltimos erros registrados:" -ForegroundColor Cyan
    Get-ChildItem $logs -Filter *.log | ForEach-Object {
        Select-String -Path $_.FullName -Pattern '"level": "ERROR"|ERROR' | Select-Object -Last 5 | ForEach-Object { $_.Line }
    }
}
exit $code
