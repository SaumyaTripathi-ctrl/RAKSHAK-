. "$PSScriptRoot\_env.ps1"
$py = Get-Python
$dirs = @('backend', 'ml', 'simulator', 'tools') | Where-Object { Test-Path $_ }
Invoke-Checked $py (@('-m', 'ruff', 'check') + $dirs)
if (Test-Path 'frontend\package.json') {
    Push-Location frontend
    try { Invoke-Checked 'npm' @('run', 'lint', '--silent') } finally { Pop-Location }
}
