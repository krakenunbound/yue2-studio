<#
.SYNOPSIS
Builds the self-contained payload consumed by the Windows installer.

.DESCRIPTION
The installed application does not depend on a system Python installation.  This
script copies a complete CPython distribution into python\standalone, then installs
only the small web-sidecar dependencies there.  GPU/feature runtimes and every
model remain opt-in downloads managed from the Models page after installation.

The payload deliberately contains no outputs, library media, logs, API keys,
model weights, or private Python runtimes.

.EXAMPLE
pwsh -ExecutionPolicy Bypass -File scripts\stage-installer.ps1
#>
[CmdletBinding()]
param(
    [string]$StageRoot = (Join-Path $PSScriptRoot '..\build\installer\payload'),
    [string]$PythonHome,
    [switch]$SkipBackendDependencies
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Resolve-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Require-Path([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description is missing: $Path"
    }
}

function Copy-Tree([string]$Source, [string]$Destination, [string[]]$ExcludedDirectories = @()) {
    Require-Path $Source 'Source directory'
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    # Robocopy return values below 8 are success, including an empty tree.
    $Arguments = @($Source, $Destination, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:2', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($ExcludedDirectories.Count) { $Arguments += '/XD'; $Arguments += $ExcludedDirectories }
    & robocopy @Arguments | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Failed to copy $Source to $Destination (robocopy exit $LASTEXITCODE)." }
}

$ProjectRoot = Resolve-FullPath (Join-Path $PSScriptRoot '..')
$StageRoot = Resolve-FullPath $StageRoot
$InstallerRoot = Resolve-FullPath (Join-Path $ProjectRoot 'build\installer')
$InstallerRootPrefix = $InstallerRoot.TrimEnd('\') + '\'

if (-not $StageRoot.StartsWith($InstallerRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "StageRoot must be inside $InstallerRoot so the staging cleanup cannot touch application files."
}

if (-not $PythonHome) {
    $CurrentVenvConfig = Join-Path $ProjectRoot 'python\venv\pyvenv.cfg'
    if (Test-Path -LiteralPath $CurrentVenvConfig) {
        $HomeLine = Get-Content -LiteralPath $CurrentVenvConfig | Where-Object { $_ -match '^home\s*=\s*' } | Select-Object -First 1
        if ($HomeLine) { $PythonHome = ($HomeLine -replace '^home\s*=\s*', '').Trim() }
    }
}
if (-not $PythonHome) { throw 'Specify -PythonHome with a full CPython 3.11 installation directory.' }
$PythonHome = Resolve-FullPath $PythonHome
Require-Path (Join-Path $PythonHome 'python.exe') 'CPython executable'
Require-Path (Join-Path $PythonHome 'Lib\venv') 'CPython venv module'
Require-Path (Join-Path $PythonHome 'Lib\ensurepip') 'CPython ensurepip module'

if (Test-Path -LiteralPath $StageRoot) {
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $StageRoot | Out-Null

$PythonStage = Join-Path $StageRoot 'python'
New-Item -ItemType Directory -Force -Path $PythonStage | Out-Null
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'python') -File -Filter '*.py' |
    Copy-Item -Destination $PythonStage -Force
foreach ($File in @('requirements.txt', 'engine-requirements.txt', 'model_catalog.json', 'woosh_downloads.json')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "python\$File") -Destination $PythonStage -Force
}
foreach ($Directory in @('caption_library', 'cover_art', 'video_studio')) {
    Copy-Tree (Join-Path $ProjectRoot "python\$Directory") (Join-Path $PythonStage $Directory)
}

# Build a clean, relocatable base CPython.  Copying python\venv would leave the
# staged app coupled to the developer's Python home.  Copying an entire Python
# installation would also accidentally ship its unrelated site packages.  The
# selected standard-library tree has ensurepip and venv, which lets the Models
# page create its own private runtimes on a clean Windows computer.
$StandalonePython = Join-Path $PythonStage 'standalone'
New-Item -ItemType Directory -Force -Path $StandalonePython | Out-Null
Get-ChildItem -LiteralPath $PythonHome -File | Copy-Item -Destination $StandalonePython -Force
Copy-Item -LiteralPath (Join-Path $PythonHome 'LICENSE.txt') -Destination (Join-Path $StandalonePython 'PYTHON_LICENSE.txt') -Force
foreach ($Directory in @('DLLs', 'tcl')) {
    $Source = Join-Path $PythonHome $Directory
    if (Test-Path -LiteralPath $Source) { Copy-Tree $Source (Join-Path $StandalonePython $Directory) }
}
Copy-Tree (Join-Path $PythonHome 'Lib') (Join-Path $StandalonePython 'Lib') @('site-packages', '__pycache__', 'test', 'tests', 'idle_test')
$SidecarPython = Join-Path $StandalonePython 'python.exe'
& $SidecarPython -m ensurepip --upgrade | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bundled Python could not bootstrap pip.' }
if (-not $SkipBackendDependencies) {
    & $SidecarPython -m pip install --disable-pip-version-check --no-input --no-cache-dir --upgrade pip | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not update bundled pip.' }
    & $SidecarPython -m pip install --disable-pip-version-check --no-input --no-cache-dir --no-compile -r (Join-Path $PythonStage 'requirements.txt') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the bundled sidecar dependencies.' }

    # WhisperX invokes `ffmpeg` by name.  imageio-ffmpeg already supplies a
    # Windows binary, so expose that exact bundled binary in tools without
    # removing its original package copy (imageio-ffmpeg still uses that).
    $FfmpegSource = (& $SidecarPython -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())').Trim()
    Require-Path $FfmpegSource 'Bundled imageio-ffmpeg executable'
    $ToolsDirectory = Join-Path $StageRoot 'tools'
    New-Item -ItemType Directory -Force -Path $ToolsDirectory | Out-Null
    Copy-Item -LiteralPath $FfmpegSource -Destination (Join-Path $ToolsDirectory 'ffmpeg.exe') -Force
}

foreach ($File in @('README.md', 'USER_GUIDE.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'APP_THIRD_PARTY_NOTICES.md')) {
    $Source = Join-Path $ProjectRoot $File
    if (Test-Path -LiteralPath $Source) { Copy-Item -LiteralPath $Source -Destination $StageRoot -Force }
}

# Verify the sidecar interpreter from its final path.  This catches an incomplete
# standard library and proves it can make model_manager's private venvs.
& $SidecarPython -c 'import ensurepip, venv; print("Bundled Python ready")'
if ($LASTEXITCODE -ne 0) { throw 'Staged Python cannot import ensurepip and venv.' }
if (-not $SkipBackendDependencies) {
    & $SidecarPython -c 'import fastapi, httpx, uvicorn; print("Sidecar dependencies ready")'
    if ($LASTEXITCODE -ne 0) { throw 'Staged backend dependencies cannot be imported.' }
}

Write-Host "Installer payload staged at $StageRoot"
