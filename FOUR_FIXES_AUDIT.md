# FOUR FIXES AUDIT (GATE 1 REPORT)

## Baseline Summary
- **Baseline Suite Status:** 59 passed in 8.07s
- **Speed Benchmarks:**
  - Scanner: 8.11 ms (Target <= 100 ms)
  - POS Checkout: 23.98 ms (Target <= 100 ms)
  - Fuzzy Search: 1.81 ms (Target <= 50 ms)
  - Receipt Print: 6.63 ms (Target <= 50 ms)
  - 5-Stream Earnings Center: 10.28 ms (Target <= 50 ms)

---

## 1. Bug 1: Once Mobile Added to Inventory It Cannot Be Edited

### Hypothesis
1. The inventory edit modal (`#edit-item-modal`) was originally built for single-variant / quantity-based items (accessories) and expected a single `variant_id` and manually typed `stock_quantity`.
2. For phones, stock quantity is derived strictly from `units` table (`COUNT(units WHERE status='IN_STOCK')`), causing confusion and potential desynchronization if manually typed.
3. No UI or backend route existed to edit Variant specifications (RAM, Storage, Color, network, wholesale/retail/minimum prices, low-stock thresholds).
4. No 2-click clone variant UI existed in the product view.
5. In the Unit Editor:
   - IMEI validation did not implement 15-digit Luhn check with Admin override.
   - Moving a unit to another variant was not accessible in the unit modal.
   - Editing a SOLD or IN_REPAIR unit did not require Admin privilege + mandatory reason + warning on historical invoices/profit impact + detailed audit logging.
   - `imei2` empty strings were risk of collision if saved as `""` rather than `NULL`.
   - Employee was not strictly blocked with 403 on backend.

### Evidence & Root Cause
- **File/Line:** `mobile_edition/web_ui.py:2320-2345`, `web_ui.py:3110-3160`, `mobile_edition/inventory.py:236-278`, `inventory.py:345-385`.
- `update_item_unified` at `inventory.py:1062` overwrote `variant["stock_quantity"]` directly with `new_sq`, ignoring phone unit counts.
- `inventory.update_variant` existed in backend but had zero endpoints in `web_ui.py` and zero buttons on the Variant table in `inventory_model_detail_screen`.
- Unit modal had no variant dropdown to move a unit, no Luhn validation check, and no warning/reason prompt for SOLD units.

---

## 2. Bug 2: Daily Closing Does Not Show Expenses & Canonical Payment Account Rule

### Hypothesis
1. `record_expense` saves payments under account labels like `"Cash Drawer"` by default, but queries in `accounting.py` relied on disparate ad-hoc string comparisons (`= 'CASH'` or `LIKE '%CASH%'` or `LIKE '%DRAWER%'`).
2. There was no single canonical rule or function defining whether an account is Cash, Bank, or Wallet across Day Closing, Cash Flow, Net Profit, Monthly Report, Earnings Center, supplier payments, and udhaar recoveries.
3. Past-date closings or non-cash accounts (Bank/Wallet) were not explicitly separated into Cash Drawer vs Non-Drawer expense totals.
4. Old expense records in the database may contain non-normalized payment account names.

### Evidence & Root Cause
- **File/Line:** `mobile_edition/accounting.py:200-260`, `mobile_edition/lookups.py:1-60`.
- In `lookups.py`, `lookup_lists` table has 8 accounts (`Cash Drawer`, `EasyPaisa Merchant`, `JazzCash Merchant`, `Raast / Bank Alfalah`, `Meezan Bank`, `HBL`, `Allied Bank`, `MCB`), but lacked an explicit `account_type` column (CASH / BANK / WALLET).
- In `accounting.py`, `get_day_closing_data` used raw SQL string pattern matching.
- `audit_g1_reproduce.py` showed `is_cash_account` function did not exist anywhere in the codebase.

---

## 3. Bug 3: Date-Wise Daily Sale Screen

### Hypothesis
1. No dedicated Daily Sales reporting view existed to view all sales for a selected date, month, or custom range with quick buttons (`Today`, `Yesterday`, `This Week`, `This Month`, `Last Month`).
2. There was no date-aggregated month view showing row-per-day breakdown (invoices, phones, accessories, gross sales, discounts, returns, net sales, cost, profit, payment mode split, expenses, net of day) matching Earnings Center and Monthly Report.
3. Drill-down from date row -> invoice list -> receipt reprint was missing.
4. Employee permission filter (Employee sees only own sales without cost/profit) was absent.

### Evidence & Root Cause
- **File/Line:** `mobile_edition/web_ui.py:7745-7890`.
- Previous `/sales` route only displayed a flat list of invoices for a single date without month-view aggregations, date-range filtering, payment split columns, expense reconciliation, employee role privacy serializer, or CSV/print export.

---

## 4. Bug 4: Back-Dated Transactions

### Hypothesis
1. Business requirements demand two distinct timestamps on financial and inventory records:
   - `transaction_date` (Business date, used by all reports, Daily Sales, Day Closing, Earnings Center, Stock Ledger).
   - `recorded_at` (Audit timestamp when the entry was physically created in the system, immutable).
2. Existing schema for `sales`, `expenses`, `purchases`, `stock_ledger` only had single timestamps (`created_at` or `expense_date`).
3. Back-dating was not supported across purchases, supplier payments, udhaar payments, returns, and repair delivery.
4. Validation rules were missing:
   - Future dates must be rejected.
   - Selling a unit on a date prior to its purchase/intake date must be rejected.
   - Back-dating into an already-closed day must prompt with a clear warning, require a reason, and mark the day closing as `modified_after_closing = 1`.
   - Admin-only enforcement (Employee blocked with 403 unless granted explicit permission).

### Evidence & Root Cause
- **File/Line:** `mobile_edition/pos.py:10-40`, `mobile_edition/accounting.py:15-30`, `mobile_edition/purchasing.py:10-50`.
- Schema audit in `audit_g1_reproduce.py` proved `sales`, `purchases`, `stock_ledger` lacked `transaction_date` column.
- Pre-aggregated tables (e.g. `sales_daily_by_variant`) only used simple dates without back-date modification support.

---

## Gate 1 Conclusion
All 4 bug domains have been audited and root causes identified without code mutations. Ready for Gate 2 execution.
