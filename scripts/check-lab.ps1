<#
.SYNOPSIS
    Smoke-test the running app and the CML lab; prints a pass/fail table.

.DESCRIPTION
    Run while scripts\run-lab.ps1 is running. "PASS" means the actual result matched the
    EXPECTED one, so ios-lab-4 (stopped on purpose, SRS 8.2 "unreachable node") passes when it
    is unreachable. Exit code 1 if any check fails.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check-lab.ps1
#>
[CmdletBinding()]
param(
    [string]$ApiBase = 'http://127.0.0.1:8000',
    [string[]]$Routers = @('192.168.198.11', '192.168.198.12', '192.168.198.13', '192.168.198.14'),
    [string[]]$ExpectedDown = @('192.168.198.14'),
    [string]$SyslogTarget = '127.0.0.1',
    [string]$EnvFile = '',   # default: .env.lab in the repo root (set below)
    [int]$SyslogPort = 514
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults, so resolve it here.
if (-not $EnvFile) { $EnvFile = Join-Path (Split-Path -Parent $PSScriptRoot) '.env.lab' }
$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$Check, [string]$Target, [string]$Expected, [string]$Actual, [string]$Result, [string]$Hint = '') {
    $results.Add([pscustomobject]@{ Check = $Check; Target = $Target; Expected = $Expected; Actual = $Actual; Result = $Result; Hint = $Hint })
}
# The API requires login (R7.1, ADR-0005): all calls share this session, which holds the cookie.
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
function Get-Api([string]$Path) { Invoke-RestMethod -Uri "$ApiBase$Path" -TimeoutSec 5 -WebSession $session }
function Get-ApiList([string]$Path) {
    # Windows PowerShell 5.1 returns a JSON array as ONE object; enumerate it so @() counts items.
    $response = Invoke-RestMethod -Uri "$ApiBase$Path" -TimeoutSec 5 -WebSession $session
    foreach ($item in $response) { $item }
}
function Read-EnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$Name\s*=(.*)$") { return $Matches[1].Trim().Trim('"').Trim("'") }
    }
    return $null
}
function Test-Tcp([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync($HostName, $Port).Wait($TimeoutMs) -and $client.Connected }
    catch { return $false }
    finally { $client.Close() }
}

# 1. API health --------------------------------------------------------------------------------
$apiUp = $false
try {
    $health = Get-Api '/health'
    $apiUp = $health.status -eq 'ok'
    Add-Result 'API health' $ApiBase 'ok' $health.status ($(if ($apiUp) { 'PASS' } else { 'FAIL' }))
} catch {
    Add-Result 'API health' $ApiBase 'ok' 'no response' 'FAIL' 'Start the app: scripts\run-lab.ps1'
}

# 1b. Log in as the admin from .env.lab (values read here, never printed) ----------------------
$loggedIn = $false
if ($apiUp) {
    $adminUser = Read-EnvValue 'ADMIN_USERNAME'
    $adminPassword = Read-EnvValue 'ADMIN_PASSWORD'
    if (-not $adminUser -or -not $adminPassword) {
        Add-Result 'API login (admin)' $ApiBase 'logged in' 'ADMIN_* not in .env.lab' 'FAIL' 'Add ADMIN_USERNAME and ADMIN_PASSWORD to .env.lab'
    } else {
        $body = @{ username = $adminUser; password = $adminPassword } | ConvertTo-Json
        try {
            $me = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/auth/login" -Body $body -ContentType 'application/json' -WebSession $session -TimeoutSec 5
            $loggedIn = $me.role -eq 'admin'
            Add-Result 'API login (admin)' $ApiBase 'logged in as admin' "logged in as $($me.role)" ($(if ($loggedIn) { 'PASS' } else { 'FAIL' })) 'The ADMIN_USERNAME account is not an admin'
        } catch {
            Add-Result 'API login (admin)' $ApiBase 'logged in as admin' 'login refused' 'FAIL' 'Wrong ADMIN_* values, or the admin was never created (see the API window for "Admin bootstrap")'
        }
        $body = $null; $adminPassword = $null
    }
}
$apiUp = $apiUp -and $loggedIn   # the checks below need an authenticated session

# 2. Syslog round trip (local) -----------------------------------------------------------------
if ($apiUp) {
    $token = 'netmgr-check-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
    $message = "<14>1 $timestamp check-lab netmgr - - - smoke test $token"   # RFC 5424, user.info
    $udp = New-Object System.Net.Sockets.UdpClient
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($message)
        [void]$udp.Send($bytes, $bytes.Length, $SyslogTarget, $SyslogPort)
    } finally { $udp.Close() }
    $found = $null
    foreach ($attempt in 1..10) {
        Start-Sleep -Milliseconds 500
        $found = @(Get-ApiList "/api/v1/logs?query=$token")
        if ($found.Count -gt 0) { break }
    }
    if ($found.Count -gt 0) {
        $parsed = if ($found[0].parsed) { 'stored, parsed' } else { 'stored, UNPARSED' }
        Add-Result 'Syslog round trip' "${SyslogTarget}:$SyslogPort" 'stored, parsed' $parsed ($(if ($found[0].parsed) { 'PASS' } else { 'FAIL' }))
    } else {
        Add-Result 'Syslog round trip' "${SyslogTarget}:$SyslogPort" 'stored, parsed' 'not found in 5 s' 'FAIL' 'Is SYSLOG_ENABLED=true in .env.lab? Is another program using port 514?'
    }
} else {
    Add-Result 'Syslog round trip' "${SyslogTarget}:$SyslogPort" 'stored, parsed' 'skipped (API down or not logged in)' 'FAIL'
}

# 3. Firewall: the local test above passes even if routers are blocked (checkpoint D) ----------
# Read rules through the HNetCfg.FwPolicy2 COM API: it works without Administrator and is fast.
# (Get-NetFirewallPortFilter -Protocol returns "Access is denied" to non-admin users.)
function Test-PortInList([string]$Ports, [int]$Port) {
    foreach ($part in ($Ports -split ',')) {
        $p = $part.Trim()
        if ($p -eq '*') { return $true }
        if ($p -match '^(\d+)-(\d+)$') { if ($Port -ge [int]$Matches[1] -and $Port -le [int]$Matches[2]) { return $true } }
        elseif ($p -eq "$Port") { return $true }
    }
    return $false
}
$fwRules = $null
try { $fwRules = @((New-Object -ComObject HNetCfg.FwPolicy2).Rules) } catch { $fwRules = $null }
foreach ($proto in @(@{ Name = 'UDP'; Number = 17 }, @{ Name = 'TCP'; Number = 6 })) {
    $check = "Firewall inbound $($proto.Name) $SyslogPort"
    $hint = 'Run the New-NetFirewallRule commands in lab/README.md as Administrator'
    if ($null -eq $fwRules) {
        # Could not check is not the same as failed: report it as a warning.
        Add-Result $check 'Windows Defender' 'allowed (Public)' 'could not read firewall rules' 'WARN' 'Verify manually: Get-NetFirewallRule -DisplayName "netmgr syslog*"'
        continue
    }
    # Direction 1 = inbound, Action 1 = allow; Profiles is a bitmask where Public = 4.
    $rules = @($fwRules | Where-Object {
        $_.Enabled -and $_.Direction -eq 1 -and $_.Action -eq 1 -and $_.Protocol -eq $proto.Number -and
        $_.LocalPorts -and (Test-PortInList $_.LocalPorts $SyslogPort) })
    $publicOk = @($rules | Where-Object { ($_.Profiles -band 4) -ne 0 }).Count -gt 0
    $actual = if ($rules.Count -eq 0) { 'no allow rule' } elseif ($publicOk) { 'allowed (Public)' } else { 'allowed, NOT on Public profile' }
    Add-Result $check 'Windows Defender' 'allowed (Public)' $actual ($(if ($publicOk) { 'PASS' } else { 'FAIL' })) $hint
}

# 4. Routers: ping and SSH port from Windows ----------------------------------------------------
$windowsPing = @{}
foreach ($ip in $Routers) {
    $wantUp = $ExpectedDown -notcontains $ip
    $want = if ($wantUp) { 'reachable' } else { 'unreachable' }
    $ping = Test-Connection -ComputerName $ip -Count 1 -Quiet -ErrorAction SilentlyContinue
    $windowsPing[$ip] = [bool]$ping
    $pingActual = if ($ping) { 'reachable' } else { 'unreachable' }
    Add-Result 'Ping' $ip $want $pingActual ($(if ($ping -eq $wantUp) { 'PASS' } else { 'FAIL' })) 'Check the router is started and Gi0/0 has its IP'
    $ssh = Test-Tcp $ip 22
    $sshActual = if ($ssh) { 'reachable' } else { 'unreachable' }
    Add-Result 'TCP 22 (SSH)' $ip $want $sshActual ($(if ($ssh -eq $wantUp) { 'PASS' } else { 'FAIL' })) 'Check "show ip ssh" and the vty lines on the router'
}

# 5. The app's own view: proves the app's ICMP works, not just PowerShell's (checkpoint E) -------
if ($apiUp) {
    $devices = @(Get-ApiList '/api/v1/devices')
    $statuses = @(Get-ApiList '/api/v1/monitoring/status')
    foreach ($ip in $Routers) {
        $wantState = if ($ExpectedDown -contains $ip) { 'down' } else { 'up' }
        $device = $devices | Where-Object { $_.management_ip -eq $ip } | Select-Object -First 1
        if (-not $device) {
            Add-Result 'App monitoring state' $ip $wantState 'not registered' 'WARN' 'Add the device on the Devices screen (name must match .env.lab)'
            continue
        }
        $status = $statuses | Where-Object { $_.device_id -eq $device.id } | Select-Object -First 1
        if (-not $status) {
            Add-Result 'App monitoring state' "$ip ($($device.name))" $wantState 'not polled yet' 'WARN' 'Wait one poll interval (60 s); check MONITORING_ENABLED=true'
        } elseif ($status.state -eq $wantState) {
            Add-Result 'App monitoring state' "$ip ($($device.name))" $wantState $status.state 'PASS'
        } elseif ($wantState -eq 'down' -and $status.consecutive_failures -lt 2) {
            Add-Result 'App monitoring state' "$ip ($($device.name))" $wantState "up, $($status.consecutive_failures) failure(s)" 'WARN' 'Down needs 2 consecutive failed polls; wait another interval'
        } else {
            $hint = if ($status.state -eq 'down' -and -not $windowsPing[$ip]) {
                'Unreachable from Windows too: fix the lab first (router started? CML running? WSL/Hyper-V off?)'
            } elseif ($status.state -eq 'down') {
                "Windows can ping it but the app can't: app ICMP issue on Windows; check the API window"
            } else {
                'App says up but Windows cannot reach it: check for an IP conflict'
            }
            Add-Result 'App monitoring state' "$ip ($($device.name))" $wantState $status.state 'FAIL' $hint
        }
    }
}

if ($loggedIn) {
    try { [void](Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/auth/logout" -WebSession $session -TimeoutSec 5) } catch { }
}

# --- Report -------------------------------------------------------------------------------------
$results | Format-Table Check, Target, Expected, Actual, Result -AutoSize | Out-String -Width 200 | Write-Host
$failed = @($results | Where-Object Result -eq 'FAIL')
$warned = @($results | Where-Object Result -eq 'WARN')
foreach ($row in $failed + $warned) { if ($row.Hint) { Write-Host ("{0} {1} [{2}]: {3}" -f $row.Result, $row.Check, $row.Target, $row.Hint) -ForegroundColor Yellow } }
$summary = "{0} passed, {1} warnings, {2} failed" -f @($results | Where-Object Result -eq 'PASS').Count, $warned.Count, $failed.Count
if ($failed.Count -gt 0) { Write-Host $summary -ForegroundColor Red; exit 1 } else { Write-Host $summary -ForegroundColor Green; exit 0 }
