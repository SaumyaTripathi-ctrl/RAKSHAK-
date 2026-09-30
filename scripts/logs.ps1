. "$PSScriptRoot\_env.ps1"
Test-Docker
Invoke-Checked 'docker' @('compose', 'logs', '-f', '--tail=100')
