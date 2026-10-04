# Run every test suite: python (incl. vector freshness), C vectors, frontend.
. "$PSScriptRoot\_env.ps1"
$py = Get-Python
Invoke-Checked $py @('tools\gen_vectors.py', '--check')
Invoke-Checked $py @('tools\gen_edge_vectors.py', '--check')
$dirs = @('backend\tests', 'ml\tests', 'simulator\tests') | Where-Object { Test-Path $_ }
Invoke-Checked $py (@('-m', 'pytest') + $dirs + @('-q'))
& "$PSScriptRoot\test-c.ps1"
if (Test-Path 'frontend\package.json') {
    Push-Location frontend
    try { Invoke-Checked 'npm' @('test', '--silent') } finally { Pop-Location }
}
Write-Host 'ALL TESTS PASSED'
