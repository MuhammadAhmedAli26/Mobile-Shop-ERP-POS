# MOBILE & ACCESSORIES ERP — G1 AUDIT (LOW-STOCK ALERTS & TOP-SELLING ANALYTICS)

## 1. Real Stack Verification
- **Host OS**: Windows 11/10 x64 (100% Offline, Single-Instance Mutex `Local\MobileShopERP_SingleInstance_Mutex`)
- **Runtime**: Python 3.14 (amd64)
- **Application Server**: Bottle 0.13 WSGI hosted via Waitress 3.0.2 (Multi-threaded, 6 background worker threads, IPv4 loopback binding `0.0.0.0:8085` / `127.0.0.1:8085`)
- **Database Engine**: SQLite 3.45+ with `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, `PRAGMA foreign_keys=ON`, `PRAGMA temp_store=MEMORY`, `PRAGMA cache_size=-64000`
- **UI / Frontend**: Native HTML5, modern CSS variables (`data-theme="dark"` / `data-theme="light"`), Vanilla JavaScript ES6+, SmartSelect + QuickAdd custom components, Zero CDN dependencies, 100% local assets
- **POS Hardware**: USB Barcode/QR Scanner (Keystroke wedge + hardware burst buffer), ESC/POS Thermal Receipt Printer (80mm / 58mm) & A4 Invoices

---

## 2. Current Low-Stock Queries & Data Model Audit
| File & Line | Current Implementation | Status / Action Needed |
|---|---|---|
| `db.py:108` | `reorder_level INTEGER DEFAULT 5` column on `variants` | Kept for compatibility; upgraded with `low_stock_level` (NULLable for inheritance), `reorder_qty`, and `alert_off` |
| `inventory.py:61,69,71` | `create_variant` sets `reorder_level=5` | Upgrade to support `low_stock_level`, `reorder_qty`, `alert_off` with category inheritance |
| `inventory.py:111` | `generate_variant_matrix` hardcodes `reorder_level=3` | Remove hardcode; inherit category default and accept matrix override level |
| `inventory.py:119,123,125` | `update_variant` updates `reorder_level` | Add explicit level, reorder qty, and alert off toggle |
| `inventory.py:141` | `clone_variant` copies `orig["reorder_level"]` | Ensure cloned variant copies full alert configuration |
| `scanner.py:156` | Checks accessory `stock_quantity <= 0` -> `ACCESSORY_OUT_OF_STOCK` | Wire directly to unified `stock_state()` engine |
| `web_ui.py:576-597` | Dashboard KPI cards: only total phones stock, no low/out stock cards | Add "Out of stock" and "Low stock" KPI cards + top 5 urgent items list |
| `web_ui.py:447-469` | Top-bar: Drawer cash, user badge, theme toggle, shortcuts, logout | Add `🔔` Alert Bell with badge count (Out + Low) and urgent popover panel |

---

## 3. Every Item Form Audit
| Item Form | Current Location | Required Alert Controls |
|---|---|---|
| **Phone Model Form** | `web_ui.py:1471`, `web_ui.py:1668` | Shows category inherited low-stock level; model-level sum alert toggle `alert_model_stock_threshold` |
| **Variant Form** | `inventory.py:create_variant`, `update_variant` | Visible "Alert me when stock is at or below [ N ]" with quick chips (1, 2, 3, 5, 10), prefilled from category default ("From category: N"), Reorder qty field, "Don't alert for this item (Off)" toggle |
| **Matrix Creator** | `web_ui.py:1677`, `inventory.py:generate_variant_matrix` | Model-wide base alert level + override column in generated variant matrix |
| **Clone Variant** | `inventory.py:clone_variant` | Copies explicit `low_stock_level`, `reorder_qty`, and `alert_off` |
| **Accessory Form** | `web_ui.py:1471`, QuickAdd | Field next to price/qty: alert level chips, reorder qty, off toggle |
| **Spare Part Form** | `web_ui.py:1471`, QuickAdd | Field next to price/qty: alert level chips, reorder qty, off toggle |
| **Inline "+ Add new" in Purchasing** | `web_ui.py:1884`, `static/smart_select.js` | Direct alert level field in QuickAdd modal |
| **Inline "+ Add new" in POS** | `web_ui.py:POS`, `static/smart_select.js` | Direct alert level field in QuickAdd modal |
| **Inventory Bulk Tool** | `inventory.py:bulk_price_update` | Add "Set alert level" bulk action: [Custom Number / Use Category Default / Off] |
| **Excel / CSV Import / Export** | To be added in `inventory.py` | Columns: `low_stock_level`, `reorder_qty` (blank = inherit category default) |

---

## 4. Stock Mutation Code Paths (100% Coverage Matrix)
Every code path that alters stock must call the unified alert evaluation hook `alert_engine.evaluate_stock_transitions(cx, affected_variant_ids, user_id)` within the **SAME ACID transaction**:

| # | Code Path | Function Location | What Changes | Calls Alert Hook? | Updates Sales Aggregates? |
|---|---|---|---|---|---|
| 1 | **POS Sale (Phone)** | `pos.py:92` | `units.status` -> `'SOLD'` | **YES** | **YES** (adds units, revenue, cost) |
| 2 | **POS Sale (Accessory/Part)**| `pos.py:118` | `variants.stock_quantity -= qty` | **YES** | **YES** (adds units, revenue, cost) |
| 3 | **POS Return (Restock)** | `pos.py:257, 266` | `units.status` -> `'IN_STOCK'`, variant `stock_quantity += qty` | **YES** | **YES** (increments returned units) |
| 4 | **POS Return (Defective)** | `pos.py:257` | `units.status` -> `'DEFECTIVE'` (no stock increment) | **YES** | **YES** (increments returned units) |
| 5 | **Admin Sale Edit** | `pos.py:354, 356, 374, 376` | Restores old items to stock, deducts new items | **YES** | **YES** (re-applies deltas) |
| 6 | **Trade-In / Buyback** | `pos.py:317` | New phone unit added with `'IN_STOCK'` | **YES** | NO (Purchase / Buyback) |
| 7 | **Purchase Inward (Phone)** | `purchasing.py:177` | New units added with `'IN_STOCK'` | **YES** | NO (Purchase) |
| 8 | **Purchase Inward (Accessory)**| `purchasing.py:190`| `variants.stock_quantity += qty` | **YES** | NO (Purchase) |
| 9 | **Return to Supplier (Phone)**| `purchasing.py:295`| `units.status` -> `'RETURNED_TO_SUPPLIER'` | **YES** | NO (Supplier debit) |
| 10 | **Return to Supplier (Acc)** | `purchasing.py:304`| `variants.stock_quantity -= qty` | **YES** | NO (Supplier debit) |
| 11 | **Repair Part Fitted** | `services.py:186` | Spare part `variants.stock_quantity -= qty` | **YES** | NO (Workshop service) |
| 12 | **Inventory Add Unit** | `inventory.py:173` | Unit inserted with `'IN_STOCK'` | **YES** | NO |
| 13 | **Inventory Update Unit** | `inventory.py:202` | Status changed (e.g. IN_STOCK <-> DEFECTIVE/IN_REPAIR) | **YES** | NO |
| 14 | **Move Unit to Variant** | `inventory.py:214` | Unit transferred between variants | **YES** (both variants) | NO |
| 15 | **Variant Direct Stock Edit** | `inventory.py:123` | `variants.stock_quantity` directly modified | **YES** | NO |
| 16 | **Archive / Restore Product**| `inventory.py:32` | `is_archived` changed | **YES** | NO |
| 17 | **Category Default Changed** | `lookups.py` | All inheriting variants re-evaluated | **YES** (bulk summary) | NO |

---

## 5. Sales Tables & Ranking Analytics Audit
- **Raw Transaction Tables**:
  - `sales`: `id`, `invoice_no`, `status` (`'COMPLETED'`, `'EDITED'`, `'RETURNED'`, `'CANCELLED'`), `created_at`
  - `sale_items`: `id`, `sale_id`, `variant_id`, `unit_id`, `item_type`, `qty`, `unit_price`, `cost_price`, `line_total`, `profit`, `is_returned`
  - `returns`: `id`, `sale_id`, `return_no`, `return_date`, `created_at`
  - `return_items`: `id`, `return_id`, `sale_item_id`, `variant_id`, `qty`, `refund_amount`, `return_action`
- **Pre-Aggregated Reporting Table to Create**:
  - `sales_daily_by_variant`:
    `(date TEXT, variant_id INTEGER, product_id INTEGER, category_id INTEGER, brand_id INTEGER, units_sold INTEGER, gross_revenue REAL, cost_total REAL, units_returned INTEGER, net_profit REAL, PRIMARY KEY (date, variant_id))`
  - Delta hooks maintain this inside sales, return, and sale edit transactions.
  - O(1) query time: any period ranking runs in <= 50ms instead of scanning hundreds of thousands of raw lines.
