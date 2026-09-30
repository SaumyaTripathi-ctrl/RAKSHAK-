# C codec vs Python vectors. Uses zig (pip package "ziglang") as the C compiler if no cc is available.
. "$PSScriptRoot\_env.ps1"
$py = Get-Python
if (-not $env:CC) {
    if (Get-Command gcc -ErrorAction SilentlyContinue) { $env:CC = 'gcc' }
    else {
        & $py -m ziglang version *> $null
        if ($LASTEXITCODE -ne 0) { Invoke-Checked $py @('-m', 'pip', 'install', '-q', 'ziglang') }
        $env:CC = ($py.Replace([string][char]92, '/')) + ' -m ziglang cc'
    }
}
Invoke-Checked (Get-GitBash) @('firmware/common/test/run_host_test.sh')
