# MOBILE & ACCESSORIES ERP — Event-Driven Smart Low-Stock Alert & Reorder Engine
import math, json
from datetime import datetime, timedelta
import db, auth, lookups

# ═══════════════════════════════════════════════════════════
# 1. THREE-LEVEL INHERITANCE RESOLUTION
# ═══════════════════════════════════════════════════════════

def _val(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        val = row[key]
        return val if val is not None else default
    except (IndexError, KeyError, TypeError):
        return default

def get_global_setting(key, default_val):
    row = db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row and row["value"] is not None else str(default_val)

def get_effective_alert_config(product, variant):
    """
    Three-level inheritance:
    1. Variant explicit level (if NOT NULL)
    2. Category default level from lookup_lists (if NOT NULL)
    3. Global setting default based on item_type (Phones 2, Accessories 5, Spare Parts 3)
    """
    itype = (_val(product, "item_type") or "PHONE").upper()
    cat_name = _val(product, "category") or ""
    
    # 1. Global Defaults
    if itype == "PHONE":
        g_level = int(get_global_setting("global_default_phone_low_stock", 2))
        g_reorder = int(get_global_setting("global_default_phone_reorder_qty", 5))
    elif itype == "SPARE_PART":
        g_level = int(get_global_setting("global_default_spare_part_low_stock", 3))
        g_reorder = int(get_global_setting("global_default_spare_part_reorder_qty", 10))
    else: # ACCESSORY / SERIAL
        g_level = int(get_global_setting("global_default_accessory_low_stock", 5))
        g_reorder = int(get_global_setting("global_default_accessory_reorder_qty", 20))

    # 2. Category Defaults
    cat_level = None
    cat_reorder = None
    if cat_name:
        crow = db.query_one("""
            SELECT default_low_stock_level, default_reorder_qty 
            FROM lookup_lists 
            WHERE list_key = 'category' AND label = ? AND is_active = 1
        """, (cat_name,))
        if crow:
            cat_level = crow["default_low_stock_level"]
            cat_reorder = crow["default_reorder_qty"]

    # 3. Item Level Override
    v_level = _val(variant, "low_stock_level")
    v_reorder = _val(variant, "reorder_qty")
    alert_off = bool(_val(variant, "alert_off", 0))

    if v_level is not None:
        effective_level = int(v_level)
        inherited_from = "custom"
    elif cat_level is not None:
        effective_level = int(cat_level)
        inherited_from = f"category:{cat_name}"
    else:
        effective_level = g_level
        inherited_from = "global"

    if v_reorder is not None:
        effective_reorder = int(v_reorder)
    elif cat_reorder is not None:
        effective_reorder = int(cat_reorder)
    else:
        effective_reorder = g_reorder

    return {
        "effective_level": effective_level,
        "reorder_qty": effective_reorder,
        "inherited_from": inherited_from,
        "alert_off": alert_off,
        "category_default": cat_level,
        "category_reorder": cat_reorder,
        "global_default": g_level,
        "global_reorder": g_reorder
    }

# ═══════════════════════════════════════════════════════════
# 2. SINGLE FUNCTION STOCK STATE COMPUTATION
# ═══════════════════════════════════════════════════════════

def compute_variant_stock(cx_or_none, variant_id, item_type):
    """
    Computes stock count:
    - Phones/Serial: units with status = 'IN_STOCK' only
    - Accessories/Parts: stock_quantity on variants
    """
    if item_type in ("PHONE", "SERIAL"):
        if cx_or_none:
            cur = cx_or_none.execute("SELECT COUNT(*) AS c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (variant_id,))
            row = cur.fetchone()
            return row["c"] if row else 0
        else:
            row = db.query_one("SELECT COUNT(*) AS c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (variant_id,))
            return row["c"] if row else 0
    else:
        if cx_or_none:
            cur = cx_or_none.execute("SELECT stock_quantity FROM variants WHERE id = ?", (variant_id,))
            row = cur.fetchone()
            return row["stock_quantity"] if row else 0
        else:
            row = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (variant_id,))
            return row["stock_quantity"] if row else 0

def get_variant_alert_state(variant_id):
    """Retrieves or computes live alert state for a single variant."""
    row = db.query_one("""
        SELECT v.*, p.name AS model_name, p.brand, p.category, p.item_type, p.is_archived AS prod_archived,
               s.state, s.snoozed_until, s.on_order_qty, s.on_order_date, s.on_order_notes,
               s.last_transition_at, s.last_notified_at
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN stock_alert_state s ON v.id = s.variant_id
        WHERE v.id = ?
    """, (variant_id,))
    if not row:
        return None

    cfg = get_effective_alert_config(row, row)
    stock = compute_variant_stock(None, variant_id, row["item_type"])
    
    # State evaluation
    is_archived = bool(row["is_archived"] or row["prod_archived"])
    if is_archived or cfg["alert_off"]:
        state = "OFF"
    elif stock == 0:
        state = "OUT"
    elif stock <= cfg["effective_level"]:
        state = "LOW"
    else:
        state = "OK"

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_snoozed = bool(row["snoozed_until"] and row["snoozed_until"] > now_iso)
    is_on_order = bool(row["on_order_qty"] and row["on_order_qty"] > 0)

    return {
        "variant_id": variant_id,
        "product_id": row["product_id"],
        "brand": row["brand"],
        "model_name": row["model_name"],
        "category": row["category"],
        "item_type": row["item_type"],
        "specs": f"{row['ram']} {row['storage']} {row['color']}".strip(),
        "current_stock": stock,
        "effective_level": cfg["effective_level"],
        "reorder_qty": cfg["reorder_qty"],
        "inherited_from": cfg["inherited_from"],
        "alert_off": cfg["alert_off"],
        "state": state,
        "is_snoozed": is_snoozed,
        "snoozed_until": row["snoozed_until"],
        "is_on_order": is_on_order,
        "on_order_qty": row["on_order_qty"] or 0,
        "on_order_date": row["on_order_date"] or "",
        "on_order_notes": row["on_order_notes"] or "",
        "last_transition_at": row["last_transition_at"],
        "last_notified_at": row["last_notified_at"]
    }

# ═══════════════════════════════════════════════════════════
# 3. EVENT-DRIVEN TRANSITION EVALUATOR (INSIDE SAME TRANSACTION)
# ═══════════════════════════════════════════════════════════

def evaluate_stock_transitions(cx, variant_ids, user_id=0, action_trigger="STOCK_CHANGE", reference=""):
    """
    Evaluates stock state transitions inside an active transaction.
    Only affected variant_ids are re-evaluated (O(lines)).
    Returns list of worsening transition notifications for UI toast / bell.
    """
    if not variant_ids:
        return []

    if cx is None:
        with db.get_connection() as conn:
            return evaluate_stock_transitions(conn, variant_ids, user_id, action_trigger, reference)

    unique_vids = list(set([int(v) for v in variant_ids if v]))
    if not unique_vids:
        return []

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    notifications = []

    # Fetch variant details
    placeholders = ",".join("?" for _ in unique_vids)
    cur = cx.execute(f"""
        SELECT v.*, p.name AS model_name, p.brand, p.category, p.item_type, p.is_archived AS prod_archived,
               s.state AS prev_state, s.effective_level AS prev_level, s.snoozed_until, s.on_order_qty,
               s.on_order_date, s.on_order_notes, s.last_transition_at, s.last_notified_at
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN stock_alert_state s ON v.id = s.variant_id
        WHERE v.id IN ({placeholders})
    """, unique_vids)
    rows = cur.fetchall()

    for r in rows:
        vid = r["id"]
        pid = r["product_id"]
        cfg = get_effective_alert_config(r, r)
        stock = compute_variant_stock(cx, vid, r["item_type"])
        
        is_archived = bool(r["is_archived"] or r["prod_archived"])
        if is_archived or cfg["alert_off"]:
            new_state = "OFF"
        elif stock == 0:
            new_state = "OUT"
        elif stock <= cfg["effective_level"]:
            new_state = "LOW"
        else:
            new_state = "OK"

        prev_state = _val(r, "prev_state") or "OK"

        # Check for worsening transitions
        is_worsening = (
            (prev_state == "OK" and new_state in ("LOW", "OUT")) or
            (prev_state == "LOW" and new_state == "OUT")
        )

        is_resolving = (
            (prev_state in ("LOW", "OUT") and new_state == "OK") or
            (prev_state == "OUT" and new_state == "LOW")
        )

        last_trans = now if (new_state != prev_state) else (_val(r, "last_transition_at") or now)
        last_notif = now if is_worsening else None

        # Upsert stock_alert_state
        cx.execute("""
            INSERT INTO stock_alert_state (
                variant_id, product_id, current_stock, effective_level, state,
                snoozed_until, on_order_qty, on_order_date, on_order_notes,
                last_transition_at, last_notified_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(variant_id) DO UPDATE SET
                current_stock = excluded.current_stock,
                effective_level = excluded.effective_level,
                state = excluded.state,
                last_transition_at = CASE WHEN excluded.state != stock_alert_state.state THEN excluded.last_transition_at ELSE stock_alert_state.last_transition_at END,
                last_notified_at = CASE WHEN excluded.last_notified_at IS NOT NULL THEN excluded.last_notified_at ELSE stock_alert_state.last_notified_at END,
                updated_at = excluded.updated_at
        """, (vid, pid, stock, cfg["effective_level"], new_state,
              r["snoozed_until"], r["on_order_qty"] or 0, r["on_order_date"] or None, r["on_order_notes"] or "",
              last_trans, last_notif, now))

        # Log transition in stock_alert_log
        if new_state != prev_state:
            cx.execute("""
                INSERT INTO stock_alert_log (
                    variant_id, product_id, from_state, to_state, stock_at_transition,
                    effective_level, action_trigger, reference, user_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (vid, pid, prev_state, new_state, stock, cfg["effective_level"],
                  action_trigger, reference, user_id, now))

        if is_worsening:
            specs = f"{r['ram']} {r['storage']} {r['color']}".strip()
            item_display = f"{r['brand']} {r['model_name']}" + (f" ({specs})" if specs else "")
            notifications.append({
                "variant_id": vid,
                "product_id": pid,
                "item_name": item_display,
                "state": new_state,
                "stock": stock,
                "level": cfg["effective_level"],
                "message": f"{item_display} — only {stock} left! (Alert at {cfg['effective_level']})" if new_state == "LOW" else f"{item_display} — OUT OF STOCK!"
            })

    return notifications

# ═══════════════════════════════════════════════════════════
# 4. BELL & DASHBOARD AGGREGATE COUNTERS (INDEXED <= 2ms)
# ═══════════════════════════════════════════════════════════

def get_alert_summary():
    """
    Returns instant cached counts for the top-bar bell and dashboard.
    Suppresses snoozed items where snoozed_until > now.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = db.query_one("""
        SELECT 
            SUM(CASE WHEN state = 'OUT' AND (snoozed_until IS NULL OR snoozed_until <= ?) THEN 1 ELSE 0 END) AS out_count,
            SUM(CASE WHEN state = 'LOW' AND (snoozed_until IS NULL OR snoozed_until <= ?) THEN 1 ELSE 0 END) AS low_count,
            SUM(CASE WHEN on_order_qty > 0 THEN 1 ELSE 0 END) AS on_order_count
        FROM stock_alert_state
    """, (now, now))
    
    out_c = int(row["out_count"] or 0) if row else 0
    low_c = int(row["low_count"] or 0) if row else 0
    order_c = int(row["on_order_count"] or 0) if row else 0

    return {
        "out_count": out_c,
        "low_count": low_c,
        "total_urgent": out_c + low_c,
        "on_order_count": order_c
    }

def get_urgent_alert_items(limit=15):
    """
    Returns urgent items for the bell panel and dashboard:
    OUT first, then lowest stock relative to effective level.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return db.query_all("""
        SELECT s.*, v.ram, v.storage, v.color, v.retail_price, v.wholesale_price,
               p.brand, p.name AS model_name, p.category, p.item_type
        FROM stock_alert_state s
        JOIN variants v ON s.variant_id = v.id
        JOIN products p ON s.product_id = p.id
        WHERE s.state IN ('LOW', 'OUT') 
          AND (s.snoozed_until IS NULL OR s.snoozed_until <= ?)
          AND v.is_archived = 0 AND p.is_archived = 0
        ORDER BY CASE WHEN s.state = 'OUT' THEN 0 ELSE 1 END ASC,
                 s.current_stock ASC,
                 s.effective_level DESC
        LIMIT ?
    """, (now, limit))

# ═══════════════════════════════════════════════════════════
# 5. SNOOZE, MARK AS ORDERED & RECEIPT CLEARING
# ═══════════════════════════════════════════════════════════

def snooze_alert(variant_id, days=1, user_id=0, username="Admin"):
    """Snoozes alert for 1, 3, or 7 days."""
    snooze_dt = (datetime.now() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("""
        UPDATE stock_alert_state 
        SET snoozed_until = ?, updated_at = ?
        WHERE variant_id = ?
    """, (snooze_dt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), variant_id))
    
    auth.log_audit(user_id, username, "SNOOZE_ALERT", "stock_alert_state", str(variant_id), "", f"Snoozed for {days} days until {snooze_dt}")
    return {"success": True, "snoozed_until": snooze_dt}

def cancel_snooze(variant_id, user_id=0, username="Admin"):
    """Unsnoozes alert immediately."""
    db.execute("""
        UPDATE stock_alert_state 
        SET snoozed_until = NULL, updated_at = ?
        WHERE variant_id = ?
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), variant_id))
    return {"success": True}

def mark_as_ordered(variant_id, qty, expected_date="", notes="", user_id=0, username="Admin"):
    """Marks variant as on-order with supplier quantity and expected arrival date."""
    db.execute("""
        UPDATE stock_alert_state 
        SET on_order_qty = ?, on_order_date = ?, on_order_notes = ?, updated_at = ?
        WHERE variant_id = ?
    """, (int(qty), expected_date.strip() or None, notes.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), variant_id))
    
    auth.log_audit(user_id, username, "MARK_ORDERED", "stock_alert_state", str(variant_id), "", f"Marked on order qty: {qty}")
    return {"success": True}

def clear_on_order_on_receipt(cx, variant_id, qty_received):
    """Decrements or clears on_order_qty when goods arrive in purchases."""
    cx.execute("""
        UPDATE stock_alert_state 
        SET on_order_qty = MAX(0, on_order_qty - ?),
            on_order_date = CASE WHEN on_order_qty - ? <= 0 THEN NULL ELSE on_order_date END,
            updated_at = ?
        WHERE variant_id = ?
    """, (int(qty_received), int(qty_received), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), variant_id))

# ═══════════════════════════════════════════════════════════
# 6. BULK MANAGEMENT & CATEGORY DEFAULTS
# ═══════════════════════════════════════════════════════════

def bulk_set_alert_level(variant_ids, level=None, reorder_qty=None, alert_off=0, user_id=0, username="Admin"):
    """
    Sets alert level or resets to category default for multiple variants in 1 transaction.
    level=None means 'Use Category Default' (sets variant.low_stock_level = NULL).
    """
    if not variant_ids:
        return {"success": False, "count": 0}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        for vid in variant_ids:
            cx.execute("""
                UPDATE variants 
                SET low_stock_level = ?, reorder_qty = ?, alert_off = ?, updated_at = ?
                WHERE id = ?
            """, (level, reorder_qty, int(alert_off), now, vid))
        
        evaluate_stock_transitions(cx, variant_ids, user_id=user_id, action_trigger="BULK_LEVEL_UPDATE")

    auth.log_audit(user_id, username, "BULK_SET_ALERT_LEVEL", "variants", f"{len(variant_ids)} variants", "", f"Level: {level}, Reorder: {reorder_qty}, Off: {alert_off}")
    return {"success": True, "count": len(variant_ids), "updated_count": len(variant_ids)}

def update_category_alert_defaults(category_id, default_low_stock, default_reorder_qty, user_id=0, username="Admin"):
    """
    Updates category default low stock and reorder qty in lookup_lists.
    Instantly re-evaluates all variants inheriting this category default!
    """
    cat = db.query_one("SELECT * FROM lookup_lists WHERE id = ? AND list_key = 'category'", (category_id,))
    if not cat:
        return {"success": False, "error": "Category not found"}

    lev = int(default_low_stock) if default_low_stock is not None else None
    reqty = int(default_reorder_qty) if default_reorder_qty is not None else None

    with db.transaction() as cx:
        cx.execute("""
            UPDATE lookup_lists 
            SET default_low_stock_level = ?, default_reorder_qty = ?
            WHERE id = ?
        """, (lev, reqty, category_id))

        # Find all variants in this category where low_stock_level is NULL (inheriting)
        cur = cx.execute("""
            SELECT v.id 
            FROM variants v
            JOIN products p ON v.product_id = p.id
            WHERE p.category = ? AND v.low_stock_level IS NULL AND v.is_archived = 0
        """, (cat["label"],))
        inheriting_vids = [r["id"] for r in cur.fetchall()]

        if inheriting_vids:
            evaluate_stock_transitions(cx, inheriting_vids, user_id=user_id, action_trigger="CATEGORY_DEFAULT_CHANGE")

    auth.log_audit(user_id, username, "UPDATE_CATEGORY_ALERT_DEFAULTS", "lookup_lists", str(category_id),
                   f"Old: {cat['default_low_stock_level']}/{cat['default_reorder_qty']}",
                   f"New: {lev}/{reqty} (Updated {len(inheriting_vids)} inheriting items)")
    return {"success": True, "updated_items_count": len(inheriting_vids)}

# ═══════════════════════════════════════════════════════════
# 7. REORDER INTELLIGENCE FORMULA
# ═══════════════════════════════════════════════════════════

def get_reorder_intelligence(variant_id, sales_window_days=30, target_cover_days=14):
    """
    Suggested reorder qty:
    formula: max(reorder_qty, ceil(avg_daily_sales * target_cover_days) - in_stock - on_order)
    Never negative.
    Days of stock left: in_stock / avg_daily_sales.
    """
    st = get_variant_alert_state(variant_id)
    if not st:
        return None

    # Calculate average daily sales over window
    window_start = (datetime.now() - timedelta(days=int(sales_window_days))).strftime("%Y-%m-%d")
    s_row = db.query_one("""
        SELECT COALESCE(SUM(units_sold - units_returned), 0) AS net_units
        FROM sales_daily_by_variant
        WHERE variant_id = ? AND date >= ?
    """, (variant_id, window_start))
    
    net_units = max(0, s_row["net_units"] if s_row else 0)
    avg_daily_sales = net_units / float(sales_window_days)

    stock = st["current_stock"]
    on_order = st["on_order_qty"]
    level = st["effective_level"]
    default_reorder = st["reorder_qty"]

    if avg_daily_sales > 0:
        days_left = round(stock / avg_daily_sales, 1)
        needed_for_cover = math.ceil(avg_daily_sales * float(target_cover_days))
        suggested = max(default_reorder, needed_for_cover - stock - on_order)
    else:
        days_left = None
        suggested = max(default_reorder, (2 * level) - stock - on_order)

    suggested = max(0, suggested)

    # Last supplier and cost
    last_sup = db.query_one("""
        SELECT p.supplier_name, s.phone AS supplier_phone, pi.unit_cost, p.purchase_date
        FROM purchase_items pi
        JOIN purchases p ON pi.purchase_id = p.id
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        WHERE pi.variant_id = ?
        ORDER BY pi.id DESC LIMIT 1
    """, (variant_id,))

    return {
        "variant_id": variant_id,
        "sold_last_window": net_units,
        "avg_daily_sales": round(avg_daily_sales, 2),
        "days_stock_left": days_left,
        "suggested_reorder_qty": suggested,
        "target_cover_days": target_cover_days,
        "sales_window_days": sales_window_days,
        "last_supplier_name": last_sup["supplier_name"] if last_sup else "N/A",
        "last_supplier_phone": last_sup["supplier_phone"] if last_sup else "",
        "last_cost": last_sup["unit_cost"] if last_sup else 0,
        "last_purchase_date": last_sup["purchase_date"] if last_sup else ""
    }

# ═══════════════════════════════════════════════════════════
# 8. STARTUP DRIFT SELF-CHECK & RECOMPUTATION
# ═══════════════════════════════════════════════════════════

def recompute_all_alerts_self_check():
    """
    On-start self-check:
    Recomputes entire catalog from scratch, fixes any drift, and logs summary.
    """
    variants = db.query_all("SELECT id FROM variants WHERE is_archived = 0")
    if not variants:
        return {"total_checked": 0, "drift_fixed": 0}

    all_vids = [v["id"] for v in variants]
    with db.transaction() as cx:
        evaluate_stock_transitions(cx, all_vids, action_trigger="STARTUP_SELF_CHECK")

    summary = get_alert_summary()
    print(f"[ALERTS ENGINE] Self-check complete: {len(all_vids)} variants verified. Out: {summary['out_count']}, Low: {summary['low_count']}, On Order: {summary['on_order_count']}")
    return summary
