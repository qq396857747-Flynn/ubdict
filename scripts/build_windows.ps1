param(
    [string]$TesseractRoot = $env:TESSERACT_HOME,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $TesseractRoot) {
    $TesseractRoot = Join-Path $env:ProgramFiles "Tesseract-OCR"
}
$TesseractRoot = (Resolve-Path $TesseractRoot).Path
$TesseractExe = Join-Path $TesseractRoot "tesseract.exe"
$EnglishData = Join-Path $TesseractRoot "tessdata\eng.traineddata"
if (-not (Test-Path $TesseractExe) -or -not (Test-Path $EnglishData)) {
    throw "Tesseract OCR with tessdata\eng.traineddata is required: $TesseractRoot"
}

$InnoCompiler = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source
if (-not $InnoCompiler) {
    $InnoCompiler = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $InnoCompiler)) {
    throw "Inno Setup 6 is required. Install it or add ISCC.exe to PATH."
}

Push-Location $ProjectRoot
try {
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
    & $Python -m pip install .
    if ($LASTEXITCODE -ne 0) { throw "Failed to install UbDict dependencies." }
    & $Python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Failed to install PyInstaller." }

    $Payload = Join-Path $ProjectRoot "dist\UbDict"
    if (Test-Path $Payload) {
        Remove-Item -LiteralPath $Payload -Recurse -Force
    }

    $PyInstallerArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "UbDict", "--paths", "src",
        "--add-data", "config/ecdict.db;config",
        "--add-data", "$TesseractRoot;tools/tesseract",
        "--collect-all", "PyQt6",
        "--collect-all", "pymupdf",
        "--collect-all", "selectolax",
        "--collect-all", "pytesseract",
        "--hidden-import", "PyQt6.QtMultimedia",
        "scripts/windows_entry.py"
    )
    & $Python @PyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $Version = (& $Python -c "from ubdict import __version__; print(__version__)").Trim()
    & $InnoCompiler "/DAppVersion=$Version" "/DPayloadDir=$Payload" `
        (Join-Path $ProjectRoot "scripts\windows\ubdict.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

    Write-Host "Windows installer created: $(Join-Path $ProjectRoot "dist\UbDictSetup-$Version-x64.exe")"
}
finally {
    Pop-Location
}
