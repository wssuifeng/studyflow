[CmdletBinding()]
param(
    [ValidateSet('debug', 'release')][string]$Profile = 'release',
    [switch]$BuildOnly,
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$tauri = (Resolve-Path -LiteralPath (Join-Path $project 'apps/desktop/src-tauri')).Path
$skill = (Resolve-Path -LiteralPath (Join-Path $project 'skills/studyflow-agent')).Path

Push-Location -LiteralPath $project
try {
    $arguments = @('build', '--locked', '-p', 'studyflow-runtime', '--bins', '--message-format=json-render-diagnostics')
    if ($Profile -eq 'release') { $arguments += '--release' }
    $runtime = @{}
    & cargo @arguments | ForEach-Object {
        $event = $_ | ConvertFrom-Json
        if ($event.reason -eq 'compiler-message' -and $event.message.rendered) {
            Write-Host $event.message.rendered.TrimEnd()
        }
        if ($event.reason -eq 'compiler-artifact' -and $event.executable -and $event.target.name -in @('studyflow', 'studyflow-engine')) {
            $runtime[$event.target.name] = (Resolve-Path -LiteralPath $event.executable).Path
        }
    }
    if ($LASTEXITCODE -ne 0 -or $runtime.Count -ne 2) { throw 'Both Cargo executables must be built successfully.' }
} finally {
    Pop-Location
}

if ($BuildOnly) {
    if ($ManifestPath) { [IO.File]::WriteAllText([IO.Path]::GetFullPath($ManifestPath), ($runtime | ConvertTo-Json)) }
    Write-Host ('Native executables at ' + (Split-Path -Parent $runtime['studyflow']))
    return
}

function Get-ResourceSha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

$destination = Join-Path $tauri 'binaries'
$nonce = [guid]::NewGuid().ToString('N')
$staging = Join-Path $tauri ('.studyflow-binaries-next-' + $nonce)
$previous = Join-Path $tauri ('.studyflow-binaries-previous-' + $nonce)
$files = [ordered]@{}
New-Item -ItemType Directory -Path $staging | Out-Null

foreach ($name in @('studyflow', 'studyflow-engine')) {
    $source = $runtime[$name]
    $filename = Split-Path -Leaf $source
    Copy-Item -LiteralPath $source -Destination (Join-Path $staging $filename)
    $files[$filename] = Get-ResourceSha256 $source
}
Get-ChildItem -LiteralPath $skill -Recurse -File | Where-Object { $_.Extension -in @('.md', '.json', '.yaml', '.yml') } | Sort-Object FullName | ForEach-Object {
    if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked skill file: $($_.Name)" }
    $relative = 'studyflow-agent/' + $_.FullName.Substring($skill.Length + 1).Replace('\', '/')
    $copy = Join-Path $staging $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $copy) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $copy
    $files[$relative] = Get-ResourceSha256 $_.FullName
}
foreach ($entry in $files.GetEnumerator()) {
    $actual = Get-ResourceSha256 (Join-Path $staging $entry.Key)
    if ($actual -ne $entry.Value) { throw "Resource verification failed: $($entry.Key)" }
}

# Both directory moves are restricted to children of the resolved Tauri folder.
foreach ($path in @($destination, $staging, $previous)) {
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($path))) -ne $tauri) { throw 'Invalid resource directory' }
    if (Test-Path -LiteralPath $path) {
        $item = Get-Item -LiteralPath $path -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked resource directory: $path" }
        if ((Split-Path -Parent $item.FullName) -ne $tauri) { throw 'Invalid resolved resource directory' }
    }
}
if (Test-Path -LiteralPath $destination) { [IO.Directory]::Move($destination, $previous) }
try {
    [IO.Directory]::Move($staging, $destination)
} catch {
    if ((Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $destination)) {
        [IO.Directory]::Move($previous, $destination)
    }
    throw
}

$manifest = [ordered]@{ format = 1; profile = $Profile; resource_root = $destination; cargo_executables = $runtime; files = $files }
if (Test-Path -LiteralPath $previous) { $manifest.previous_resource_root = $previous }
if (-not $ManifestPath) { $ManifestPath = Join-Path $tauri 'target/studyflow-native-resources.json' }
$manifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $manifestFullPath) | Out-Null
[IO.File]::WriteAllText($manifestFullPath, ($manifest | ConvertTo-Json -Depth 5))
Write-Host "Native resources ($($files.Count) files): $manifestFullPath"
