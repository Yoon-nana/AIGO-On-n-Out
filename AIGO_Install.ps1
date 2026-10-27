param([string]$RuntimeRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
try {
    foreach ($name in @('AIGO_Launch.ps1', 'requirements-bridge.txt', 'robodog_abc_delivery.py', 'aigo_on_patrol.py', 'on_demo_original.py', 'pawcare_control.html')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name) -PathType Leaf)) {
            throw ('Missing file: ' + $name + '. Extract ALL files from the ZIP into one folder first.')
        }
    }
    $runtimeRootPath = [IO.Path]::GetFullPath($RuntimeRoot)
    $pythonExe = Join-Path $runtimeRootPath '.venv\Scripts\python.exe'
    $versionCheck = 'import sys; sys.exit(0 if (3, 10) <= sys.version_info < (3, 15) else 1)'
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $pythonCommand = $null
        $pythonArgs = @()
        # Prefer the documented version, then try other installed Python 3 versions.
        $candidates = @(
            @{ command = 'py'; arguments = @('-3.14') },
            @{ command = 'py'; arguments = @('-3.13') },
            @{ command = 'py'; arguments = @('-3.12') },
            @{ command = 'py'; arguments = @('-3.11') },
            @{ command = 'py'; arguments = @('-3.10') },
            @{ command = 'python'; arguments = @() }
        )
        foreach ($candidate in $candidates) {
            $command = Get-Command $candidate.command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -eq $command) { continue }
            $candidateArgs = @($candidate.arguments)
            try { & $command.Source @candidateArgs -c $versionCheck 2>$null } catch { continue }
            if ($LASTEXITCODE -eq 0) {
                $pythonCommand = $command.Source
                $pythonArgs = $candidateArgs
                break
            }
        }
        if ($null -eq $pythonCommand) { throw 'Install Python 3.10-3.14 from https://www.python.org/downloads/windows/ (include the py launcher), then retry.' }
        & $pythonCommand @pythonArgs -m venv (Join-Path $runtimeRootPath '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Check folder permissions and your Python installation.' }
    }
    & $pythonExe -c $versionCheck
    if ($LASTEXITCODE -ne 0) { throw 'The .venv requires Python 3.10-3.14. Extract this ZIP into a fresh folder and rerun AIGO_Install.cmd.' }
    & $pythonExe -m pip install -r (Join-Path $PSScriptRoot 'requirements-bridge.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & $pythonExe -c 'import kocoafab_robodog, serial; from pyjuni.robodog import RoboDog'
    if ($LASTEXITCODE -ne 0) { throw 'Robot libraries could not be loaded. Check the installation output above.' }
    $logDir = Join-Path $runtimeRootPath 'work\aigo-runtime'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $config = @{ python = $pythonExe; logDir = $logDir; projectRoot = $PSScriptRoot }
    $config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'aigo-helper.local.json') -Encoding UTF8
    $protocolKey = 'HKCU:\Software\Classes\aigo-robodog'
    New-Item -Path $protocolKey -Force | Out-Null
    Set-Item -LiteralPath $protocolKey -Value 'URL:Jeongseon AIGO Robot Helper'
    New-ItemProperty -LiteralPath $protocolKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    $commandKey = Join-Path $protocolKey 'shell\open\command'
    New-Item -Path $commandKey -Force | Out-Null
    $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $launcher = Join-Path $PSScriptRoot 'AIGO_Launch.ps1'
    $command = '"' + $psExe + '" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '" -LaunchUri "%1"'
    Set-Item -LiteralPath $commandKey -Value $command
    Write-Host 'AIGO helper installed. Open pawcare_control.html and click the robot connect button.' -ForegroundColor Green
} catch {
    Write-Host ('AIGO installation failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
