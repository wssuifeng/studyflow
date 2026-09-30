[CmdletBinding()]
param(
    [switch]$InstallMissing
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$appRoot = Join-Path $repoRoot "studyflow_app"
$python = Join-Path $appRoot ".venv\Scripts\python.exe"
$binaryRoot = Join-Path $repoRoot "desktop\src-tauri\binaries"
$buildRoot = Join-Path $appRoot "build\engine"

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
    "--paths", $appRoot,
    "--add-data", "$(Join-Path $appRoot 'alembic.ini');.",
    "--add-data", "$(Join-Path $appRoot 'migrations');migrations",
    "--hidden-import", "alembic.ddl.sqlite",
    "--hidden-import", "sqlalchemy.dialects.sqlite",
    (Join-Path $appRoot "engine_entry.py")
)

& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$built = Join-Path $distRoot "studyflow-engine.exe"
if (-not (Test-Path -LiteralPath $built)) { throw "PyInstaller did not create studyflow-engine.exe." }
Copy-Item -LiteralPath $built -Destination (Join-Path $binaryRoot "studyflow-engine.exe") -Force
Write-Output "StudyFlow Engine sidecar: $(Join-Path $binaryRoot 'studyflow-engine.exe')"
Write-Output "PyInstaller: $pyInstallerCheck"
