#requires -Version 5.1
<#
.SYNOPSIS
    Construit l'executable Windows de SectionCAD via uv + PyInstaller (mode onedir).

.DESCRIPTION
    Script ADDITIF et reversible. Il :
      1. verifie que uv est installe ;
      2. materialise l'environnement de DEV/BUILD sous Python 3.12 (fige par
         .python-version), groupe « build » inclus (PyInstaller) ;
      3. (optionnel) lance les tests sous l'interpreteur fige ;
      4. construit l'exe a partir du .spec versionne (SectionCAD.spec).

    Il NE touche a AUCUN fichier de l'application et ne modifie pas
    requirements.txt. Resultat : dist\SectionCAD\SectionCAD.exe (onedir).

.PARAMETER SkipTests
    Ne pas lancer pytest avant le build.

.PARAMETER Clean
    Supprimer build\ et dist\ avant de reconstruire.

.EXAMPLE
    pwsh -File .\build_exe.ps1
    pwsh -File .\build_exe.ps1 -Clean -SkipTests
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Clean,
    [switch]$Installer   # compile aussi l'installeur per-user (Inno Setup) si ISCC.exe est present
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "== SectionCAD : build de l'executable Windows (uv + PyInstaller, onedir) ==" -ForegroundColor Cyan

# --- 1. Verifier uv -----------------------------------------------------------
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error @"
uv introuvable. Installez-le puis relancez ce script :
    winget install astral-sh.uv
ou :
    irm https://astral.sh/uv/install.ps1 | iex
"@
}
Write-Host ("uv detecte : " + (uv --version)) -ForegroundColor Green

# --- 2. Nettoyage optionnel ---------------------------------------------------
if ($Clean) {
    foreach ($d in @("build", "dist")) {
        if (Test-Path $d) {
            Write-Host "Nettoyage de $d\ ..." -ForegroundColor Yellow
            Remove-Item -Recurse -Force $d
        }
    }
}

# --- 3. Materialiser l'env (Python 3.12 fige par .python-version) -------------
# uv lit .python-version ; s'il manque l'interpreteur, uv le telecharge.
Write-Host "Synchronisation de l'environnement (groupe build : PyInstaller) ..." -ForegroundColor Cyan
uv sync --group build
if ($LASTEXITCODE -ne 0) { throw "uv sync a echoue (code $LASTEXITCODE)." }

# --- 4. Tests (optionnels) ----------------------------------------------------
if (-not $SkipTests) {
    Write-Host "Execution des tests (pytest) sous l'interpreteur fige ..." -ForegroundColor Cyan
    uv run pytest tests/
    if ($LASTEXITCODE -ne 0) {
        throw "Les tests ont echoue (code $LASTEXITCODE). Build interrompu. Utilisez -SkipTests pour ignorer."
    }
}

# --- 5. Build PyInstaller a partir du .spec versionne -------------------------
# On pilote par le .spec (reproductible), PAS par la longue ligne de flags.
# IMPORTANT : pyinstaller est lance DANS l'env du projet (uv run), jamais via
# `uvx`/`uv tool run` (env isole qui ne verrait pas numpy/scipy/sectionproperties).
Write-Host "Build PyInstaller a partir de SectionCAD.spec ..." -ForegroundColor Cyan
uv run --group build pyinstaller --noconfirm SectionCAD.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue (code $LASTEXITCODE)." }

$dist = Join-Path $PSScriptRoot "dist\SectionCAD"
$out = Join-Path $dist "SectionCAD.exe"
if (-not (Test-Path $out)) {
    Write-Warning "Build termine mais $out introuvable — verifiez la sortie ci-dessus."
    return
}
Write-Host "OK : executable genere -> $out" -ForegroundColor Green

# --- 6. ZIP PORTABLE : livrable AUTOPORTANT, SANS installation ni droits admin ---
# L'utilisateur extrait ce zip n'importe ou (Bureau, cle USB) et lance
# SectionCAD.exe. Aucune installation, aucune elevation, aucune ecriture systeme
# requise pour demarrer (onedir ne touche ni Program Files ni HKLM).
$zip = Join-Path $PSScriptRoot "dist\SectionCAD-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "Creation du ZIP portable -> $zip ..." -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $dist "*") -DestinationPath $zip -CompressionLevel Optimal
Write-Host "OK : ZIP portable (extraire-et-lancer, sans admin) -> $zip" -ForegroundColor Green

# --- 7. Installeur PER-USER optionnel (Inno Setup, sans droits admin) ---
if ($Installer) {
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $cand = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $cand) { $iscc = $cand }
    }
    if ($iscc) {
        Write-Host "Compilation de l'installeur per-user (installer.iss) ..." -ForegroundColor Cyan
        & $iscc "installer.iss"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OK : installeur per-user (sans admin) -> dist\SectionCAD-Setup-user.exe" -ForegroundColor Green
        } else { Write-Warning "ISCC a echoue (code $LASTEXITCODE)." }
    } else {
        Write-Warning "Inno Setup (ISCC.exe) introuvable : installeur ignore. Le ZIP portable suffit (l'installeur est OPTIONNEL)."
    }
}
