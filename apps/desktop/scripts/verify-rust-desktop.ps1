[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('BuildTree', 'Installed')][string]$Mode,
    [Parameter(Mandatory)][string]$DesktopPath,
    [Parameter(Mandatory)][string]$WorkspacePath,
    [string]$ManifestPath,
    [string]$EvidencePath,
    [string]$StaleEnginePath,
    [string]$ProductCode,
    [switch]$ExerciseBusinessFlows
)

$ErrorActionPreference = 'Stop'
$desktop = (Resolve-Path -LiteralPath $DesktopPath).Path
$workspace = (Resolve-Path -LiteralPath $WorkspacePath).Path
if (-not $EvidencePath) {
    $EvidencePath = Join-Path $PSScriptRoot ('../test-results/native-rust-' + [guid]::NewGuid().ToString('N'))
}
$evidence = [IO.Path]::GetFullPath($EvidencePath)
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$arguments = @('--mode', $Mode, '--desktop', $desktop, '--workspace', $workspace, '--evidence', $evidence)
if ($Mode -eq 'BuildTree') {
    if (-not $ManifestPath) { $ManifestPath = Join-Path $PSScriptRoot '../src-tauri/target/studyflow-native-resources.json' }
} elseif (-not $ProductCode) {
    throw 'Installed mode requires the ProductCode from the tested MSI.'
}
if ($ManifestPath) { $arguments += @('--manifest', (Resolve-Path -LiteralPath $ManifestPath).Path) }
if ($ProductCode) { $arguments += @('--product-code', $ProductCode) }
if ($ExerciseBusinessFlows) { $arguments += '--exercise-business-flows' }
if ($StaleEnginePath) { $arguments += @('--stale-engine', (Resolve-Path -LiteralPath $StaleEnginePath).Path) }

& python -X utf8 (Join-Path $PSScriptRoot 'verify-rust-desktop.py') @arguments
exit $LASTEXITCODE
