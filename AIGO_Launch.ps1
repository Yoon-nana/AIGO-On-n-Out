param([string]$LaunchUri = 'aigo-robodog://connect?port=AUTO')
$ErrorActionPreference = 'Stop'
$mutex = $null
$ownsMutex = $false
try {
    if ($LaunchUri -notmatch '^aigo-robodog://connect/?\?port=(COM[1-9][0-9]{0,3}|AUTO)(?:&service=(on)(?:&route=([A-Za-z0-9_-]{1,4096}))?)?$') { throw 'Invalid AIGO launch address.' }
    $robotPort = $Matches[1]
    $service = $Matches[2]
    $routePayload = $Matches[3]
    $configFile = Join-Path $PSScriptRoot 'aigo-helper.local.json'
    $bundleRoot = Split-Path -Parent $PSScriptRoot
    $runtimeRoot = if (Test-Path -LiteralPath (Join-Path $bundleRoot 'Install_All.cmd') -PathType Leaf) { $bundleRoot } else { $PSScriptRoot }
    $config = $null
    if (Test-Path -LiteralPath $configFile -PathType Leaf) {
        try { $config = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $config = $null }
    }
    # Repair missing/stale settings before starting, including after moving the ZIP folder.
    if ($null -eq $config -or $config.projectRoot -ne $PSScriptRoot -or -not $config.python -or -not $config.logDir -or -not (Test-Path -LiteralPath $config.python -PathType Leaf)) {
        $installer = Join-Path $PSScriptRoot 'AIGO_Install.ps1'
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'AIGO_Install.ps1 is missing. Extract ALL files from the ZIP into one folder.' }
        $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        & $psExe -NoProfile -ExecutionPolicy Bypass -File $installer -RuntimeRoot $runtimeRoot
        if ($LASTEXITCODE -ne 0) { throw 'AIGO setup failed. Run AIGO_Install.cmd to see the installation details.' }
        $config = Get-Content -LiteralPath $configFile -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    foreach ($name in @('robodog_abc_delivery.py', 'aigo_on_patrol.py', 'on_demo_original.py', 'pawcare_control.html')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name) -PathType Leaf)) {
            throw ('Missing file: ' + $name + '. Extract ALL files from the ZIP into one folder.')
        }
    }
    $mutex = [Threading.Mutex]::new($false, 'Local\JeongseonAigoBridgeLauncher')
    $ownsMutex = $mutex.WaitOne(0)
    if (-not $ownsMutex) { exit 0 }
    $baseUrl = 'http://127.0.0.1:8765'
    function Get-Bridge {
        try { return Invoke-RestMethod -Uri ($baseUrl + '/api/status') -TimeoutSec 2 } catch { return $null }
    }
    $bridgeStatus = Get-Bridge
    if ($null -ne $bridgeStatus -and $bridgeStatus.bridge -ne 'jeongseon-aigo-v1') {
        throw 'Port 8765 is used by an older server or another program. Close that server and retry.'
    }
    if ($null -eq $bridgeStatus) {
        New-Item -ItemType Directory -Path $config.logDir -Force | Out-Null
        $env:AIGO_NO_BROWSER = '1'
        $env:ROBODOG_PORT = if ($robotPort -eq 'AUTO') { 'None' } else { $robotPort }
        $env:PYTHONIOENCODING = 'utf-8'
        $backendFile = Join-Path $PSScriptRoot 'robodog_abc_delivery.py'
        $process = Start-Process -FilePath $config.python -ArgumentList @('"' + $backendFile + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $config.logDir 'bridge.stdout.log') -RedirectStandardError (Join-Path $config.logDir 'bridge.stderr.log') -PassThru
        $deadline = [DateTime]::UtcNow.AddSeconds(25)
        do {
            Start-Sleep -Milliseconds 400
            $bridgeStatus = Get-Bridge
            if ($null -ne $bridgeStatus) { break }
            if ($process.HasExited) { throw ('Bridge stopped. Check ' + (Join-Path $config.logDir 'bridge.stderr.log')) }
        } while ([DateTime]::UtcNow -lt $deadline)
        if ($null -eq $bridgeStatus -or $bridgeStatus.bridge -ne 'jeongseon-aigo-v1') { throw 'Bridge startup timed out. Check the bridge logs.' }
    }
    $targetUrl = if ($robotPort -eq 'AUTO') { $baseUrl + '/?' } else { $baseUrl + '/?connect=1&port=' + $robotPort }
    if ($service -eq 'on') { $targetUrl += '&service=on'; if ($routePayload) { $targetUrl += '&route=' + $routePayload } }
    Start-Process -FilePath $targetUrl
} catch {
    Write-Host ('AIGO startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, 'AIGO connection helper') | Out-Null
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
