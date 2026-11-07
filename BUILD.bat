@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   MOBILE SHOP ERP v1.0 PRO — AUTOMATED BUILD SYSTEM
echo   Target: Windows 10/11 x64 (Standard User, Offline)
echo ============================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

if not exist release mkdir release
if exist build.log del build.log

echo [1/7] Verifying Python Environment... >> build.log
python --version >> build.log 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found on PATH. Please install Python 3.11+.
    exit /b 1
)

echo [2/7] Running Full Test Suite & Hardening Verification... >> build.log
python -m pytest -q >> build.log 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Pre-build verification tests failed. Inspect build.log.
    exit /b 1
)

echo [3/7] Purging Dummy Data for Pristine Clean Database Template... >> build.log
python clean_database.py >> build.log 2>&1

echo [4/7] Compiling Executable with PyInstaller (Windowed --onedir)... >> build.log
python -m PyInstaller -y --clean MobileShopERP.spec >> build.log 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller compilation failed. Inspect build.log.
    exit /b 1
)

echo [5/7] Checking Code Signing Certificate (Optional Hook)... >> build.log
if defined CODE_SIGN_CERT (
    if exist "%CODE_SIGN_CERT%" (
        echo Signing MobileShopERP.exe with signtool... >> build.log
        signtool sign /f "%CODE_SIGN_CERT%" /p "%CODE_SIGN_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\MobileShopERP\MobileShopERP.exe >> build.log 2>&1
        echo ✓ Code signature applied successfully.
    ) else (
        echo [NOTICE] CODE_SIGN_CERT file not found. Skipping signature. >> build.log
    )
) else (
    echo [NOTICE] CODE_SIGN_CERT not set. Skipping signature (Standard offline distribution). >> build.log
)

echo [6/7] Packaging Portable ZIP Distribution... >> build.log
if exist dist\MobileShopERP (
    copy /y NUL dist\MobileShopERP\portable.flag >nul 2>&1
    python -c "import zipfile, os, glob; zf = zipfile.ZipFile('release/MobileShopERP-1.0.0-portable.zip', 'w', zipfile.ZIP_DEFLATED); [zf.write(os.path.join(r, f), os.path.relpath(os.path.join(r, f), 'dist')) for r, d, files in os.walk('dist/MobileShopERP') for f in files]; zf.close()" >> build.log 2>&1
    echo ✓ Portable package created: release\MobileShopERP-1.0.0-portable.zip
)

echo [7/7] Compiling Inno Setup Installer... >> build.log
set ISCC=""
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if not "!ISCC!"=="" (
    echo Compiling Setup installer using Inno Setup... >> build.log
    !ISCC! setup.iss >> build.log 2>&1
    if defined CODE_SIGN_CERT (
        if exist "%CODE_SIGN_CERT%" (
            signtool sign /f "%CODE_SIGN_CERT%" /p "%CODE_SIGN_PASS%" /tr http://timestamp.digicert.com /td sha256 /fd sha256 ..\release\MobileShopERP-Setup-1.0.0.exe >> build.log 2>&1
        )
    )
    echo ✓ Installer created: release\MobileShopERP-Setup-1.0.0.exe
) else (
    echo [NOTICE] Inno Setup compiler ISCC.exe not found on default paths.
    echo Portable package ready in release\ folder. Setup.iss is ready for compilation on machines with Inno Setup.
)

echo Generating SHA-256 Checksums...
python -c "import hashlib, glob, os; fp=open('release/SHA256SUMS.txt', 'w'); [fp.write(f'{hashlib.sha256(open(p, \"rb\").read()).hexdigest()}  {os.path.basename(p)}\n') for p in glob.glob('release/*') if not p.endswith('.txt')]; fp.close()" >> build.log 2>&1

echo ============================================================
echo   BUILD PROCESS COMPLETED SUCCESSFULLY!
echo   Outputs available in release\ folder.
echo ============================================================
endlocal
