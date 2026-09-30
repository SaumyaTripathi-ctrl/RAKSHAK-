# Start the whole stack: mosquitto (TLS), postgres, api, web, simulator.
. "$PSScriptRoot\_env.ps1"
Test-Docker
Invoke-Checked 'docker' @('compose', 'up', '--build', '-d')
Write-Host "Rakshak is starting. Web: http://localhost:8080   API docs: http://localhost:8000/docs"
Write-Host "Logs: docker compose logs -f     Stop: scripts\down.ps1"
