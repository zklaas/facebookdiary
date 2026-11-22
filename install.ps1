# Install FacebookDiary on Windows (current user, no admin needed).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Creates .venv in this folder with PyQt6 and PyQt6-WebEngine (videos play in
# FacebookDiary's own window when it can decode them, otherwise in Windows' own
# player), writes a `facebookdiary` command into a per-user bin folder on PATH,
# and adds a Start-menu shortcut with the FacebookDiary icon.
# The index, settings and media cache go to %LOCALAPPDATA%\FacebookDiary.
param([string]$BinDir = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $BinDir) { $BinDir = Join-Path $env:LOCALAPPDATA 'Programs\FacebookDiary\bin' }

function Test-RealPython([string]$Exe) {
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    if ($Exe -match '\\WindowsApps\\') { return $false }      # Microsoft Store stub
    try {
        $out = & $Exe -c 'import sys, sqlite3; c = sqlite3.connect(":memory:"); c.execute("CREATE VIRTUAL TABLE t USING fts5(x)"); print(sys.version_info >= (3, 10))' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True')
    } catch { return $false }
}

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in @('-3.13', '-3.12', '-3')) {
            try {
                $exe = (& $py.Source $v -c 'import sys; print(sys.executable)' 2>$null)
                if ($exe -and (Test-RealPython $exe.Trim())) { return $exe.Trim() }
            } catch { }
        }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath -and (Test-RealPython $onPath.Source)) { return $onPath.Source }
    throw "No Python 3.10+ (with SQLite full-text search) found. Install one, then run this again:`n    winget install --id Python.Python.3.13 -e --scope user"
}

$python = Find-Python
Write-Host "Python: $python"
$venv = Join-Path $AppDir '.venv'
$vpy = Join-Path $venv 'Scripts\python.exe'
$vpyw = Join-Path $venv 'Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $vpy)) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create $venv" }
}
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet PyQt6
if ($LASTEXITCODE -ne 0) { throw "pip install PyQt6 failed" }
& $vpy -m pip install --quiet PyQt6-WebEngine
if ($LASTEXITCODE -ne 0) { Write-Host "NOTE: PyQt6-WebEngine didn't install; videos will open in Windows' own player." }

# `facebookdiary` command
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$shim = Join-Path $BinDir 'facebookdiary.cmd'
Set-Content -LiteralPath $shim -Encoding ASCII -Value "@`"$vpy`" `"$AppDir\facebookdiary.py`" %*"
Write-Host "Installed: $shim"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if (($userPath -split ';') -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $BinDir).TrimStart(';'), 'User')
    Write-Host "Added $BinDir to your PATH (open a new terminal to use it)."
}

# Start-menu shortcut (pythonw: no console window)
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'FacebookDiary.lnk'
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($startMenu)
$lnk.TargetPath = $vpyw
$lnk.Arguments = "`"$AppDir\facebookdiary.py`""
$lnk.WorkingDirectory = $AppDir
$lnk.IconLocation = (Join-Path $AppDir 'icons\facebookdiary.ico')
$lnk.Description = 'Browse your Facebook posts day by day, by topic or by words'
$lnk.Save()
Write-Host "Start menu: $startMenu"
Write-Host "Done. Run it with:  facebookdiary      (or from the Start menu)"
Write-Host "On first start it asks for the folder holding your Facebook export zip(s)."
