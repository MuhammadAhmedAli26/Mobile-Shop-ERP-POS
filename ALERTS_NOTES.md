# MOBILE & ACCESSORIES ERP — ALERTS & TOP SELLERS ENGINEERING NOTES

## Current Status
- Gate G1 Audit: COMPLETED (documented in `ALERTS_AUDIT.md`)
- Gate G2 Design: COMPLETED (documented in `ALERTS_DESIGN.md`)
- Gate G3 Alert Engine & Hooks: COMPLETED (verified via `test_alerts_g3.py` - 100% PASS)
- Gate G4 UI Surfaces & Hand-Off: COMPLETED (bell, drawer, `/inventory/low-stock`, A4 print, CSV export, POS toast)
- Gate G5 Top Sellers & Analytics: COMPLETED (`/reports/top-sellers`, POS quick drawer, A4 report, CSV export)
- Gate G6 Red Team & Packaging: COMPLETED (`Mobile_Shop_ERP.exe` direct single-file binary built and verified)

## Key Engineering Decisions
1. **Three-level Inheritance Model**:
   - Level resolution: `COALESCE(variant.low_stock_level, category.default_low_stock_level, global_default)`
   - Where NULL means "Inherit from parent".
   - Seed global defaults: Phones = 2, Accessories = 5, Spare Parts = 3.
   - If `alert_off == 1`, alert state is always `OFF`.

2. **Stock Count Definition**:
   - Phones/Serial items: Units with `status = 'IN_STOCK' AND is_archived = 0`.
   - Accessories/Spare Parts: `stock_quantity` on variants where `is_archived = 0`.
   - Archived products/variants never generate alerts.

3. **Alert State Machine**:
   - `OK`: stock > level
   - `LOW`: stock <= level and stock > 0
   - `OUT`: stock == 0
   - `OFF`: alert disabled
   - Flags: `snoozed` (`snoozed_until > now`), `on_order` (`on_order_qty > 0`)

4. **Event-Driven Transitions & Notifications**:
   - Only worsening transitions notify: `OK -> LOW`, `OK -> OUT`, `LOW -> OUT`.
   - Restocking resolves state (`LOW -> OK`, `OUT -> OK`, `OUT -> LOW`).
   - Notification deduplication: no repeat alerts on subsequent sales when already LOW or OUT.

5. **Pre-Aggregated Sales Daily Table**:
   - `sales_daily_by_variant` (date, variant_id, product_id, category_id, brand_id, units_sold, gross_revenue, cost_total, units_returned, net_profit)
   - Incremental deltas in sale, return, and sale edit transactions.
