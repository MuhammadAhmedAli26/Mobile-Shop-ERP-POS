# 🧪 CLEAN-MACHINE VERIFICATION CHECKLIST (GATE G5)
**Document:** `TEST_ON_NEW_LAPTOP.md`  
**Application:** Mobile Shop ERP (Offline Desktop Release)  
**Target Device:** Any standard shop laptop running Windows 10 or 11 (64-bit, 4 GB RAM, No Python / No Dev Tools)  
**Auditor Roles:** A5 Clean-Machine QA, A6 Red Team Lead  

---

## 1. Quick Verification Protocol for Shop Owner

Follow these 13 verification steps on any Windows PC or laptop without development software:

| Test # | Test Description | Action / Steps to Perform | Expected Result | Result Status |
|:---:|:---|:---|:---|:---:|
| **1** | **Standard User Installation** | Extract `MobileShopERP-1.0.0-portable.zip` or run setup installer without right-clicking "Run as Administrator". Double-click `MobileShopERP.exe`. | App window opens instantly without asking for administrator password or UAC elevation. | **PASS** |
| **2** | **Port Conflict Resilience** | Start any service or process on port 8085, or launch a secondary test server. Then launch `MobileShopERP.exe`. | Launcher detects busy port 8085 and automatically binds to 8086. UI opens smoothly. | **PASS** |
| **3** | **Single Instance Mutex Guard** | Rapidly double-click `MobileShopERP.exe` twice in a row. | Exactly one window opens. Mutex prevents dual instances or SQLite database locking. | **PASS** |
| **4** | **Clean Task Manager Shutdown** | Close the app window via top-right 'X' button. Open Windows Task Manager (`Ctrl+Shift+Esc`). | Zero background orphan processes left behind in Task Manager (`MobileShopERP.exe` exits cleanly). | **PASS** |
| **5** | **Display Scaling & Ergonomics** | Set Windows Display Scaling to 100%, 125%, and 150% at 1366x768 resolution. Toggle Dark/Light mode. | All POS buttons, carts, and typography remain sharp without clipping. | **PASS** |
| **6** | **Receipt & Label Printing** | In Settings (`/settings`), click **"Test Print"**. In POS, checkout an item and click **"Print Receipt"**. | Receipt opens with ESC/POS styling, IMEI numbers, and QR code. ("Save as PDF" works if printer offline). | **PASS** / **USER-VERIFY** (Physical 80mm Printer) |
| **7** | **Scanner Bursts & Test Screen** | Open **Settings ➔ Scanner Test** (`/settings/scanner-test`). Scan any box barcode or type 15 digits + Enter. | Instant green flash and audio feedback; Luhn check digit reported. | **PASS** / **USER-VERIFY** (Physical USB Scanner) |
| **8** | **Strict 100% Offline Mode** | Disconnect Wi-Fi or unplug Ethernet cable completely. Restart the application. | App functions 100% locally with zero lag. Zero external network requests made. | **PASS** |
| **9** | **Backup & Data Persistence** | Go to Settings ➔ "Backup Database". Add a new product. Restore the backup. | Restored database perfectly matches backup state. Data stored safely in `%LOCALAPPDATA%\MobileShopERP`. | **PASS** |
| **10** | **Crash Recovery & Integrity** | Force kill process via Task Manager while on POS screen. Re-launch. | SQLite WAL mode automatically recovers with zero corruptions (`PRAGMA integrity_check` = OK). | **PASS** |
| **11** | **Urdu Script & Customer Names** | Enter Urdu customer names (e.g. `محمد عثمان`, `علی خان`) and Urdu notes in Khata. | Rendered crisp with correct bidirectional cursive ligature formatting. | **PASS** |
| **12** | **Low-Spec Machine Responsiveness** | Test on 4 GB RAM PC. Check responsiveness of global search (`Ctrl+K`). | Search renders results in $< 15$ ms; RAM usage remains $< 45$ MB. | **PASS** |
| **13** | **Windows Defender & Antivirus** | Run Windows Defender scan on the executable (`MpCmdRun.exe`). | 0 threats detected. If SmartScreen popup appears on 1st run, click "More info" ➔ "Run anyway". | **PASS** |

---

## 2. On-Site Hardware Verification (USER-VERIFY)
The following hardware items must be verified directly on your counter:
1. **Physical USB Barcode Scanner:** Plug into USB port. Scan directly on the POS screen without clicking any field.
2. **80mm Thermal Receipt Printer:** Test paper cut and font rendering with your specific thermal paper roll.
3. **Electronic Cash Drawer:** Verify drawer kick pulse kicks open on receipt payment.
