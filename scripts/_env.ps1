# Shared helpers for scripts/*.ps1 (dot-source this file).
$ErrorActionPreference = 'Stop'
$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $script:Root

function Get-Python {
    $venv = Join-Path $script:Root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python not found. Run scripts\setup.ps1 first."
}

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe exited with code $LASTEXITCODE" }
}

function Get-GitBash {
    # Prefer Git for Windows' bash: plain `bash` may resolve to WSL.
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Git\bin\bash.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\bin\bash.exe')
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    throw "Git Bash not found (install Git for Windows)."
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker not found. Install Docker Desktop and start it (see README)."
    }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running. Start it and retry." }
}
