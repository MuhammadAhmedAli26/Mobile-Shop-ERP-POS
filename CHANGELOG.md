# CHANGELOG

## [v1.0.0-PRO] - 2026-10-11 - Final Production Desktop Release (Gates G1–G6)

### 🚀 Highlights & Packaging
- **Standalone Windows Desktop Binary:** Built windowed `dist\MobileShopERP\MobileShopERP.exe` and `release\MobileShopERP-1.0.0-portable.zip` with zero external runtime requirements.
- **Pristine Fresh Database:** Executed `clean_database.py` purging all 24 dummy transaction and inventory tables. Shipped database contains 0 dummy records, with admin accounts, lookups, and software catalog preserved.
- **Waitress Multi-Threaded WSGI Server:** 6 worker threads running on `127.0.0.1`, replacing single-threaded dev server.
- **High-Performance SQLite Configuration:** In-memory temp store (`temp_store=MEMORY`), 64MB cache (`cache_size=-64000`), and 128MB mmap (`mmap_size=134217728`) in WAL mode.
- **POS Hold & Resume Cart:** Cashiers can park active customer carts (`⏸️ Hold Cart`) and resume them (`▶️ Resume`) without losing entered items.
- **POS Unit Resolution Hardening:** Fixed `unit.unit_id || unit.id` extraction in POS cart and added automatic IMEI fallback in `pos_checkout` resolving "Device unit #0 not found".
- **Single Instance Mutex Guard:** Windows mutex `Local\MobileShopERP_SingleInstance_Mutex` prevents dual-launch database locking.
- **Port Conflict Fallback:** Automatically switches to port 8086 if 8085 is in use.
- **App-Mode Browser Launcher:** Dedicated Edge/Chrome window with isolated profile directory in `%LOCALAPPDATA%\MobileShopERP\browser_profile`.
- **Windows Defender Scanned:** Verified 100% clean by `MpCmdRun.exe`.

---

### 🎯 Overview
Comprehensive fix-and-upgrade pass resolving all search, routing, and scanner-burst conflicts across the **Mobile & Accessories Shop ERP + POS** (offline edition, `http://localhost:8085`).

---

### 🐛 Fixed Deficiencies

1. **Inventory Model 404 Resolution (`/inventory/models/<id>`)**
   - **Root Cause**: `search.py` generated deep links to `/inventory/models/{product_id}`, but Bottle had no registered route for this pattern.
   - **Fix**: Added `@app.route("/inventory/models/<pid:int>")` and `@app.route("/inventory/models/<pid:int>/")` serving the dedicated Model Details Hub in `web_ui.py`. Supports optional unit highlighting via `?unit=<uid>` and friendly fallback card if the model is archived or missing.

2. **POS Instant Product Search & Typeahead Dropdown**
   - **Root Cause**: `#pos-scan-input` only listened to `Enter` keypresses, routing raw text to `/api/scan-route` which attempted exact barcode/SKU matches and returned `CODE_NOT_FOUND` for hand-typed product names (e.g., "samsung").
   - **Fix**:
     - Added live `#pos-search-dropdown` with 30ms debounced input listener querying `/api/search/products`.
     - Supports direct addition of accessories (+1 to cart) with sound feedback.
     - Supports single in-stock phone units (adds unit directly to cart).
     - Opens `#pos-imei-picker-modal` when multiple units of a phone variant exist, letting the cashier select the exact physical IMEI.
     - Out-of-stock toast notification if stock is 0.
     - Up/Down arrow and Enter keyboard navigation.
     - Added fallback search in `scanner.py:universal_scan_route` when text is submitted via Enter.

3. **1-Character Instant Search (`len(q) >= 1`)**
   - **Root Cause**: Artificial `len(q) < 2` guard in `search.py` and `web_ui.py` blocked single-letter instant searches.
   - **Fix**:
     - Removed `< 2` restriction across backend and frontend. Typing even "a" immediately returns matches.
     - Implemented 4-tier relevance ranking in SQL:
       - **Tier 1 (Score 100)**: Exact barcode, SKU, or IMEI.
       - **Tier 2 (Score 80)**: Starts-with prefix on brand or model name (`LIKE 'q%'`).
       - **Tier 3 (Score 60)**: Word starts-with (`LIKE '% q%'`).
       - **Tier 4 (Score 40)**: Substring match (`LIKE '%q%'`).
     - Added safety limit and SQL wildcard escaping (`%` and `_`).

4. **Branded 404 & 500 Error Pages**
   - **Root Cause**: Missing application-level error handlers in Bottle, displaying raw unstyled HTML error text.
   - **Fix**: Registered `@app.error(404)` and `@app.error(500)` in `web_ui.py`. Returns clean JSON for `/api/*` requests and styled dark-mode in-app HTML layout with quick navigation links for browser pages.

5. **Scanner Burst & Typeahead Coexistence**
   - **Root Cause**: Fast barcode scanner keystrokes could trigger typeahead dropdown updates and conflict with cart addition.
   - **Fix**: Scanner burst detector ($\le 45$ms) immediately hides `#pos-search-dropdown` during scan submission, ensuring clean, interference-free cart addition.

6. **Deep Linking Standard across the Application**
   - Added routes for `/credit/customer/<cid:int>` (Customer Khata Ledger).
   - Added routes for `/purchasing/supplier/<sid:int>` (Supplier Ledger).
   - Added routes for `/sales` (redirects to sale invoice print slip).
   - Added routes for `/repairing` (alias to `/repairs`).

7. **Urdu / Arabic Normalization across Tables & SmartSelect**
   - Added global `window.normText` helper normalizing Urdu digits (`۰-۹`, `٠-٩`) and characters (`ي/ك/ة/ھ/ؤ/إ/أ/آ` $\to$ `ی/ک/ہ/و/ا`).
   - Integrated into `SmartSelect` and all client-side table filter inputs.

---

### 🧪 Verification & QA
- **`test_search_fix_verification.py`**: 42/42 Tests Passed (100%).
- **`test_scanner_burst.py`**: 5/5 Tests Passed (100%).
- **`test_search_15.py`**: 15/15 Tests Passed (100%).
- **`verify_http_endpoints.py`**: 33/33 Web Routes & Print Endpoints Verified (100%).
- **Phase Regression Suites**:
  - `test_phase1.py`: 10/10 Passed (100%).
  - `test_phase2.py`: 9/9 Passed (100%).
  - `test_phase3.py`: 14/14 Passed (100%).
  - `test_phase4.py`: 10/10 Passed (100%).
  - `test_phase5.py`: 8/8 Passed (100%).
- **`benchmark_speed.py`**:
  - Scanner Engine: 1.64 ms
  - Search Latency: 1.56 ms
  - POS Checkout: 16.08 ms
  - Receipt Compilation: 5.03 ms
  - P&L Aggregation: 8.99 ms
