# Train the ML models on simulated produce shipments (writes ml\artifacts + model card).
. "$PSScriptRoot\_env.ps1"
Invoke-Checked (Get-Python) @('-m', 'rakshak_ml.train', '--out', 'mlrtifacts')
