# Create .venv and install the backend (+ api, ml, dev extras) and the simulator.
. "$PSScriptRoot\_env.ps1"
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { Invoke-Checked 'py' @('-3.12', '-m', 'venv', '.venv') } else { Invoke-Checked 'python' @('-m', 'venv', '.venv') }
}
$p = Get-Python
Invoke-Checked $p @('-m', 'pip', 'install', '-U', 'pip')
Invoke-Checked $p @('-m', 'pip', 'install', '-e', 'backend[api,ml,dev]')
if (Test-Path 'simulator\pyproject.toml') { Invoke-Checked $p @('-m', 'pip', 'install', '-e', 'simulator') }
Write-Host 'setup complete'
