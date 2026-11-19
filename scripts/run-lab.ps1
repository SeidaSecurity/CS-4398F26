<#
.SYNOPSIS
    Run the network management app natively on Windows for CML lab sessions (no Docker).

.DESCRIPTION
    Checks the toolchain and .env.lab, creates/updates .venv, then starts the API (this window)
    and the web UI in live mode (a second window). Docker/WSL stay off so CML can run.
    Never prints values from .env.lab.

.PARAMETER CheckOnly
    Run every check and install step, but do not start the API or the UI.
.PARAMETER NoWeb
    Start only the API (e.g. while Node is older than 22.12).
.PARAMETER Reinstall
    Force `pip install -e .[dev]` even if the venv already imports the app.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run-lab.ps1
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$NoWeb,
    [switch]$Reinstall,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root   # checkpoint B: SQLite path ./network_manager.db is relative to the CWD

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Stop-WithError([string]$What, [string]$Fix) {
    Write-Host "FAILED: $What" -ForegroundColor Red
    Write-Host "  Fix:  $Fix" -ForegroundColor Yellow
    exit 1
}
function Test-NodeVersion([string]$Raw) {
    # package.json engines: ^20.19.0 || >=22.12.0
    $v = [version]($Raw.TrimStart('v'))
    return ($v.Major -eq 20 -and $v.Minor -ge 19) -or ($v.Major -eq 22 -and $v.Minor -ge 12) -or ($v.Major -gt 22)
}

# --- Python ---------------------------------------------------------------------------------
Write-Step 'Checking Python (>= 3.11)'
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { Stop-WithError 'python is not on PATH.' 'Install Python 3.11+ from python.org and reopen the terminal.' }
$pyVersion = [version]((& python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim())
if ($pyVersion -lt [version]'3.11') { Stop-WithError "Python $pyVersion is too old." 'Install Python 3.11 or newer.' }
Write-Host "    Python $pyVersion"

# --- Virtual environment --------------------------------------------------------------------
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Step 'Creating .venv'
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Could not create .venv.' 'Run: python -m venv .venv  and read the error.' }
    $Reinstall = $true
}
# Import the package only (app.main would create the SQLite file as a side effect).
# Windows PowerShell 5.1 turns redirected native stderr into errors, so relax 'Stop' here.
$ErrorActionPreference = 'Continue'
& $Py -c "import app, uvicorn, dotenv, netmiko" 2>&1 | Out-Null
$importExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($Reinstall -or $importExit -ne 0) {
    Write-Step 'Installing the project into .venv (pip install -e .[dev])'
    & $Py -m pip install --disable-pip-version-check -q -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'pip install failed.' 'Scroll up for the pip error; then rerun with -Reinstall.' }
}

Write-Step 'Checking paramiko (< 5, required for IOSv SHA-1 key exchange; ADR-0003)'
$paramiko = (& $Py -c "import paramiko; print(paramiko.__version__)").Trim()
if ([version]$paramiko -ge [version]'5.0') {
    Stop-WithError "paramiko $paramiko cannot SSH to IOSv." 'Run: .venv\Scripts\python -m pip install "paramiko>=4,<5"'
}
Write-Host "    paramiko $paramiko"

# --- .env.lab -------------------------------------------------------------------------------
Write-Step 'Checking .env.lab'
$envFile = Join-Path $Root '.env.lab'
if (-not (Test-Path $envFile)) { Stop-WithError '.env.lab does not exist.' 'Copy-Item .env.lab.example .env.lab  then fill in the REPLACE_WITH_* values.' }
$placeholders = @(Select-String -Path $envFile -Pattern 'REPLACE_WITH_' -AllMatches | ForEach-Object { $_.Matches }).Count
if ($placeholders -gt 0) {
    Stop-WithError ".env.lab still has $placeholders REPLACE_WITH_* placeholder(s)." 'Edit .env.lab and replace them with the values used in lab/configs.'
}
# Checkpoint A: python-dotenv does not override variables already set in the shell.
$keys = @(Get-Content $envFile | ForEach-Object { if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=') { $Matches[1] } })
$shadowed = @($keys | Where-Object { [Environment]::GetEnvironmentVariable($_) })
if ($shadowed.Count -gt 0) {
    Write-Host "WARNING: these are already set in your shell and will override .env.lab: $($shadowed -join ', ')" -ForegroundColor Yellow
    Write-Host '         Clear them with: Remove-Item Env:NAME' -ForegroundColor Yellow
}
# Admin account settings (R7.4): check them with the app's OWN password policy, so a rejected
# password is caught here instead of as a log line after startup (found on the lab, 2026-11-19).
# Values travel only through environment variables of the child process and are never printed.
$envValues = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$') { $envValues[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'") }
}
if (-not $envValues['ADMIN_USERNAME'] -or -not $envValues['ADMIN_PASSWORD']) {
    Write-Host 'WARNING: ADMIN_USERNAME / ADMIN_PASSWORD are not set in .env.lab. Fine if an admin account' -ForegroundColor Yellow
    Write-Host '         already exists; otherwise nobody can log in. Add both and restart.' -ForegroundColor Yellow
} else {
    $env:NETMGR_CHECK_USER = $envValues['ADMIN_USERNAME']
    $env:NETMGR_CHECK_PASSWORD = $envValues['ADMIN_PASSWORD']
    $policyCheck = "import os`nfrom app.auth import PasswordPolicyError, validate_password`ntry:`n    validate_password(os.environ['NETMGR_CHECK_PASSWORD'], os.environ['NETMGR_CHECK_USER'])`nexcept PasswordPolicyError as exc:`n    print(exc)"
    $ErrorActionPreference = 'Continue'
    $policyError = (& $Py -c $policyCheck 2>&1 | Out-String).Trim()
    $ErrorActionPreference = 'Stop'
    Remove-Item Env:NETMGR_CHECK_USER, Env:NETMGR_CHECK_PASSWORD
    if ($policyError) {
        Stop-WithError "ADMIN_PASSWORD in .env.lab would be rejected: $policyError" 'Edit ADMIN_PASSWORD in .env.lab (8-64 characters, not a common password, not the username) and rerun.'
    }
}
Write-Host "    OK ($($keys.Count) keys; values not shown)"

# --- Node / web UI --------------------------------------------------------------------------
if (-not $NoWeb) {
    Write-Step 'Checking Node (^20.19 or >= 22.12)'
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeCmd) { Stop-WithError 'node is not on PATH.' 'Install Node 22 LTS from nodejs.org, or rerun with -NoWeb.' }
    $nodeVersion = (& node --version).Trim()
    if (-not (Test-NodeVersion $nodeVersion)) {
        Stop-WithError "Node $nodeVersion is too old for the web build." 'Install the current Node 22 LTS, or rerun with -NoWeb to start only the API.'
    }
    Write-Host "    Node $nodeVersion"
    $binding = Join-Path $Root 'web\node_modules\@rolldown\binding-win32-x64-msvc'
    if (-not (Test-Path $binding)) {
        Write-Step 'Installing web dependencies (npm ci) - missing or installed under an older Node'
        Push-Location (Join-Path $Root 'web')
        try { & npm ci --no-audit --no-fund } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Stop-WithError 'npm ci failed.' 'Delete web\node_modules and rerun.' }
    }
}

Write-Host ''
Write-Host 'All checks passed.' -ForegroundColor Green
if ($CheckOnly) { exit 0 }

# --- Start ----------------------------------------------------------------------------------
if (-not $NoWeb) {
    Write-Step 'Starting the web UI (live mode) in a second window'
    $webDir = Join-Path $Root 'web'
    Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$webDir'; `$env:VITE_API_MODE='live'; npm run dev"
}
Write-Step "Starting the API on http://127.0.0.1:$Port (syslog on UDP/TCP 514). Ctrl+C to stop."
# No --reload: it would start a second copy of the background poller and syslog listener.
& $Py -m uvicorn app.main:app --env-file $envFile --host 127.0.0.1 --port $Port
