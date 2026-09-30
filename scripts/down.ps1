param([switch]$Volumes)
. "$PSScriptRoot\_env.ps1"
Test-Docker
$a = @('compose', 'down'); if ($Volumes) { $a += '-v' }
Invoke-Checked 'docker' $a
