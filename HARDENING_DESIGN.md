# HARDENING ARCHITECTURE DESIGN (GATE G2)
**Project:** Mobile & Accessories Shop ERP + POS  
**Release:** v1.0-PRO Hardened Edition  
**Target:** Windows 10/11 x64, Standard User, Localhost 127.0.0.1, Offline  

---

## 1. Unified Item Creation & Mutation Contract (Part 1)

### 1.1 Single Service Contract (`create_item_unified`, `update_item_unified`)
All paths (Inventory UI, QuickAdd modal, Variant Matrix, Purchasing, POS, Trade-In) call a single server-side service in `inventory.py`.

```
Payload Contract:
- item_type: "PHONE" | "SERIAL" | "ACCESSORY" | "SPARE_PART" (Required)
- brand: string (1-60 chars, trimmed)
- name: string (1-120 chars, trimmed, Unicode/Urdu supported)
- category: string (Default "Smartphone" / "Accessory" / "Spare Parts")
- retail_price: number | string (Parsed: "1,500", "Rs. 1,500", Urdu digits -> float >= 0)
- wholesale_price: number | string (Parsed -> float >= 0, default 0)
- min_selling_price: number | string (Parsed -> float <= retail_price)
- stock_quantity: integer (Whole number >= 0, for ACCESSORY/SPARE_PART)
- barcode: string | null (Blank -> Auto-generated unique barcode)
- sku: string | null (Blank -> Auto-generated unique SKU)
- low_stock_level: integer | null (0-99999, null inherits category/global)
- reorder_qty: integer | null (0-99999)
- alert_off: 0 | 1
- ram / storage / color: strings (For PHONE/SERIAL)
- compatible_models: string (For accessories/spares)
- request_id: UUID string (For idempotency)
```

### 1.2 Data Normalization & Auto-Codes
1. **Money Normalizer:** Strips `Rs.`, `PKR`, commas, whitespace, and translates Eastern Arabic / Urdu digits (`۰-۹`) to standard ASCII digits `0-9`.
2. **Auto-Generated Codes:** If `barcode` or `sku` is omitted or empty, the server generates a collision-free code using an atomic sequence table `code_counters`:
   - Accessory: `ACC-000101`, `BAR-ACC-000101`
   - Phone Variant: `PHN-000101`, `BAR-PHN-000101`
   - Spare Part: `PRT-000101`, `BAR-PRT-000101`
3. **Empty Text to NULL:** Any empty optional code is converted to `NULL` (never `""`) preventing SQLite unique constraint collisions on empty strings.
4. **Resilient Derived Data:** Search FTS5 index update, low-stock alert evaluation, and daily sales aggregates execute in safe sub-blocks within the ACID transaction. If a derived index step encounters an edge case, the item record and stock ledger are safely committed, the incident is logged, and self-repair re-indexes on startup.

---

## 2. Authentication, Accounts & Employee Lock-Down (Parts 2-3)

### 2.1 First-Run Wizard & Zero Default Credentials
1. **First-Run Trigger:** On startup or `/login`, if `SELECT COUNT(*) FROM users` is 0 or contains default plaintext/legacy hashes, the user is redirected to `/setup` wizard.
2. **Setup Wizard Steps:**
   - Shop details: Name (required), address, phone, WhatsApp.
   - Admin credentials: Username (unique), password (min 8 chars, typed twice).
   - Generates and presents a 24-character **Recovery Key** (`XXXX-XXXX-XXXX-XXXX-XXXX-XXXX`) with a mandatory "I have securely saved this key" confirmation checkbox. Only the bcrypt hash of the key is persisted.
3. **Password Security:**
   - Standard `bcrypt` with salt and cost factor 11 (~180 ms execution).
   - Zero hardcoded passwords in code, seeds, or docs.

### 2.2 Brute-Force Rate Limiting
- Login attempts tracked in memory/DB: 5 consecutive failed attempts per username triggers a 30-second exponential backoff delay (doubling up to 5 minutes).
- Responses return generic message: `"Invalid username or password"`.

### 2.3 Role & Permission Architecture (Deny by Default)
1. **Central Matrix:**
   - `ADMIN`: Full access to all routes, financial reports, user management, and shop settings.
   - `EMPLOYEE`: POS billing, returns, view-only inventory (retail price only), job tickets.
2. **Backend Field Stripping:**
   - Dedicated serializer `serialize_item_for_role(item, role)`: Automatically deletes `wholesale_price`, `cost_price`, `cost`, `supplier_id`, `supplier_name`, `margin`, and `profit` when role is `EMPLOYEE`.
   - Mutating inventory routes (`/inventory/create-product`, `/inventory/create-item`, `/inventory/matrix-create-submit`) strictly require Admin privileges.
   - Forbidden deep-link visits render a clean in-app `"Access Denied"` panel (HTTP 403) instead of leaking data or showing raw server tracebacks.

---

## 3. Shop Profile & Live Change-Feed (Part 4)

### 3.1 Central Shop Profile Store
- Managed in `shop_profile` table with integer `profile_version` incrementing on each update.
- Admin manages profile at `/settings/shop-profile`.
- **Logo Processing Engine:**
  - PNG/JPG upload automatically converted using Pillow:
    - `logo_ui.png`: Rescaled for top bar and login screen.
    - `logo_thermal_80mm.bin` & `logo_thermal_58mm.bin`: Dithered 1-bit monochrome ESC-POS graphics for receipt printers.
    - `favicon.ico`: 32x32 / 16x16 icon for browser and window taskbar.

### 3.2 Real-Time Change-Feed (`/api/change-feed`)
- Lightweight HTTP endpoint: `GET /api/change-feed?v=<client_version>`
- Returns: `{version: N, profile_version: P, groups: {items: I, stock: S, alerts: A, users: U, profile: P}}`
- Polling strategy: Client polls every 2 seconds only when window is active (`document.hasFocus()`). Pauses when minimized or blurred.
- Average response time: < 3 ms. Total idle CPU consumption: < 0.2%.
- Live DOM patch: Updates shop title, logo, top bar, and alert bell badge seamlessly without page reloading or wiping user input fields.

---

## 4. Launcher, Shortcuts & Windows Packaging (Part 5)

### 4.1 Windows Desktop Launcher (`launcher.py`)
- Direct execution into dedicated browser application window (`--app=http://127.0.0.1:8085`).
- Strictly binds to `127.0.0.1` (no Windows Firewall alert).
- Isolated browser profile directories per role:
  - Admin: `%localappdata%\MobileShopERP\browser_profile_admin`
  - Counter: `%localappdata%\MobileShopERP\browser_profile_counter`
- Suppresses Chromium first-run, sync, and recovery bubbles.
- Clean process shutdown on final window close with automatic SQLite WAL checkpoint (`PRAGMA wal_checkpoint(TRUNCATE)`).

### 4.2 Inno Setup & Build Pipeline
- `setup.iss` with `PrivilegesRequired=lowest` and `asInvoker` manifest (zero UAC prompts).
- Creates two distinct desktop shortcuts:
  - `Mobile Shop ERP - Admin` (`--role=admin`)
  - `Mobile Shop ERP - Counter` (`--role=employee`)
- `BUILD.bat` includes automated code signing hook (`signtool.exe`) supporting environment-driven PFX certificates with RFC 3161 timestamps.
