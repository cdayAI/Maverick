<#
  Maverick desktop bootstrap (Windows).

  One-line install (PowerShell):
    irm https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/desktop/install.ps1 | iex

  Zero prerequisites. It installs Python 3.12 and Git if they are
  missing (via winget), pulls Maverick, installs the agent + setup
  wizard into an isolated pipx environment, and launches the wizard
  (`maverick init`).

  Pin or override the source first:
    $env:MAVERICK_REPO = "owner/maverick"; $env:MAVERICK_REF = "main"
    irm https://raw.githubusercontent.com/.../install.ps1 | iex
#>

$ErrorActionPreference = 'Stop'

$Repo   = if ($env:MAVERICK_REPO) { $env:MAVERICK_REPO } else { 'cdayAI/Maverick' }
$Ref    = if ($env:MAVERICK_REF)  { $env:MAVERICK_REF }  else { 'main' }
$SrcDir = Join-Path $env:LOCALAPPDATA 'Maverick\src'

# How to call the resolved Python: $PyExe + $PyPre (e.g. 'py' + '-3').
$script:PyExe = $null
$script:PyPre = @()

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Die($m) { throw "Maverick install failed: $m" }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Py { & $script:PyExe @($script:PyPre + $args) }

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Ensure-Winget {
  if (Have winget) { return }
  Die @"
winget is not available (older Windows 10). Install these by hand, then re-run:
  Python 3.12 : https://www.python.org/downloads/  (tick 'Add python.exe to PATH')
  Git         : https://git-scm.com/download/win
"@
}

function Winget-Install($id, $override) {
  Write-Step "Installing $id ..."
  # An $override replaces winget's default installer args entirely, so it
  # must carry its own quiet flag. Used to force Python onto PATH.
  if ($override) {
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --override $override
  } else {
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
  }
  Refresh-Path
}

# Validate one interpreter: run it and confirm it reports >= 3.10. On
# success, record how to invoke it ($script:PyExe / $script:PyPre).
function Test-PyCandidate($exe, $pre) {
  try {
    $v = & $exe @($pre + @('-c', 'import sys;print("%d.%d"%sys.version_info[:2])')) 2>$null
    if ($v -match '^(\d+)\.(\d+)$' -and
        ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10))) {
      $script:PyExe = $exe; $script:PyPre = $pre
      return $true
    }
  } catch { }
  return $false
}

# Find a usable Python >= 3.10. Checks PATH first, then well-known
# install dirs: winget runs the python.org installer, which does NOT add
# Python to PATH unless PrependPath is set, so a fresh install is often
# only reachable on disk.
function Resolve-Python {
  if ((Have py)     -and (Test-PyCandidate 'py'     @('-3'))) { return $true }
  if ((Have python) -and (Test-PyCandidate 'python' @()))     { return $true }

  $globs = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
    (Join-Path $env:ProgramFiles 'Python3*\python.exe'),
    (Join-Path $env:ProgramFiles 'Python\Python3*\python.exe'),
    'C:\Python3*\python.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher\py.exe'),
    'C:\Windows\py.exe'
  )
  if (${env:ProgramFiles(x86)}) {
    $globs += (Join-Path ${env:ProgramFiles(x86)} 'Python3*\python.exe')
  }
  foreach ($g in $globs) {
    $hits = Get-ChildItem -Path $g -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    foreach ($hit in $hits) {
      $pre = if ($hit.Name -ieq 'py.exe') { @('-3') } else { @() }
      if (Test-PyCandidate $hit.FullName $pre) { return $true }
    }
  }
  return $false
}

Write-Host ""
Write-Host "Maverick desktop installer (Windows)" -ForegroundColor Green
Write-Host ""

# 1. Python 3.10+
if (-not (Resolve-Python)) {
  Ensure-Winget
  # PrependPath puts python.org's install on PATH for future sessions;
  # Resolve-Python also locates it on disk for the current one.
  Winget-Install 'Python.Python.3.12' '/quiet PrependPath=1 InstallLauncherAllUsers=0'
  if (-not (Resolve-Python)) {
    Die "Python installed but couldn't be located. Open a NEW PowerShell window and re-run the command."
  }
}
Write-Step ("Using Python " + (Py -c 'import sys;print(sys.version.split()[0])'))

# 2. Git
if (-not (Have git)) { Ensure-Winget; Winget-Install 'Git.Git' }
if (-not (Have git)) { Die "Git installed, but it isn't on PATH. Open a NEW PowerShell window and re-run." }

# 3. pipx
Write-Step "Ensuring pipx ..."
Py -m pip install --user --upgrade pip pipx | Out-Null
Py -m pipx ensurepath | Out-Null

# 4. Source
if (Test-Path (Join-Path $SrcDir '.git')) {
  Write-Step "Updating Maverick source ($Ref) ..."
  git -C $SrcDir remote set-url origin "https://github.com/$Repo"
  git -C $SrcDir fetch --depth 1 origin $Ref
  git -C $SrcDir checkout -B $Ref FETCH_HEAD | Out-Null
} else {
  Write-Step "Downloading Maverick ($Repo@$Ref) ..."
  New-Item -ItemType Directory -Force -Path (Split-Path $SrcDir) | Out-Null
  git clone --depth 1 --branch $Ref "https://github.com/$Repo" $SrcDir
}

# 5. Install agent + wizard into one pipx venv. We inject the wizard
#    from source (apps/installer-cli) rather than the [installer] extra
#    because maverick-installer is not published to PyPI.
Write-Step "Installing the agent + setup wizard (this can take a minute) ..."
Py -m pipx install --force (Join-Path $SrcDir 'packages\maverick-core')
Py -m pipx inject --force maverick-agent (Join-Path $SrcDir 'apps\installer-cli')

# 6. Locate the maverick shim and launch the wizard.
$binDir = $null
try { $binDir = (Py -m pipx environment --value PIPX_BIN_DIR).Trim() } catch { }
if (-not $binDir) { $binDir = Join-Path $env:USERPROFILE '.local\bin' }
$env:Path = "$binDir;$env:Path"
Refresh-Path

Write-Host ""
Write-Host "Maverick installed." -ForegroundColor Green
Write-Host "Launching the setup wizard..." -ForegroundColor Green
Write-Host ""
if (Have maverick) {
  maverick init
} else {
  Write-Warn "Installed, but 'maverick' isn't on this window's PATH yet."
  Write-Host "Open a NEW PowerShell window and run:  maverick init"
}
