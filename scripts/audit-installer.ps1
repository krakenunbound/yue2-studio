[CmdletBinding()]
param([string]$Payload = (Join-Path $PSScriptRoot '..\build\installer\payload'))
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$payloadPath = (Resolve-Path -LiteralPath $Payload).Path
$files = @(Get-ChildItem -LiteralPath $payloadPath -File -Recurse)
$privateStrings = [Collections.Generic.List[string]]::new()
function Collect-Keys($value) {
    if ($value -is [string]) {
        if ($value -match '^AIza[0-9A-Za-z_-]{20,}$') { $privateStrings.Add($value) }
    } elseif ($value -is [Collections.IDictionary]) {
        foreach ($entry in $value.Values) { Collect-Keys $entry }
    } elseif ($value -is [Collections.IEnumerable]) {
        foreach ($entry in $value) { Collect-Keys $entry }
    }
}
$vault = Join-Path $root 'outputs\settings\api-keys.json'
if (Test-Path -LiteralPath $vault) {
    Collect-Keys (Get-Content -LiteralPath $vault -Raw | ConvertFrom-Json -AsHashtable)
}
foreach ($file in $files) {
    $relative = [IO.Path]::GetRelativePath($payloadPath, $file.FullName)
    if ($relative -match '(^|[\\/])(outputs|api-keys\.json|\.env)([\\/]|$)' -or $file.Name -match '^(credentials|secrets?)\.(json|txt|ya?ml|toml|ini)$') {
        throw "Private file rejected from installer: $relative"
    }
    # Scan exact local key values in every payload file, including binaries.
    # Values are never written to the console or the release audit report.
    if ($privateStrings.Count) {
        $content = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($file.FullName))
        foreach ($keyValue in $privateStrings) {
            if ($content.Contains($keyValue)) { throw "Private credential found in installer payload: $relative" }
        }
    }
}
$privateStrings.Clear()
$total = ($files | Measure-Object -Property Length -Sum).Sum
Write-Host "Installer privacy audit passed: $($files.Count) files, $([math]::Round($total / 1MB, 1)) MB; no key vault, user outputs, or local Gemini key."
