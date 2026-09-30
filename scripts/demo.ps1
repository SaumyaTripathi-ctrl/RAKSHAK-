# Bring the stack up and run the scripted end-to-end demo.
. "$PSScriptRoot\_env.ps1"
Test-Docker
Invoke-Checked 'docker' @('compose', 'up', '--build', '-d')
Invoke-Checked (Get-Python) @('tools\demo.py')
