# Regenerate (or -Check) the cross-language test vectors.
param([switch]$Check)
. "$PSScriptRoot\_env.ps1"
$a = @('tools\gen_vectors.py'); if ($Check) { $a += '--check' }
Invoke-Checked (Get-Python) $a
