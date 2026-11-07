# 🛠️ MOBILE SHOP ERP — BUILD & PACKAGING GUIDE

This document describes how to compile the Windows standalone executable and setup installer from source.

---

## 1. Prerequisites
- **Operating System:** Windows 10 or Windows 11 (64-bit)
- **Python Version:** Python 3.11, 3.12, 3.13, or 3.14 (64-bit)
- **Required Build Tools:**
  - `PyInstaller` (`pip install pyinstaller`)
  - `Inno Setup 6` (Optional, only needed to generate `MobileShopERP-Setup-1.0.0.exe`)

---

## 2. 1-Click Automated Build
Open Command Prompt or PowerShell in the `mobile_edition` folder and run:
```cmd
BUILD.bat
```

### What `BUILD.bat` Does Automatically:
1. Verifies the local Python runtime environment.
2. Runs the full test verification suite (`test_search_fix_verification.py`).
3. Executes `clean_database.py` to ensure the bundled database is 100% clean with zero dummy records.
4. Invokes PyInstaller with `MobileShopERP.spec` to generate `dist\MobileShopERP\`.
5. Injects `portable.flag` and archives `release\MobileShopERP-1.0.0-portable.zip`.
6. Checks for Inno Setup compiler (`ISCC.exe`) and builds `release\MobileShopERP-Setup-1.0.0.exe`.
7. Computes cryptographic SHA-256 hashes for all artifacts in `release\SHA256SUMS.txt`.

---

## 3. Manual Build Commands

### Step 3.1: Install Dependencies
```cmd
pip install -r requirements.lock
pip install pyinstaller waitress
```

### Step 3.2: Compile Executable
```cmd
python -m PyInstaller --clean MobileShopERP.spec
```
The compiled application will be generated in `dist\MobileShopERP\`.

### Step 3.3: Create Portable ZIP
Create an empty file named `portable.flag` inside `dist\MobileShopERP\`, then compress the `dist\MobileShopERP\` directory into a `.zip` archive.

### Step 3.4: Build Inno Setup Installer (Optional)
If Inno Setup 6 is installed on your computer:
```cmd
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```
This produces `release\MobileShopERP-Setup-1.0.0.exe`.

---

## 4. Antivirus & Windows SmartScreen Notice
- **Unsigned Binary Warning:** Because this build does not include an expensive commercial code-signing certificate (EV Certificate), Windows Defender SmartScreen may display:  
  `"Windows protected your PC"` on the very first launch.
- **How to Run:** Click **"More info"** and then **"Run anyway"**.
- This is normal behavior for offline open-source and proprietary enterprise ERP software on Windows.
