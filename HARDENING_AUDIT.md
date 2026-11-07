# HARDENING AUDIT REPORT (GATE G1)
**Project:** Mobile & Accessories Shop ERP + POS (Offline, 127.0.0.1, Rs./PKR, Local Server)  
**Date:** October 12, 2026  
**Auditor Team:** A0-A7 Engineering Release Team  
**Baseline Database Backup:** `mobile_edition/backups/pre-hardening-baseline.db`  
**Baseline Codebase Snapshot:** `mobile_edition_pre_hardening_baseline`  

---

## 1. Real Stack & Executable Packaging Configuration

| Component | Current State | Audit Finding / Requirement |
| :--- | :--- | :--- |
| **Python Runtime** | Python 3.14.0 (64-bit Windows) | Waitress 3.0.2 WSGI + Bottle 0.12.25 + Beaker 1.12.1 |
| **Database Engine** | SQLite 3 in WAL mode | Single local DB (`mobile_erp.db`), WAL enabled, PRAGMA synchronous=NORMAL, cache_size=-64000, mmap_size=134217728 |
| **Packaging Architecture** | PyInstaller `--onedir` (`MobileShopERP.spec`) | Windowed mode (`console=False`), outputs to `dist\MobileShopERP` |
| **Installer** | Inno Setup 6 (`setup.iss`) | `PrivilegesRequired=lowest` (Per-user install into `%localappdata%\Programs\MobileShopERP`) |
| **Code Signing** | Unsigned | No signtool digital signature currently attached. Triggers SmartScreen warning unless unblocked. |
| **Manifest / Privileges** | `asInvoker` | Correctly avoids automatic Windows UAC elevation requests. |
| **Host Binding** | `0.0.0.0` (in `config.py`) | **CRITICAL RISK:** Binding to `0.0.0.0` causes Windows Firewall dialog. Must bind strictly to `127.0.0.1`. |
| **Data Storage Location** | `%localappdata%\MobileShopERP` | Fallback to `./` if portable flag present. Preserved on uninstallation. |

---

## 2. Item Creation & Mutation Audit (Add-Item Failures)

### 2.1 Accessory & Item Add Failure Reproduction
* **Reproduction Scenario (UI):**  
  User navigates to `/inventory`, opens "+ Add New Model", chooses `Item Type: ACCESSORY`, Brand: `Samsung`, Model Name: `45W Fast Charger`, and submits to `/inventory/create-product`.
* **Request Payload:** `brand=Samsung&name=45W+Fast+Charger&category=Charger&item_type=ACCESSORY`
* **Response:** HTTP 302 Redirect to `/inventory/matrix-create?product_id=187`
* **Failure Analysis:**
  1. `/inventory/matrix-create` filters products via `SELECT * FROM products WHERE item_type = 'PHONE'`. The newly created accessory **does not appear in the model dropdown**.
  2. The screen forces the user into phone-specific RAM/Storage combinations (`4GB/64GB`, etc.) and colors. There is **no input field for accessory stock quantity, SKU, or barcode**.
  3. When attempting to enter prices formatted with commas (e.g. `"1,500"`) or currency strings (e.g. `"Rs. 1,500"`), `float(request.forms.get("retail_price"))` raises an unhandled `ValueError: could not convert string to float: '1,500'`, resulting in an HTTP 500 error page.
* **Reproduction Scenario (API):**  
  `POST /api/products/quick-add` with `{"brand": "Baseus", "name": "PowerBank 20000mAh", "item_type": "ACCESSORY"}` inserts a record into `products` table only. It creates **no variant, no price, no barcode, and no initial stock quantity**.

### 2.2 Complete Item Add/Edit Code Path Matrix

| Entry Path | Entity / Item Type | Endpoint | Client Validation | Server Validation | ACID Transaction | Status / Failure Cause |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Inventory -> New Model** | Phone / Accessory / Part | `POST /inventory/create-product` | `required` on name, brand | Trims strings; no money validation | No | **BROKEN FOR ACCESSORIES:** Redirects to phone matrix; accessories filtered out. |
| **Variant Matrix Creator** | Phone Variant Matrix | `POST /inventory/matrix-create-submit` | HTML5 `required` | `float(price)` | Yes (`inventory.generate_variant_matrix`) | **FRAGILE:** Throws `ValueError` on `"1,500"` or `"Rs. 1,500"`. RAM/Storage not applicable to accessories. |
| **Direct Variant Add** | Phone / Accessory / Part | `inventory.create_variant()` | None | Strips strings; `float(price)` | Yes (`db.transaction()`) | **FAIL ON DUPLICATE/EMPTY BARCODE:** Blank barcode inserted as `""` instead of `NULL`; money strings throw `ValueError`. |
| **Unit Stock In** | Phone Unit (IMEI) | `inventory.add_unit()` | Form check | Duplicate IMEI check; `float(cost)` | Yes | **FAIL ON MONEY:** Throws `ValueError` on `"1,500"`. IMEI 2 empty string instead of NULL. |
| **Unit Edit** | Phone Unit | `inventory.update_unit()` | Form check | Duplicate IMEI check | Yes | Works for clean floats; crashes on formatted currency. |
| **QuickAdd Product** | Model (Any Type) | `POST /api/products/quick-add` | JS check | Brand & name required | No | **INCOMPLETE:** Creates product only, no variant or stock created. |
| **Purchasing Receive** | Bulk IMEIs & Accessory Qty | `POST /purchasing/receive` | JS check | Variant existence, IMEI format | Yes (`purchasing.create_purchase`) | Works if variant pre-exists; cannot create new variant on the fly. |
| **Trade-In Intake** | Used Phone Unit | `POST /returns/trade-in` | JS check | IMEI check; creates unit | Yes | Works for phones; no support for accessory trade-in. |
| **Repair Spare Part** | Spare Part | `POST /repairs/add-part/<rid>` | JS check | Checks `spare_variant_id` | Yes | Requires pre-existing spare part variant. |

---

## 3. Authentication & Role Permissions Audit

### 3.1 Credentials & Password Storage
* **Password Hashing:** `auth.py` line 10 uses `hashlib.sha256((str(password) + salt).encode('utf-8')).hexdigest()`. Salt is a static constant (`config.SESSION_SECRET`). **Non-compliant:** Must use salted `bcrypt` with work factor tuned to 150-300 ms.
* **Default Credentials:** `config.py` contains:
  * `DEFAULT_ADMIN_USERNAME = "admin"`
  * `DEFAULT_ADMIN_PASSWORD = "admin123"`
  * `DEFAULT_STAFF_USERNAME = "staff"`
  * `DEFAULT_STAFF_PASSWORD = "staff123"`
  * **Violation:** Requirement mandates zero default credentials. First-run wizard required when DB is empty; existing users must be migrated to bcrypt and forced to change password.
* **Admin Override PIN:** Stored in plaintext (`admin_pin = '9999'` in `settings` table). Must be securely hashed.
* **Brute-Force Protection:** No rate limiting or account lockout implemented on `/login`. Vulnerable to dictionary attacks.

### 3.2 Route x Role Permissions Matrix

| Route | Method | Expected Allowed Roles | Current Check in Code | Vulnerability Status |
| :--- | :--- | :--- | :--- | :--- |
| `/login` | GET, POST | Anonymous | None | Open (Correct) |
| `/logout` | GET | Authenticated | None | Open (Correct) |
| `/pos` | GET | Employee, Admin | `require_login()` | OK |
| `/api/pos/checkout` | POST | Employee, Admin | `require_login()` | OK |
| `/inventory` | GET | Employee (View-only), Admin (Full) | `require_login()` | **LEAK:** Employee sees cost, margin, and edit buttons. |
| `/inventory/create-product` | POST | Admin only | `require_login()` | **CRITICAL LEAK (RED):** Employee can create products! |
| `/inventory/matrix-create` | GET | Admin only | `require_login()` | **CRITICAL LEAK (RED):** Employee can access matrix creator! |
| `/inventory/matrix-create-submit`| POST | Admin only | `require_login()` | **CRITICAL LEAK (RED):** Employee can generate variants! |
| `/purchasing` | GET | Admin only | `require_admin()` | Protected (Returns raw 403 HTML) |
| `/purchasing/receive` | POST | Admin only | `require_admin()` | Protected |
| `/returns` | GET, POST | Employee, Admin | `require_login()` | OK |
| `/repairs` | GET, POST | Employee (Jobs), Admin (Full) | `require_login()` | OK |
| `/software` | GET, POST | Employee (Jobs), Admin (Full) | `require_login()` | OK |
| `/expenses` | GET, POST | Admin (or granted employee) | `require_admin()` | Protected |
| `/reports` | GET | Admin only | `require_admin()` | Protected (Returns raw 403 HTML) |
| `/reports/top-sellers` | GET | Admin only | `require_admin()` | Protected (Returns raw 403 HTML) |
| `/settings` | GET, POST | Admin only | `require_admin()` | Protected |
| `/api/search` | GET | Employee (Sanitized), Admin | `require_login()` | **LEAK:** Returns wholesale/cost data to Employee. |

---

## 4. Shop Identity & Legacy Literals Audit

* **Central Store:** Shop name, tagline, address, phones, and warranty terms are read from `settings` via `printing.get_shop_info()`.
* **Legacy Literals ("ATFAAL", "Garments", "Kapra"):**
  * Automated grep scan of all `.py`, `.html`, `.js`, `.css`, and `.iss` source files found **0 occurrences** in active code. (Legacy terms only exist in changelog/removal history markdown documentation).
* **Missing Shop Identity Features:**
  1. No logo upload or central logo processing (no conversion to monochrome thermal bitmap for 80mm/58mm or favicon).
  2. No unified Shop Profile editing screen under Settings (`Settings -> Shop Profile`).
  3. No live sync / change-feed propagation across open windows when shop profile is edited.
  4. Footer note in receipts and UI contains hardcoded author attribution `"Developed by Ahmed"` which should be customizable.

---

## 5. Baseline Performance Benchmark (Before Hardening)

Executed via `benchmark_speed.py` on local system:
* **Universal Scanner Engine:** Avg 7.64 ms (Target: $\le 100$ ms) -> **PASS**
* **POS Checkout Transaction (ACID):** Avg 23.34 ms (Target: $\le 100$ ms) -> **PASS**
* **Catalog Fuzzy Search:** Avg 1.79 ms (Target: $\le 50$ ms) -> **PASS**
* **Thermal Receipt Compilation:** Avg 4.88 ms (Target: $\le 50$ ms) -> **PASS**
* **5-Stream Earnings Aggregation:** Avg 9.81 ms (Target: $\le 50$ ms) -> **PASS**
* **Full Automated Test Suite:** 21/21 passed in 26.43s.

---

## 6. Audit Verdict & Gate G1 Sign-Off
All 5 Gate G1 audit requirements have been verified, backed up, reproduced, and documented.  
Gate G1 is **COMPLETE**. Ready for Gate G2 Design.
