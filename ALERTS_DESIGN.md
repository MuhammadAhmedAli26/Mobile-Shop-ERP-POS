# MOBILE & ACCESSORIES ERP — G2 ARCHITECTURAL DESIGN

## 1. Schema Extensions & Idempotent Migrations
Before executing any DDL or migration, an automatic timestamped backup is made to `backups/mobile_erp_pre_alerts_backup_{timestamp}.db`.

### 1.1 Altered Tables
- `lookup_lists`:
  - `default_low_stock_level INTEGER DEFAULT NULL`
  - `default_reorder_qty INTEGER DEFAULT NULL`
- `products`:
  - `alert_model_stock_threshold INTEGER DEFAULT NULL`
- `variants`:
  - `low_stock_level INTEGER DEFAULT NULL`
  - `reorder_qty INTEGER DEFAULT NULL`
  - `alert_off INTEGER DEFAULT 0`

### 1.2 New Tables
```sql
CREATE TABLE IF NOT EXISTS stock_alert_state (
    variant_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    current_stock INTEGER NOT NULL DEFAULT 0,
    effective_level INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'OK', -- 'OK', 'LOW', 'OUT', 'OFF'
    snoozed_until TEXT DEFAULT NULL,
    on_order_qty INTEGER DEFAULT 0,
    on_order_date TEXT DEFAULT NULL,
    on_order_notes TEXT DEFAULT '',
    last_transition_at TEXT,
    last_notified_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(variant_id) REFERENCES variants(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_stock_alert_state_state ON stock_alert_state(state);
CREATE INDEX IF NOT EXISTS idx_stock_alert_state_prod ON stock_alert_state(product_id);

CREATE TABLE IF NOT EXISTS stock_alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    stock_at_transition INTEGER NOT NULL,
    effective_level INTEGER NOT NULL,
    action_trigger TEXT NOT NULL, -- 'SALE', 'RETURN', 'ADJUSTMENT', 'PURCHASE', 'MANUAL_LEVEL_CHANGE'
    reference TEXT DEFAULT '',
    user_id INTEGER DEFAULT 0,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_log_variant ON stock_alert_log(variant_id);
CREATE INDEX IF NOT EXISTS idx_alert_log_time ON stock_alert_log(timestamp);

CREATE TABLE IF NOT EXISTS sales_daily_by_variant (
    date TEXT NOT NULL,
    variant_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    units_sold INTEGER NOT NULL DEFAULT 0,
    gross_revenue REAL NOT NULL DEFAULT 0.0,
    cost_total REAL NOT NULL DEFAULT 0.0,
    units_returned INTEGER NOT NULL DEFAULT 0,
    net_profit REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (date, variant_id)
);
CREATE INDEX IF NOT EXISTS idx_sales_daily_cat ON sales_daily_by_variant(category, date);
CREATE INDEX IF NOT EXISTS idx_sales_daily_brand ON sales_daily_by_variant(brand, date);
CREATE INDEX IF NOT EXISTS idx_sales_daily_prod ON sales_daily_by_variant(product_id, date);
```

---

## 2. Three-Level Inheritance Rule
For any variant, the effective alert level and reorder qty are determined as follows:
```
1. Item Level: variant.low_stock_level (if NOT NULL)
2. Category Level: lookup_lists.default_low_stock_level WHERE list_key = 'category' AND label = product.category (if NOT NULL)
3. Global Default: settings key:
   - Phones: 'global_default_phone_low_stock' (Seed: 2)
   - Accessories: 'global_default_accessory_low_stock' (Seed: 5)
   - Spare Parts: 'global_default_spare_part_low_stock' (Seed: 3)
```
If `variant.alert_off == 1`, state is forced to `OFF`.

---

## 3. Alert State Machine & Transition Rules
- **State Definition**:
  - `OK`: `stock > effective_level`
  - `LOW`: `stock <= effective_level AND stock > 0`
  - `OUT`: `stock == 0`
  - `OFF`: `alert_off == 1` OR `product.is_archived == 1` OR `variant.is_archived == 1`
- **Worsening Transitions** (generates notification & toast event):
  - `OK` -> `LOW`
  - `OK` -> `OUT`
  - `LOW` -> `OUT`
- **Resolution Transitions** (clears notification):
  - `OUT` -> `LOW`
  - `OUT` -> `OK`
  - `LOW` -> `OK`
- **Snooze & On Order**:
  - `snoozed_until > now` suppresses bell count and active alert displays
  - `on_order_qty > 0` marks badge as "On order" with expected date and quantity

---

## 4. Aggregate Deltas & Performance Contract
- Transactions modifying `sale_items` or `return_items` execute atomic upsert queries into `sales_daily_by_variant` in O(1) time.
- Stock changes recalculate ONLY the modified `variant_id` in O(1) time (typically <= 1.5ms).
- Cached counters for bell (`SELECT COUNT(*) FROM stock_alert_state WHERE state IN ('LOW', 'OUT') AND (snoozed_until IS NULL OR snoozed_until < datetime('now'))`) execute in <= 2ms using index.

---

## 5. Screen & Permission Map
| Feature / Screen | Admin Access | Employee Access |
|---|---|---|
| Top-bar Bell & Urgent Drawer | Full list + Snooze / Mark Ordered | Urgent list (Item, Stock, Level only; no costs) |
| Dashboard Alert Cards | Out of stock & Low stock counts + Top 5 urgent | Out of stock & Low stock counts + Top 5 urgent |
| Inventory Filter Chips & Row Badges | All Badges, inline level edit, bulk actions | All Badges, read-only (cannot edit levels) |
| Low Stock & Reorder Screen | Full screen + Costs, Suppliers, Suggestions, Purchase Drafts | Read-only item & stock list; no costs, no suppliers |
| Top Sellers Screen (`/reports/top-sellers`) | Full screen: Units, Revenue, Profit, Margin %, Comparisons | Forbidden (403) |
| POS Top Sellers Tab | Full access | Units sold only (No revenue or profit displayed) |
| Item Form Alert Controls | Set/change alert level, reorder qty, off toggle | Read-only |
