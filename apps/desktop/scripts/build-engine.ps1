[CmdletBinding()]
param(
    [switch]$InstallMissing
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$appRoot = Join-Path $repoRoot "packages\core"
$python = Join-Path $appRoot ".venv\Scripts\python.exe"
$binaryRoot = Join-Path $repoRoot "apps\desktop\src-tauri\binaries"
$buildRoot = Join-Path $appRoot "build\engine"
$sourceRoot = Join-Path $appRoot "src"
$resourceRoot = Join-Path $sourceRoot "studyflow\resources"
$previousPyInstallerConfig = $env:PYINSTALLER_CONFIG_DIR

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}

$pyInstallerCheck = & $python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    if (-not $InstallMissing) {
        throw "PyInstaller is not installed in the project environment. Run pip install pyinstaller or use -InstallMissing."
    }
    & $python -m pip install 'pyinstaller>=6.10,<7'
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}

New-Item -ItemType Directory -Path $binaryRoot -Force | Out-Null
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "work"
$specRoot = Join-Path $buildRoot "spec"
New-Item -ItemType Directory -Path $distRoot,$workRoot,$specRoot -Force | Out-Null

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onefile",
    "--name", "studyflow-engine",
    "--distpath", $distRoot,
    "--workpath", $workRoot,
    "--specpath", $specRoot,
    "--paths", $sourceRoot,
    "--collect-submodules", "studyflow",
    "--hidden-import", "alembic.ddl.sqlite",
    "--hidden-import", "sqlalchemy.dialects.sqlite"
)

# Add the curated assets including Alembic's .py scripts, but never bytecode.
# Directory-wide --add-data would also copy source-tree caches into the sidecar.
$assets = Get-ChildItem -LiteralPath $resourceRoot -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.Extension -in @('.ini','.py','.mako','.md','.html','.css')
}
foreach ($asset in $assets) {
    if ($asset.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked resource is not allowed: $($asset.Name)" }
    $relative = $asset.FullName.Substring($resourceRoot.Length).TrimStart('\','/')
    $folder = [IO.Path]::GetDirectoryName($relative).Replace('\','/')
    $destination = if ($folder) { "studyflow/resources/$folder" } else { "studyflow/resources" }
    $arguments += @("--add-data", "$($asset.FullName);$destination")
}
$arguments += (Join-Path $appRoot "engine_entry.py")

try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildRoot "cache"
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
} finally {
    if ($null -eq $previousPyInstallerConfig) {
        Remove-Item Env:PYINSTALLER_CONFIG_DIR -ErrorAction SilentlyContinue
    } else {
        $env:PYINSTALLER_CONFIG_DIR = $previousPyInstallerConfig
    }
}

$built = Join-Path $distRoot "studyflow-engine.exe"
if (-not (Test-Path -LiteralPath $built)) { throw "PyInstaller did not create studyflow-engine.exe." }
Copy-Item -LiteralPath $built -Destination (Join-Path $binaryRoot "studyflow-engine.exe") -Force
Write-Output "StudyFlow Engine sidecar: $(Join-Path $binaryRoot 'studyflow-engine.exe')"
Write-Output "PyInstaller: $pyInstallerCheck"
