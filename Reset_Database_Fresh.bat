@echo off
chcp 65001 >nul
color 0C
title Clean Fresh Database Reset - Mobile Shop ERP
cls
echo ===============================================================================
echo        🧹 MOBILE SHOP ERP - FRESH PRODUCTION DATABASE RESET TOOL
echo ===============================================================================
echo.
echo  Khabardaar! (WARNING):
echo  Ye script testing ka tamam dummy data mukammal tor par delete kar de gi:
echo    • Tamam Invoices aur Sales History
echo    • Tamam Stock / Phone Units / Barcodes / IMEIs
echo    • Tamam EasyPaisa / JazzCash / Quick Services Transactions
echo    • Tamam Repairing aur Software Job Tickets
echo    • Tamam Udhaar Khata (Customer Ledger) aur Shop Expenses
echo.
echo  Mehfooz cheezein (Preserved Data):
echo    ✓ Dukan ki Settings, Categories aur Brands lookups
echo    ✓ Master Admin (admin / admin123) aur Counter Staff (staff / staff123)
echo    ✓ Admin Override PIN: 9999
echo.
echo  [Pehle se maujood database ka automatic backup banya jaye ga]
echo ===============================================================================
echo.
set /p CONFIRM="Aap waqai tamam data saaf karna chahte hain? Type 'RESET' to proceed: "

if /i not "%CONFIRM%"=="RESET" (
    echo.
    echo [CANCELLED] Reset operation cancel kar dia gaya hai. Koi data delete nahi hua.
    echo.
    pause
    exit /b 0
)

echo.
echo [1/2] Creating Safety Backup of mobile_erp.db...
if exist "mobile_erp.db" (
    copy "mobile_erp.db" "mobile_erp.db.pre_reset_backup" /Y >nul
    echo       ✓ Backup saved as: mobile_erp.db.pre_reset_backup
)

echo.
echo [2/2] Purging dummy data and initializing pristine state...
if exist "clean_database.py" (
    python clean_database.py
) else (
    echo [ERROR] clean_database.py nahi mila!
)

echo.
echo ===============================================================================
echo  MUBARAK HO! Database bilkul clean, fresh aur ready-for-launch hai.
echo  Ab aap fresh stock add karein aur real business shuru karein.
echo ===============================================================================
echo.
pause
