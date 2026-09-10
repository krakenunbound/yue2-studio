[CmdletBinding()]
param([switch]$SkipStage)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location $root
try {
    if (-not $SkipStage) { & (Join-Path $PSScriptRoot 'stage-installer.ps1') }
    & (Join-Path $root 'build\installer\payload\python\standalone\python.exe') -B -c 'import fastapi, httpx, uvicorn, imageio_ffmpeg, venv, ensurepip; from pathlib import Path; assert Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file()'
    if ($LASTEXITCODE -ne 0) { throw 'Release payload is missing required Python or media support.' }
    & (Join-Path $PSScriptRoot 'audit-installer.ps1')
    & npm.cmd run tauri build -- --config src-tauri/tauri.installer.conf.json --bundles nsis
    if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }
    $package = Get-ChildItem -LiteralPath (Join-Path $root 'src-tauri\target\release\bundle\nsis') -Filter '*-setup.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $package) { throw 'The build did not produce a setup executable.' }
    $release = Join-Path $root 'release'
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    $destination = Join-Path $release $package.Name
    Copy-Item -LiteralPath $package.FullName -Destination $destination -Force
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    [IO.File]::WriteAllText("$destination.sha256", "$hash  $($package.Name)`n")
    Write-Host "Windows installer ready: $destination"
} finally { Pop-Location }
