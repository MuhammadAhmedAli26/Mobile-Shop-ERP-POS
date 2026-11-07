@echo off
title Mobile Shop ERP
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path . -Filter *.exe -Recurse | Unblock-File -ErrorAction SilentlyContinue"
if exist "Mobile_Shop_ERP.exe" (
    start "" "Mobile_Shop_ERP.exe"
) else if exist "MobileShopERP\MobileShopERP.exe" (
    start "" "MobileShopERP\MobileShopERP.exe"
) else (
    echo [ERROR] Mobile_Shop_ERP.exe not found in this folder.
    pause
)
exit
