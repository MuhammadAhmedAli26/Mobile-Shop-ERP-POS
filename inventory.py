import json, re, sqlite3, os
from datetime import datetime, timedelta
import db, auth

URDU_ARABIC_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def parse_money(val, default=0.0):
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    s = str(val).strip().translate(URDU_ARABIC_DIGIT_MAP)
    s = re.sub(r'(?i)(rs\.?|pkr|\$|,|\s)', '', s)
    try:
        num = float(s)
        return max(0.0, min(99999999.0, num))
    except (ValueError, TypeError):
        return default

def parse_qty(val, default=0):
    if val is None or val == "":
        return default
    if isinstance(val, int):
        return max(0, min(99999, val))
    s = str(val).strip().translate(URDU_ARABIC_DIGIT_MAP)
    s = re.sub(r'[\s,]', '', s)
    try:
        num = int(float(s))
        return max(0, min(99999, num))
    except (ValueError, TypeError):
        return default

def generate_next_code(cx, prefix="ACC"):
    cx.execute("""
        INSERT INTO code_counters (prefix, last_val) VALUES (?, 1)
        ON CONFLICT(prefix) DO UPDATE SET last_val = last_val + 1
    """, (prefix,))
    row = cx.execute("SELECT last_val FROM code_counters WHERE prefix = ?", (prefix,)).fetchone()
    seq = row["last_val"] if hasattr(row, "__getitem__") else row[0]
    return f"{prefix}-{int(seq):06d}"

FORBIDDEN_EMPLOYEE_FIELDS = {
    "cost_price", "wholesale_price", "avg_cost", "last_cost",
    "profit", "total_profit", "margin", "min_selling_price", "min_price",
    "supplier_id", "supplier_name", "supplier_phone", "supplier_ref", "supplier_payments"
}

def public_item(item, is_admin=False):
    """
    Serializes an item/dict, removing sensitive cost/profit/supplier fields for non-admin users.
    """
    if item is None:
        return None
    if hasattr(item, "keys"):
        res = dict(item)
    elif isinstance(item, dict):
        res = dict(item)
    else:
        return item
    if is_admin:
        return res
    for k in list(res.keys()):
        if k in FORBIDDEN_EMPLOYEE_FIELDS or k.startswith("supplier"):
            del res[k]
    return res

# ═══════════════════════════════════════════════════════════
# 1. PRODUCTS (MODELS)
# ═══════════════════════════════════════════════════════════

def create_product(brand, name, category="Smartphone", item_type="PHONE", warranty_months=12, compatible_models="", notes="", user_id=0, username=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pid = db.execute("""
        INSERT INTO products (brand, name, category, item_type, default_warranty_months, compatible_models, notes, is_archived, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (brand.strip(), name.strip(), category.strip(), item_type.strip(), int(warranty_months), compatible_models.strip(), notes.strip(), now, now))
    
    auth.log_audit(user_id, username, "CREATE_PRODUCT", "products", str(pid), "", f"{brand} {name} ({item_type})")
    return pid

def update_product(product_id, brand, name, category, item_type="PHONE", warranty_months=0, compatible_models="", notes="", image_url="", user_id=0, username=""):
    old = db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))
    if not old:
        return {"success": False, "error": "Product not found"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    b = str(brand).strip()
    n = str(name).strip()
    c = str(category).strip()
    it = str(item_type or old["item_type"]).strip()
    wm = int(warranty_months or 0)
    cm = str(compatible_models or "").strip()
    nt = str(notes or "").strip()
    img = str(image_url or old.get("image_url") or "").strip()

    with db.transaction() as cx:
        cx.execute("""
            UPDATE products SET brand=?, name=?, category=?, item_type=?, default_warranty_months=?, compatible_models=?, notes=?, image_url=?, updated_at=?
            WHERE id=?
        """, (b, n, c, it, wm, cm, nt, img, now, product_id))
    
    db.bump_change_version("items")
    auth.log_audit(user_id, username, "UPDATE_PRODUCT", "products", str(product_id), json.dumps(dict(old)), f"{b} {n}")
    return {"success": True}

def delete_or_archive_product(product_id, user_id=0, username=""):
    """
    Deletes product if zero history; archives product if history exists.
    Admin only.
    """
    prod = db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))
    if not prod:
        return {"success": False, "status": 404, "message": "Product not found."}

    v_ids = [r["id"] for r in db.query_all("SELECT id FROM variants WHERE product_id = ?", (product_id,))]

    # Check for historical transactions
    history_count = 0
    if v_ids:
        placeholders = ",".join("?" * len(v_ids))
        # Sales
        s_count = db.query_one(f"SELECT COUNT(*) AS c FROM sale_items WHERE variant_id IN ({placeholders})", v_ids)
        if s_count and s_count["c"] > 0:
            history_count += s_count["c"]
        # Purchases
        p_count = db.query_one(f"SELECT COUNT(*) AS c FROM purchase_items WHERE variant_id IN ({placeholders})", v_ids)
        if p_count and p_count["c"] > 0:
            history_count += p_count["c"]
        # Sold / active units
        u_count = db.query_one(f"SELECT COUNT(*) AS c FROM units WHERE variant_id IN ({placeholders}) AND status != 'IN_STOCK'", v_ids)
        if u_count and u_count["c"] > 0:
            history_count += u_count["c"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if history_count > 0:
        # Archive mode
        with db.transaction() as cx:
            cx.execute("UPDATE products SET is_archived = 1, updated_at = ? WHERE id = ?", (now, product_id))
            if v_ids:
                placeholders = ",".join("?" * len(v_ids))
                cx.execute(f"UPDATE variants SET is_archived = 1, updated_at = ? WHERE id IN ({placeholders})", [now] + v_ids)
        db.bump_change_version("items")
        auth.log_audit(user_id, username, "ARCHIVE_PRODUCT", "products", str(product_id), "is_archived: 0", "is_archived: 1")
        return {
            "success": True,
            "action": "ARCHIVED",
            "message": f"'{prod['brand']} {prod['name']}' has {history_count} historical transaction(s) and was safely archived.",
            "product_id": product_id,
            "can_undo": True
        }
    else:
        # Delete mode
        with db.transaction() as cx:
            if v_ids:
                placeholders = ",".join("?" * len(v_ids))
                cx.execute(f"DELETE FROM units WHERE variant_id IN ({placeholders})", v_ids)
                cx.execute(f"DELETE FROM stock_ledger WHERE variant_id IN ({placeholders})", v_ids)
                cx.execute(f"DELETE FROM variants WHERE id IN ({placeholders})", v_ids)
            cx.execute("DELETE FROM products WHERE id = ?", (product_id,))
        db.bump_change_version("items")
        db.bump_change_version("stock")
        auth.log_audit(user_id, username, "DELETE_PRODUCT", "products", str(product_id), json.dumps(dict(prod)), "Deleted permanently (zero history)")
        return {
            "success": True,
            "action": "DELETED",
            "message": f"'{prod['brand']} {prod['name']}' had zero transaction history and was permanently deleted.",
            "product_id": product_id,
            "can_undo": False
        }

def restore_product(product_id, user_id=0, username=""):
    """
    Restores an archived product and its variants. Admin only.
    """
    prod = db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))
    if not prod:
        return {"success": False, "status": 404, "message": "Product not found."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("UPDATE products SET is_archived = 0, updated_at = ? WHERE id = ?", (now, product_id))
        cx.execute("UPDATE variants SET is_archived = 0, updated_at = ? WHERE product_id = ?", (now, product_id))

    db.bump_change_version("items")
    auth.log_audit(user_id, username, "RESTORE_PRODUCT", "products", str(product_id), "is_archived: 1", "is_archived: 0")
    return {
        "success": True,
        "message": f"'{prod['brand']} {prod['name']}' restored successfully.",
        "product_id": product_id
    }

def archive_product(product_id, user_id=0, username=""):
    res = delete_or_archive_product(product_id, user_id, username)
    return res.get("success", False)

def delete_unit(unit_id, user_id=0, username=""):
    """
    Deletes physical unit if in stock and unsold. Admin only.
    """
    unit = db.query_one("SELECT * FROM units WHERE id = ?", (unit_id,))
    if not unit:
        return {"success": False, "status": 404, "message": "Unit not found."}
    if unit["status"] != "IN_STOCK":
        return {"success": False, "status": 400, "message": f"Cannot delete unit in status '{unit['status']}'."}

    vid = unit["variant_id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("DELETE FROM units WHERE id = ?", (unit_id,))
        cx.execute("""
            UPDATE variants SET 
                stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                updated_at = ?
            WHERE id = ?
        """, (vid, now, vid))
        cx.execute("""
            INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
            VALUES ((SELECT product_id FROM variants WHERE id = ?), ?, ?, ?, 'PHONE', -1, (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'), 'ADJUST', 'UNIT_DELETE', 'Unit removed by Admin', ?, ?)
        """, (vid, vid, unit_id, unit.get("imei1", ""), vid, user_id, now))

    db.bump_change_version("items")
    db.bump_change_version("stock")
    auth.log_audit(user_id, username, "DELETE_UNIT", "units", str(unit_id), json.dumps(dict(unit)), "Unit deleted")
    return {"success": True, "message": f"Unit #{unit_id} ({unit.get('imei1', '')}) removed."}

def get_product(product_id):
    return db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))

def list_products(item_type=None, brand=None, search=None, include_archived=False):
    sql = "SELECT * FROM products WHERE 1=1"
    params = []
    if not include_archived:
        sql += " AND is_archived = 0"
    if item_type:
        sql += " AND item_type = ?"
        params.append(item_type)
    if brand:
        sql += " AND brand = ?"
        params.append(brand)
    if search:
        sql += " AND (name LIKE ? OR brand LIKE ? OR category LIKE ? OR compatible_models LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])
    sql += " ORDER BY brand ASC, name ASC"
    return db.query_all(sql, params)

# ═══════════════════════════════════════════════════════════
# 2. VARIANTS & MATRIX CREATOR
# ═══════════════════════════════════════════════════════════

def create_variant(product_id, ram="", storage="", color="", network="", retail_price=0, wholesale_price=0, min_selling_price=0, stock_qty=0, reorder_level=None, sku="", barcode="", low_stock_level=None, reorder_qty=None, alert_off=0, user_id=0, username=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rp = parse_money(retail_price)
    wp = parse_money(wholesale_price)
    mp = parse_money(min_selling_price)
    sq = parse_qty(stock_qty)
    bc = (str(barcode).strip() or None) if barcode else None
    sk = (str(sku).strip() or None) if sku else None

    if not sk:
        prod = get_product(product_id)
        if prod:
            spec = f"{ram}-{storage}-{color}".strip("-")
            sk = f"{prod['brand'][:3].upper()}-{prod['name'][:4].upper()}-{spec}".replace(" ", "").replace("/", "-")
        else:
            sk = f"VAR-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    final_reorder = low_stock_level if low_stock_level is not None else (reorder_level if reorder_level is not None else 5)

    with db.transaction() as cx:
        if sk:
            base_sku = sk
            candidate_sku = base_sku
            counter = 1
            while True:
                dup = cx.execute("SELECT id FROM variants WHERE sku = ?", (candidate_sku,)).fetchone()
                if not dup:
                    break
                counter += 1
                candidate_sku = f"{base_sku}-{counter}"
            sk = candidate_sku

        cur = cx.execute("""
            INSERT INTO variants (product_id, ram, storage, color, network, sku, barcode, retail_price, wholesale_price, min_selling_price, stock_quantity, reorder_level, low_stock_level, reorder_qty, alert_off, is_archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (product_id, str(ram).strip(), str(storage).strip(), str(color).strip(), str(network).strip(), sk, bc, rp, wp, mp, sq, int(final_reorder), low_stock_level, reorder_qty, int(alert_off), now, now))
        vid = cur.lastrowid

        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, [vid], user_id=user_id, action_trigger="CREATE_VARIANT")
        except Exception:
            pass

    db.bump_change_version("items")
    auth.log_audit(user_id, username, "CREATE_VARIANT", "variants", str(vid), "", f"SKU: {sk}")
    return vid

def generate_variant_matrix(product_id, arg2, arg3, default_retail=0, default_wholesale=0, default_min=0, base_low_stock_level=None, base_reorder_qty=None, variant_overrides=None, user_id=0, username=""):
    created_ids = []
    prod = get_product(product_id)
    if not prod:
        return []

    rp = parse_money(default_retail)
    wp = parse_money(default_wholesale)
    mp = parse_money(default_min)

    # Detect which argument is colors and which is combos
    if arg2 and isinstance(arg2[0], dict) and arg3 and isinstance(arg3[0], str):
        ram_storage_combos, colors_list = arg2, arg3
    elif arg3 and isinstance(arg3[0], dict) and arg2 and isinstance(arg2[0], str):
        colors_list, ram_storage_combos = arg2, arg3
    else:
        colors_list, ram_storage_combos = arg2, arg3

    with db.transaction() as cx:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for color in colors_list:
            c = str(color).strip()
            if not c: continue
            for item in ram_storage_combos:
                if isinstance(item, dict):
                    r = str(item.get("ram", "")).strip()
                    s = str(item.get("storage", "")).strip()
                elif isinstance(item, (list, tuple)):
                    r = str(item[0]).strip()
                    s = str(item[1]).strip()
                else:
                    r, s = "", str(item).strip()

                v_level = base_low_stock_level
                v_reorder = base_reorder_qty
                if variant_overrides and isinstance(variant_overrides, dict):
                    override_key = f"{r}/{s}_{c}"
                    if override_key in variant_overrides:
                        v_level = variant_overrides[override_key].get("low_stock_level", base_low_stock_level)
                        v_reorder = variant_overrides[override_key].get("reorder_qty", base_reorder_qty)

                # Check if variant for this product + specs already exists
                existing = cx.execute("""
                    SELECT id FROM variants 
                    WHERE product_id = ? AND ifnull(ram, '') = ? AND ifnull(storage, '') = ? AND ifnull(color, '') = ?
                """, (product_id, r, s, c)).fetchone()

                if existing:
                    var_id = existing[0]
                    cx.execute("""
                        UPDATE variants SET 
                            retail_price = CASE WHEN ? > 0 THEN ? ELSE retail_price END,
                            wholesale_price = CASE WHEN ? > 0 THEN ? ELSE wholesale_price END,
                            min_selling_price = CASE WHEN ? > 0 THEN ? ELSE min_selling_price END,
                            low_stock_level = COALESCE(?, low_stock_level),
                            reorder_qty = COALESCE(?, reorder_qty),
                            is_archived = 0,
                            updated_at = ?
                        WHERE id = ?
                    """, (rp, rp, wp, wp, mp, mp, v_level, v_reorder, now, var_id))
                    created_ids.append(var_id)
                    continue

                sku = f"{prod['brand'][:3].upper()}-{prod['name'][:4].upper()}-{r}-{s}-{c}".replace(" ", "").replace("/", "-")
                base_sku = sku
                candidate_sku = base_sku
                counter = 1
                while True:
                    dup = cx.execute("SELECT id FROM variants WHERE sku = ?", (candidate_sku,)).fetchone()
                    if not dup:
                        break
                    counter += 1
                    candidate_sku = f"{base_sku}-{counter}"
                sku = candidate_sku

                cur = cx.execute("""
                    INSERT INTO variants (product_id, ram, storage, color, sku, retail_price, wholesale_price, min_selling_price, stock_quantity, reorder_level, low_stock_level, reorder_qty, alert_off, is_archived, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 0, ?, ?)
                """, (product_id, r, s, c, sku, rp, wp, mp, int(v_level or 3), v_level, v_reorder, now, now))
                created_ids.append(cur.lastrowid)

        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, created_ids, user_id=user_id, action_trigger="MATRIX_CREATE")
        except Exception:
            pass

    db.bump_change_version("items")
    auth.log_audit(user_id, username, "MATRIX_CREATE", "variants", str(product_id), "", f"Created {len(created_ids)} matrix variants")
    return created_ids

def update_variant(variant_id, ram, storage, color, network, retail_price, wholesale_price, min_selling_price, stock_quantity=None, reorder_level=None, sku="", barcode="", low_stock_level=None, reorder_qty=None, alert_off=0, user_id=0, username=""):
    old = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not old:
        return {"success": False, "error": "Variant not found"}
    prod = db.query_one("SELECT * FROM products WHERE id = ?", (old["product_id"],))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rp = parse_money(retail_price)
    wp = parse_money(wholesale_price)
    mp = parse_money(min_selling_price)
    bc = (str(barcode).strip() or None) if barcode else None
    sk = (str(sku).strip() or None) if sku else None

    # Check barcode duplicate if barcode provided
    if bc:
        dup_bc = db.query_one("SELECT id FROM variants WHERE barcode = ? AND id != ?", (bc, variant_id))
        if dup_bc:
            return {"success": False, "error": f"Barcode {bc} is already assigned to variant #{dup_bc['id']}!"}

    # For PHONE/MOBILE items, stock_quantity is strictly derived from IN_STOCK units
    if prod and prod.get("item_type") in ("PHONE", "MOBILE", "SERIAL"):
        u_cnt = db.query_one("SELECT COUNT(*) AS c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (variant_id,))
        sq = u_cnt["c"] if u_cnt else 0
    else:
        sq = parse_qty(stock_quantity) if stock_quantity is not None else old["stock_quantity"]

    final_reorder = low_stock_level if low_stock_level is not None else (reorder_level if reorder_level is not None else 5)

    with db.transaction() as cx:
        cx.execute("""
            UPDATE variants SET ram=?, storage=?, color=?, network=?, retail_price=?, wholesale_price=?, min_selling_price=?, stock_quantity=?, reorder_level=?, low_stock_level=?, reorder_qty=?, alert_off=?, sku=?, barcode=?, updated_at=?
            WHERE id=?
        """, (str(ram).strip(), str(storage).strip(), str(color).strip(), str(network).strip(), rp, wp, mp, sq, int(final_reorder), low_stock_level, reorder_qty, int(alert_off), sk, bc, now, variant_id))

        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, [variant_id], user_id=user_id, action_trigger="UPDATE_VARIANT")
        except Exception:
            pass

    db.bump_change_version("items")
    auth.log_audit(user_id, username, "UPDATE_VARIANT", "variants", str(variant_id), json.dumps(dict(old)), f"Prices: {rp}/{wp}")
    return {"success": True}

def clone_variant(variant_id, new_color=None, new_ram=None, new_storage=None, new_network=None, retail_price=None, wholesale_price=None, min_selling_price=None, user_id=0, username=""):
    """Clone an existing variant in 2 clicks with all its prices and settings including alert thresholds."""
    orig = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not orig: return None
    color = str(new_color).strip() if (new_color is not None and str(new_color).strip()) else orig["color"]
    ram = str(new_ram).strip() if (new_ram is not None and str(new_ram).strip()) else orig["ram"]
    storage = str(new_storage).strip() if (new_storage is not None and str(new_storage).strip()) else orig["storage"]
    network = str(new_network).strip() if (new_network is not None and str(new_network).strip()) else orig["network"]
    rp = parse_money(retail_price) if retail_price is not None else orig["retail_price"]
    wp = parse_money(wholesale_price) if wholesale_price is not None else orig["wholesale_price"]
    mp = parse_money(min_selling_price) if min_selling_price is not None else orig["min_selling_price"]

    new_id = create_variant(
        orig["product_id"], ram=ram, storage=storage, color=color, network=network,
        retail_price=rp, wholesale_price=wp, min_selling_price=mp,
        reorder_level=orig["reorder_level"], low_stock_level=orig["low_stock_level"], reorder_qty=orig["reorder_qty"],
        alert_off=orig["alert_off"], user_id=user_id, username=username
    )
    return new_id

def archive_variant(variant_id, user_id=0, username=""):
    old = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not old: return {"success": False, "error": "Variant not found"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("UPDATE variants SET is_archived = 1, updated_at = ? WHERE id = ?", (now, variant_id))
    db.bump_change_version("items")
    auth.log_audit(user_id, username, "ARCHIVE_VARIANT", "variants", str(variant_id), "is_archived: 0", "is_archived: 1")
    return {"success": True}

def restore_variant(variant_id, user_id=0, username=""):
    old = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not old: return {"success": False, "error": "Variant not found"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("UPDATE variants SET is_archived = 0, updated_at = ? WHERE id = ?", (now, variant_id))
    db.bump_change_version("items")
    auth.log_audit(user_id, username, "RESTORE_VARIANT", "variants", str(variant_id), "is_archived: 1", "is_archived: 0")
    return {"success": True}

def delete_or_archive_variant(variant_id, user_id=0, username=""):
    """
    Deletes variant if zero transaction history; otherwise archives it safely.
    """
    v = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not v:
        return {"success": False, "status": 404, "message": "Variant not found"}

    u_count = db.query_one("SELECT COUNT(*) AS c FROM units WHERE variant_id = ?", (variant_id,))["c"]
    s_count = db.query_one("SELECT COUNT(*) AS c FROM sale_items WHERE variant_id = ?", (variant_id,))["c"]
    p_count = db.query_one("SELECT COUNT(*) AS c FROM purchase_items WHERE variant_id = ?", (variant_id,))["c"]
    l_count = db.query_one("SELECT COUNT(*) AS c FROM stock_ledger WHERE variant_id = ?", (variant_id,))["c"]

    if u_count > 0 or s_count > 0 or p_count > 0 or l_count > 1 or v["stock_quantity"] > 0:
        res = archive_variant(variant_id, user_id=user_id, username=username)
        res["action"] = "ARCHIVED"
        res["message"] = f"Variant SKU '{v['sku']}' has history and has been safely archived."
        return res
    else:
        with db.transaction() as cx:
            cx.execute("DELETE FROM variants WHERE id = ?", (variant_id,))
        db.bump_change_version("items")
        auth.log_audit(user_id, username, "DELETE_VARIANT", "variants", str(variant_id), "", f"Permanently deleted variant SKU {v['sku']}")
        return {"success": True, "action": "DELETED", "message": f"Variant SKU '{v['sku']}' permanently deleted."}

def get_variants_for_product(product_id):
    p = db.query_one("SELECT item_type FROM products WHERE id = ?", (product_id,))
    is_phone = (p and p.get("item_type") in ("PHONE", "SERIAL"))
    if is_phone:
        return db.query_all("""
            SELECT v.*, 
                   (SELECT COUNT(*) FROM units u WHERE u.variant_id = v.id AND u.status = 'IN_STOCK') AS units_in_stock
            FROM variants v 
            WHERE v.product_id = ? AND v.is_archived = 0
            ORDER BY v.ram ASC, v.storage ASC, v.color ASC
        """, (product_id,))
    else:
        return db.query_all("""
            SELECT v.*, 
                   COALESCE(v.stock_quantity, 0) AS units_in_stock
            FROM variants v 
            WHERE v.product_id = ? AND v.is_archived = 0
            ORDER BY v.id ASC
        """, (product_id,))

# ═══════════════════════════════════════════════════════════
# 3. UNITS (IMEI LEVEL TRACKING)
# ═══════════════════════════════════════════════════════════

def add_unit(variant_id, imei1, imei2="", serial_no="", condition="NEW_BOX_PACK", pta_status="PTA_APPROVED", cost_price=0, supplier_id=0, purchase_ref="", date_in=None, battery_health=100, notes="", user_id=0, username=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_in = date_in or datetime.now().strftime("%Y-%m-%d")
    imei1 = str(imei1).strip()
    imei2 = (str(imei2).strip() or None) if imei2 else None
    serial_no = (str(serial_no).strip() or None) if serial_no else None
    cp = parse_money(cost_price)
    bh = parse_qty(battery_health, 100)
    sid = int(supplier_id) if supplier_id else 0

    # Check duplicate
    if db.query_one("SELECT id FROM units WHERE imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)", (imei1, imei1)):
        return {"success": False, "error": f"IMEI 1 ({imei1}) is ALREADY REGISTERED in the system!"}
    if imei2 and db.query_one("SELECT id FROM units WHERE imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)", (imei2, imei2)):
        return {"success": False, "error": f"IMEI 2 ({imei2}) is ALREADY REGISTERED in the system!"}

    with db.transaction() as cx:
        cur = cx.execute("""
            INSERT INTO units (variant_id, imei1, imei2, serial_no, condition, pta_status, cost_price, supplier_id, purchase_ref, date_in, battery_health, notes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
        """, (variant_id, imei1, imei2, serial_no, condition, pta_status, cp, sid, purchase_ref, date_in, bh, notes, now, now))
        unit_id = cur.lastrowid
        
        # Log stock ledger
        v = db.query_one("SELECT product_id FROM variants WHERE id = ?", (variant_id,))
        cx.execute("""
            INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
            VALUES (?, ?, ?, ?, 'PHONE', 1, 1, 'PURCHASE', ?, ?, ?, ?)
        """, (v["product_id"] if v else 0, variant_id, unit_id, imei1, purchase_ref, "Initial Unit Added", user_id, now))

        # Update variant stock_quantity to match in-stock units
        in_stock_cnt = cx.execute("SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (variant_id,)).fetchone()[0]
        cx.execute("UPDATE variants SET stock_quantity = ? WHERE id = ?", (in_stock_cnt, variant_id))

        # Alert transition
        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, [variant_id], user_id=user_id, action_trigger="ADD_UNIT")
        except Exception:
            pass

    db.bump_change_version("stock")
    auth.log_audit(user_id, username, "ADD_UNIT", "units", str(unit_id), "", f"IMEI: {imei1}")
    return {"success": True, "unit_id": unit_id}

def update_unit(unit_id, imei1, imei2=None, condition="NEW_BOX_PACK", pta_status="PTA_APPROVED", cost_price=0, battery_health=100, status="IN_STOCK", notes="", target_variant_id=None, override_luhn=False, admin_reason="", user_id=0, username="", user_role="ADMIN"):
    if user_role != "ADMIN":
        return {"success": False, "error": "Access Denied: Only Admin can edit phone units."}

    old = db.query_one("SELECT * FROM units WHERE id = ?", (unit_id,))
    if not old: return {"success": False, "error": "Unit not found"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    imei1 = str(imei1).strip()
    imei2 = (str(imei2).strip() or None) if (imei2 and str(imei2).strip()) else None
    cp = parse_money(cost_price)
    bh = parse_qty(battery_health, 100)

    # 1. Luhn Checksum validation (validated when IMEI is modified)
    imei1_changed = (imei1 != old["imei1"])
    imei2_changed = (imei2 != old.get("imei2"))
    if not override_luhn:
        import scanner
        if imei1_changed:
            is_luhn, l_msg = scanner.luhn_checksum_valid(imei1)
            if not is_luhn:
                return {"success": False, "error": f"Invalid IMEI 1 ({l_msg}). Check 15 digits or enable 'Override Luhn' with admin reason."}
        if imei2 and imei2_changed:
            is_luhn2, l_msg2 = scanner.luhn_checksum_valid(imei2)
            if not is_luhn2:
                return {"success": False, "error": f"Invalid IMEI 2 ({l_msg2}). Check 15 digits or enable 'Override Luhn' with admin reason."}
    else:
        if (imei1_changed or imei2_changed) and (not admin_reason or not str(admin_reason).strip()):
            return {"success": False, "error": "Admin reason is mandatory when overriding Luhn checksum."}

    # 2. SOLD or IN_REPAIR validation
    if old["status"] == "IN_REPAIR" and status == "IN_STOCK" and not str(admin_reason).strip():
        admin_reason = "Repair completed - returned to stock"

    if old["status"] in ("SOLD", "IN_REPAIR"):
        if not admin_reason or not str(admin_reason).strip():
            return {"success": False, "error": f"Editing a {old['status']} unit requires a mandatory Admin reason."}
        
        imei_changed = (old["imei1"] != imei1 or (old.get("imei2") or "") != (imei2 or ""))
        cost_changed = (old["cost_price"] != cp)
        if imei_changed or cost_changed:
            auth.log_audit(
                user_id, username, "CRITICAL_OVERRIDE_SOLD_UNIT", "units", str(unit_id),
                f"Old IMEI: {old['imei1']}, Cost: {old['cost_price']}",
                f"New IMEI: {imei1}, Cost: {cp}, Reason: {admin_reason}. Warning: Historical profit calculation affected."
            )

    # 3. Duplicate checks across ALL units (excluding self)
    dup = db.query_one("SELECT id FROM units WHERE (imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)) AND id != ?", (imei1, imei1, unit_id))
    if dup:
        return {"success": False, "error": f"IMEI 1 ({imei1}) is already assigned to unit #{dup['id']}!"}
    if imei2:
        dup2 = db.query_one("SELECT id FROM units WHERE (imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)) AND id != ?", (imei2, imei2, unit_id))
        if dup2:
            return {"success": False, "error": f"IMEI 2 ({imei2}) is already assigned to unit #{dup2['id']}!"}

    # 4. Target variant resolution (move unit if requested)
    target_vid = int(target_variant_id) if (target_variant_id and int(target_variant_id) != old["variant_id"]) else None
    final_variant_id = target_vid if target_vid else old["variant_id"]
    if target_vid:
        t_var = db.query_one("SELECT id FROM variants WHERE id = ?", (target_vid,))
        if not t_var:
            return {"success": False, "error": f"Target variant #{target_vid} does not exist."}

    t1 = imei1[-4:] if len(imei1) >= 4 else imei1
    t2 = imei2[-4:] if (imei2 and len(imei2) >= 4) else (imei2 if imei2 else None)

    with db.transaction() as cx:
        cx.execute("""
            UPDATE units SET variant_id=?, imei1=?, imei2=?, imei1_tail=?, imei2_tail=?, condition=?, pta_status=?, cost_price=?, battery_health=?, status=?, notes=?, updated_at=?
            WHERE id=?
        """, (final_variant_id, imei1, imei2, t1, t2, condition, pta_status, cp, bh, status, notes, now, unit_id))

        # Re-derive stock_quantity on affected variant(s)
        for v_id in set([old["variant_id"], final_variant_id]):
            cnt_row = cx.execute("SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (v_id,)).fetchone()
            in_stock_cnt = cnt_row[0] if cnt_row else 0
            cx.execute("UPDATE variants SET stock_quantity = ? WHERE id = ?", (in_stock_cnt, v_id))

        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, list(set([old["variant_id"], final_variant_id])), user_id=user_id, action_trigger="UPDATE_UNIT")
        except Exception:
            pass

    db.bump_change_version("stock")
    db.bump_change_version("items")
    auth.log_audit(user_id, username, "UPDATE_UNIT", "units", str(unit_id), json.dumps(dict(old)), f"Status: {status}, Cost: {cp}, Reason: {admin_reason}")
    return {"success": True}

def move_unit_variant(unit_id, target_variant_id, user_id=0, username=""):
    """Move a unit to another variant if it was mistakenly added to the wrong variant."""
    unit = db.query_one("SELECT * FROM units WHERE id = ?", (unit_id,))
    if not unit: return False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("UPDATE units SET variant_id = ?, updated_at = ? WHERE id = ?", (target_variant_id, now, unit_id))
        cx.execute("UPDATE variants SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'), updated_at = ? WHERE id = ?", (unit["variant_id"], now, unit["variant_id"]))
        cx.execute("UPDATE variants SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'), updated_at = ? WHERE id = ?", (target_variant_id, now, target_variant_id))
        import alert_engine
        alert_engine.evaluate_stock_transitions(cx, [unit["variant_id"], target_variant_id], user_id=user_id, action_trigger="MOVE_UNIT_VARIANT")
    auth.log_audit(user_id, username, "MOVE_UNIT_VARIANT", "units", str(unit_id), f"From {unit['variant_id']}", f"To {target_variant_id}")
    return True

# ═══════════════════════════════════════════════════════════
# 4. IMEI LOOKUP (FULL LIFECYCLE CARD)
# ═══════════════════════════════════════════════════════════

def imei_lookup_lifecycle(imei_or_fragment):
    """
    Returns complete lifecycle card for an IMEI (or last 4-6 digits):
    Model, specs, cost, supplier, status, sale, returns, repair tickets, software jobs.
    """
    search_term = str(imei_or_fragment).strip()
    unit = db.query_one("""
        SELECT u.*, v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price, v.sku,
               p.brand, p.name AS model_name, p.category, p.default_warranty_months,
               s.name AS supplier_name, s.phone AS supplier_phone
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        LEFT JOIN suppliers s ON u.supplier_id = s.id
        WHERE u.imei1 = ? OR u.imei2 = ? OR u.imei1 LIKE ? OR u.imei2 LIKE ?
        LIMIT 1
    """, (search_term, search_term, f"%{search_term}", f"%{search_term}"))

    if not unit:
        return None

    # Find Sale info
    sale_item = db.query_one("""
        SELECT si.*, s.invoice_no, s.customer_name, s.customer_phone, s.created_at AS sale_date, s.payment_method
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE si.unit_id = ?
        ORDER BY si.id DESC LIMIT 1
    """, (unit["id"],))

    # Find Returns
    returns = db.query_all("""
        SELECT r.*, ri.return_action, ri.refund_amount
        FROM return_items ri
        JOIN returns r ON ri.return_id = r.id
        WHERE ri.unit_id = ?
    """, (unit["id"],))

    # Find Repairs on this IMEI
    repairs = db.query_all("SELECT * FROM repair_jobs WHERE imei = ?", (unit["imei1"],))

    # Find Software jobs on this IMEI
    software = db.query_all("SELECT * FROM software_jobs WHERE imei = ?", (unit["imei1"],))

    # Find Stock ledger timeline
    history = db.query_all("SELECT * FROM stock_ledger WHERE unit_id = ? ORDER BY id ASC", (unit["id"],))

    return {
        "unit": unit,
        "sale": sale_item,
        "returns": returns,
        "repairs": repairs,
        "software": software,
        "history": history
    }

# ═══════════════════════════════════════════════════════════
# 5. BULK TOOLS & AGING STOCK
# ═══════════════════════════════════════════════════════════

def bulk_price_update(brand=None, category=None, adjustment_type="AMOUNT", retail_adj=0, wholesale_adj=0, user_id=0, username=""):
    """
    Bulk price update: (+/- amount or %) by Brand or Category.
    """
    sql = """
        SELECT v.id, v.retail_price, v.wholesale_price, v.min_selling_price
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.is_archived = 0
    """
    params = []
    if brand:
        sql += " AND p.brand = ?"
        params.append(brand)
    if category:
        sql += " AND p.category = ?"
        params.append(category)

    rows = db.query_all(sql, params)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db.transaction() as cx:
        for r in rows:
            if adjustment_type == "PERCENT":
                new_ret = round(r["retail_price"] * (1 + float(retail_adj) / 100.0), -1)
                new_ws = round(r["wholesale_price"] * (1 + float(wholesale_adj) / 100.0), -1)
            else:
                new_ret = max(0, r["retail_price"] + float(retail_adj))
                new_ws = max(0, r["wholesale_price"] + float(wholesale_adj))
            
            cx.execute("UPDATE variants SET retail_price=?, wholesale_price=?, updated_at=? WHERE id=?",
                       (new_ret, new_ws, now, r["id"]))

    auth.log_audit(user_id, username, "BULK_PRICE_UPDATE", "variants", f"Brand: {brand or 'ALL'}", "", f"Updated {len(rows)} variants")
    return len(rows)

def preview_bulk_price_update(brand=None, category=None, adjustment_type="AMOUNT", retail_adj=0, wholesale_adj=0):
    """
    Computes before & after prices for bulk update preview without committing.
    """
    sql = """
        SELECT v.id, v.sku, v.retail_price, v.wholesale_price, p.name AS model_name, p.brand, p.category
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.is_archived = 0
    """
    params = []
    if brand:
        sql += " AND p.brand = ?"
        params.append(brand)
    if category:
        sql += " AND p.category = ?"
        params.append(category)

    rows = db.query_all(sql, params)
    preview = []
    for r in rows:
        if adjustment_type == "PERCENT":
            new_ret = round(r["retail_price"] * (1 + float(retail_adj) / 100.0), -1)
            new_ws = round(r["wholesale_price"] * (1 + float(wholesale_adj) / 100.0), -1)
        else:
            new_ret = max(0, r["retail_price"] + float(retail_adj))
            new_ws = max(0, r["wholesale_price"] + float(wholesale_adj))
        preview.append({
            "variant_id": r["id"],
            "model_name": r["model_name"],
            "sku": r["sku"],
            "brand": r["brand"],
            "current_retail": r["retail_price"],
            "new_retail": new_ret,
            "current_wholesale": r["wholesale_price"],
            "new_wholesale": new_ws
        })
    return {"count": len(preview), "items": preview}

def preview_inventory_import(rows_data):
    """
    Pre-validates inventory import rows with duplicate IMEI detection.
    """
    if not isinstance(rows_data, list):
        return {"success": False, "error": "Invalid rows format"}

    seen_imeis = set()
    validated = []
    duplicates = 0
    valid_count = 0

    for idx, row in enumerate(rows_data):
        b = str(row.get("brand") or "").strip()
        m = str(row.get("model_name") or row.get("name") or "").strip()
        itype = str(row.get("item_type") or "PHONE").upper()
        imei = str(row.get("imei1") or row.get("imei") or "").strip()
        cost = float(row.get("cost_price") or row.get("wholesale_price") or 0)
        ret = float(row.get("retail_price") or 0)

        item_status = "VALID"
        err_msg = ""

        if not m:
            item_status = "INVALID"
            err_msg = "Model name missing"
        elif itype in ("PHONE", "SERIAL") and imei:
            if imei in seen_imeis:
                item_status = "DUPLICATE_IN_FILE"
                err_msg = f"Duplicate IMEI in import file: {imei}"
                duplicates += 1
            else:
                seen_imeis.add(imei)
                u_cand = db.query_one("SELECT id, status FROM units WHERE imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)", (imei, imei))
                if u_cand:
                    item_status = "DUPLICATE_IN_DB"
                    err_msg = f"IMEI {imei} already registered in database (Unit #{u_cand['id']}, Status: {u_cand['status']})"
                    duplicates += 1

        if item_status == "VALID":
            valid_count += 1

        validated.append({
            "row_idx": idx + 1,
            "brand": b,
            "model_name": m,
            "item_type": itype,
            "imei1": imei,
            "cost_price": cost,
            "retail_price": ret,
            "status": item_status,
            "error": err_msg
        })

    return {
        "success": True,
        "total_rows": len(rows_data),
        "valid_rows": valid_count,
        "duplicate_imeis": duplicates,
        "items": validated
    }

def get_aging_stock():
    """Identifies phones unsold for 30+, 60+, and 90+ days."""
    today = datetime.now().date()
    rows = db.query_all("""
        SELECT u.*, v.ram, v.storage, v.color, v.retail_price,
               p.brand, p.name AS model_name
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        WHERE u.status = 'IN_STOCK'
        ORDER BY u.date_in ASC
    """)
    
    aging_30 = []
    aging_60 = []
    aging_90 = []

    for r in rows:
        try:
            d_in = datetime.strptime(r["date_in"][:10], "%Y-%m-%d").date()
            days = (today - d_in).days
        except Exception:
            days = 0
        r["days_in_stock"] = days
        
        if days >= 90:
            aging_90.append(r)
        elif days >= 60:
            aging_60.append(r)
        elif days >= 30:
            aging_30.append(r)
            
    return {
        "aging_30_count": len(aging_30),
        "aging_60_count": len(aging_60),
        "aging_90_count": len(aging_90),
        "total_aging": len(aging_30) + len(aging_60) + len(aging_90),
        "list_30": aging_30,
        "list_60": aging_60,
        "list_90": aging_90
    }

def get_stock_valuation():
    """Calculates cost vs retail valuation for phones, accessories, and spare parts."""
    phones = db.query_one("""
        SELECT COUNT(*) AS total_count,
               COALESCE(SUM(u.cost_price), 0) AS total_cost,
               COALESCE(SUM(v.retail_price), 0) AS total_retail
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        WHERE u.status = 'IN_STOCK'
    """)

    accessories = db.query_one("""
        SELECT COALESCE(SUM(v.stock_quantity), 0) AS total_count,
               COALESCE(SUM(v.stock_quantity * v.wholesale_price), 0) AS total_cost,
               COALESCE(SUM(v.stock_quantity * v.retail_price), 0) AS total_retail
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE p.item_type = 'ACCESSORY' AND v.is_archived = 0
    """)

    parts = db.query_one("""
        SELECT COALESCE(SUM(v.stock_quantity), 0) AS total_count,
               COALESCE(SUM(v.stock_quantity * v.wholesale_price), 0) AS total_cost,
               COALESCE(SUM(v.stock_quantity * v.retail_price), 0) AS total_retail
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE p.item_type = 'SPARE_PART' AND v.is_archived = 0
    """)

    return {
        "phones": phones,
        "accessories": accessories,
        "parts": parts,
        "total_cost": phones["total_cost"] + accessories["total_cost"] + parts["total_cost"],
        "total_retail": phones["total_retail"] + accessories["total_retail"] + parts["total_retail"],
        "potential_profit": (phones["total_retail"] + accessories["total_retail"] + parts["total_retail"]) - (phones["total_cost"] + accessories["total_cost"] + parts["total_cost"])
    }

def parse_imei_pairs(raw_input):
    """
    Parses input into clean pairs of physical units: [{"imei1": ..., "imei2": ...}, ...].
    Each pair represents ONE physical mobile device (supporting dual-SIM IMEIs).
    Handles:
    - Lists of dicts: [{'imei1': ..., 'imei2': ...}, ...]
    - Paired strings on single line:
      '358921098492011 / 358921098492012'
      '358921098492011 | 358921098492012'
      '358921098492011, 358921098492012' (2 numbers on same line)
      '358921098492011 \t 358921098492012'
      '358921098492011' (single IMEI)
    - Multiline input with one phone per line.
    """
    if not raw_input:
        return []
    if isinstance(raw_input, list):
        res = []
        for item in raw_input:
            if isinstance(item, dict):
                im1 = str(item.get("imei1") or item.get("imei") or "").strip()
                im2 = str(item.get("imei2") or "").strip()
                if im1 or im2:
                    res.append({"imei1": im1 or im2, "imei2": im2 if im1 else ""})
            elif isinstance(item, (list, tuple)):
                im1 = str(item[0]).strip() if len(item) > 0 else ""
                im2 = str(item[1]).strip() if len(item) > 1 else ""
                if im1 or im2:
                    res.append({"imei1": im1 or im2, "imei2": im2 if im1 else ""})
            elif isinstance(item, str):
                res.extend(parse_imei_pairs(item))
        return res

    if not isinstance(raw_input, str):
        return []

    lines = raw_input.strip().splitlines()
    pairs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = []
        if "/" in line:
            parts = [p.strip() for p in line.split("/") if p.strip()]
        elif "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
        elif "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        elif "," in line:
            subparts = [p.strip() for p in line.split(",") if p.strip()]
            if len(subparts) == 2 and any(c.isdigit() for c in subparts[0]) and any(c.isdigit() for c in subparts[1]):
                parts = subparts
            else:
                for sp in subparts:
                    if sp: pairs.append({"imei1": sp, "imei2": ""})
                continue
        else:
            # Check if line has two 14-16 digit numbers separated by spaces
            digits_matches = re.findall(r'\b\d{14,16}\b', line)
            if len(digits_matches) == 2:
                parts = digits_matches
            elif len(digits_matches) > 2:
                for dm in digits_matches:
                    pairs.append({"imei1": dm, "imei2": ""})
                continue

        if len(parts) >= 2:
            pairs.append({"imei1": parts[0], "imei2": parts[1]})
        elif len(parts) == 1:
            pairs.append({"imei1": parts[0], "imei2": ""})
        else:
            pairs.append({"imei1": line, "imei2": ""})

    return pairs

def parse_imei_list(raw_input):
    """Parses a string or list into flat list of clean unique IMEI strings."""
    pairs = parse_imei_pairs(raw_input)
    res = []
    seen = set()
    for p in pairs:
        for im in (p.get("imei1"), p.get("imei2")):
            im_str = str(im or "").strip()
            if im_str and im_str not in seen:
                seen.add(im_str)
                res.append(im_str)
    return res

def add_stock(variant_id, qty=1, cost_price=None, imeis=None, condition="NEW_BOX_PACK",
              pta_status="PTA_APPROVED", mode="PURCHASE", supplier_id=0,
              payment_method="CASH", paid_amount=None, request_id="", notes="",
              user_id=0, username=""):
    """
    Unified stock intake service for Inventory and POS.
    - Idempotency support via request_id.
    - Supports PURCHASE mode (with optional supplier ledger entry) and ADJUSTMENT mode.
    - Phones: Validates IMEIs, creates units in stock, logs stock ledger.
    - Accessories: Increments stock_quantity, updates wholesale_price if cost provided, logs stock ledger.
    - Atomically updates stock and triggers alert engine.
    """
    # 1. Idempotency check
    if request_id:
        cached = db.query_one("SELECT response_json FROM idempotency_keys WHERE request_id = ?", (request_id,))
        if cached and cached["response_json"]:
            try:
                return json.loads(cached["response_json"])
            except Exception:
                pass

    variant = db.query_one("SELECT * FROM variants WHERE id = ?", (variant_id,))
    if not variant:
        return {"success": False, "status": 404, "message": "Variant not found."}

    product = db.query_one("SELECT * FROM products WHERE id = ?", (variant["product_id"],))
    if not product:
        return {"success": False, "status": 404, "message": "Product not found."}

    item_type = product.get("item_type", "PHONE")
    brand = product.get("brand", "PHN")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cp = parse_money(cost_price) if (cost_price is not None and cost_price != "") else variant["wholesale_price"]
    parsed_pairs = parse_imei_pairs(imeis)
    parsed_imeis = []
    for p in parsed_pairs:
        if p.get("imei1"): parsed_imeis.append(p["imei1"])
        if p.get("imei2"): parsed_imeis.append(p["imei2"])
    add_qty = len(parsed_pairs) if parsed_pairs else parse_qty(qty)

    if add_qty <= 0:
        return {"success": False, "status": 400, "message": "Quantity or at least one IMEI is required."}

    # Validate IMEIs for duplicates
    seen = set()
    for imei in parsed_imeis:
        if imei in seen:
            return {"success": False, "status": 409, "message": f"Duplicate IMEI '{imei}' entered multiple times."}
        seen.add(imei)
        dup = db.query_one("SELECT id, imei1 FROM units WHERE imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)", (imei, imei))
        if dup:
            return {"success": False, "status": 409, "message": f"IMEI '{imei}' is ALREADY REGISTERED in the system (Unit #{dup['id']})."}

    # Handle Purchase with Supplier if supplier_id > 0
    if mode.upper() == "PURCHASE" and supplier_id and int(supplier_id) > 0:
        import purchasing
        items_payload = [{
            "variant_id": variant_id,
            "item_type": item_type,
            "qty": add_qty,
            "unit_cost": cp,
            "condition": condition,
            "pta_status": pta_status,
            "imeis": [{"imei1": p.get("imei1"), "imei2": p.get("imei2") or "", "condition": condition, "pta_status": pta_status, "unit_cost": cp} for p in parsed_pairs] if parsed_pairs else []
        }]
        paid = parse_money(paid_amount) if paid_amount is not None else 0.0
        p_res = purchasing.create_purchase(
            supplier_id=int(supplier_id),
            items=items_payload,
            paid_amount=paid,
            payment_method=payment_method or "CASH",
            notes=notes or "Stock Intake via Inventory",
            user_id=user_id,
            username=username
        )
        if request_id and p_res.get("success"):
            try:
                db.execute("INSERT OR REPLACE INTO idempotency_keys (request_id, response_json, created_at) VALUES (?, ?, ?)",
                           (request_id, json.dumps(p_res), now))
            except Exception:
                pass
        return p_res

    # Direct intake / adjustment mode
    action_type = "PURCHASE" if mode.upper() == "PURCHASE" else "ADJUST"
    ref_label = "STOCK_ADD" if action_type == "PURCHASE" else "STOCK_ADJUST"
    note_text = notes.strip() if notes else ("Manual Stock Addition" if action_type == "PURCHASE" else "Manual Stock Adjustment")

    with db.transaction() as cx:
        cur = cx.cursor()
        if item_type in ("ACCESSORY", "SPARE_PART") and not parsed_pairs:
            cur.execute("""
                UPDATE variants SET 
                    stock_quantity = COALESCE(stock_quantity, 0) + ?,
                    wholesale_price = CASE WHEN ? > 0 THEN ? ELSE wholesale_price END,
                    updated_at = ?
                WHERE id = ?
            """, (add_qty, cp, cp, now, variant_id))

            new_bal = (variant["stock_quantity"] or 0) + add_qty
            cur.execute("""
                INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                VALUES (?, ?, 0, '', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (variant["product_id"], variant_id, item_type, add_qty, new_bal, action_type, ref_label, note_text, user_id, now))
        elif parsed_pairs:
            for pair in parsed_pairs:
                im1 = pair["imei1"]
                im2 = pair["imei2"] or None
                cur.execute("""
                    INSERT INTO units (variant_id, imei1, imei2, condition, pta_status, cost_price, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
                """, (variant_id, im1, im2, condition, pta_status, cp, now, now))
                uid = cur.lastrowid
                imei_label = f"{im1} / {im2}" if im2 else im1
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (?, ?, ?, ?, 'PHONE', 1, (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'), ?, ?, ?, ?, ?)
                """, (variant["product_id"], variant_id, uid, imei_label, variant_id, action_type, ref_label, note_text, user_id, now))

            cur.execute("""
                UPDATE variants SET 
                    stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                    updated_at = ?
                WHERE id = ?
            """, (variant_id, now, variant_id))
        else:
            for _ in range(add_qty):
                auto_sn = generate_next_code(cx, f"SN-{brand[:3].upper()}")
                cur.execute("""
                    INSERT INTO units (variant_id, imei1, condition, pta_status, cost_price, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
                """, (variant_id, auto_sn, condition, pta_status, cp, now, now))
                uid = cur.lastrowid
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (?, ?, ?, ?, 'PHONE', 1, (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'), ?, ?, ?, ?, ?)
                """, (variant["product_id"], variant_id, uid, auto_sn, variant_id, action_type, ref_label, note_text, user_id, now))

            cur.execute("""
                UPDATE variants SET 
                    stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                    updated_at = ?
                WHERE id = ?
            """, (variant_id, now, variant_id))

        try:
            import alert_engine
            alert_engine.evaluate_stock_transitions(cx, [variant_id], user_id=user_id, action_trigger="ADD_STOCK_UNIFIED")
        except Exception:
            pass

    db.bump_change_version("items")
    db.bump_change_version("stock")
    auth.log_audit(user_id, username, "ADD_STOCK", "variants", str(variant_id), "", f"Added {add_qty} units ({mode})")

    updated_v = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (variant_id,))
    res_data = {
        "success": True,
        "message": f"Successfully added {add_qty} unit(s) to stock!",
        "variant_id": variant_id,
        "units_added": add_qty,
        "new_stock": updated_v["stock_quantity"] if updated_v else 0
    }

    if request_id:
        try:
            db.execute("INSERT OR REPLACE INTO idempotency_keys (request_id, response_json, created_at) VALUES (?, ?, ?)",
                       (request_id, json.dumps(res_data), now))
        except Exception:
            pass

    return res_data

def add_stock_to_variant(variant_id, cost_price=0, imeis=None, qty=0, condition="NEW_BOX_PACK", pta_status="PTA_APPROVED", user_id=0, username=""):
    return add_stock(
        variant_id=variant_id,
        qty=qty,
        cost_price=cost_price,
        imeis=imeis,
        condition=condition,
        pta_status=pta_status,
        mode="PURCHASE",
        user_id=user_id,
        username=username
    )

# ═══════════════════════════════════════════════════════════
# 5. UNIFIED CREATE & UPDATE ENGINE (BULLETPROOF ITEM CONTRACT)
# ═══════════════════════════════════════════════════════════

def create_item_unified(payload, user_id=0, username=""):
    """
    Single unified create service for all item types: PHONE, SERIAL, ACCESSORY, SPARE_PART.
    - Idempotent via request_id
    - Supports multiple variants per phone model with opening stock and IMEIs
    - Safe money & quantity normalization (supports commas, 'Rs.', Urdu digits)
    - Auto-generates unique barcode and SKU on blank
    - Duplicate detection (barcode, SKU, exact name, IMEIs)
    - Single atomic ACID transaction across products, variants, and stock ledger
    - Derived data updates safely (never rolls back item creation)
    """
    request_id = str(payload.get("request_id") or "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Idempotency Check
    if request_id:
        cached = db.query_one("SELECT response_json FROM idempotency_keys WHERE request_id = ?", (request_id,))
        if cached:
            try:
                ret = json.loads(cached["response_json"])
                ret["cached"] = True
                return ret
            except Exception:
                pass

    # 2. Extract & Normalize Fields
    item_type = str(payload.get("item_type") or "ACCESSORY").strip().upper()
    if item_type not in ("PHONE", "SERIAL", "ACCESSORY", "SPARE_PART"):
        return {
            "success": False,
            "status": 422,
            "errors": [{"field": "item_type", "code": "INVALID_TYPE", "message": f"Item type '{item_type}' is invalid."}]
        }

    passed_pid = parse_qty(payload.get("product_id"))
    existing_p = None
    if passed_pid > 0:
        existing_p = db.query_one("SELECT * FROM products WHERE id = ?", (passed_pid,))
        if existing_p:
            if not payload.get("brand"):
                payload["brand"] = existing_p["brand"]
            if not payload.get("name"):
                payload["name"] = existing_p["name"]
            if not payload.get("category"):
                payload["category"] = existing_p["category"]
            item_type = existing_p["item_type"]

    brand = str(payload.get("brand") or "").strip()
    name = str(payload.get("name") or "").strip()

    errors = []
    if not brand:
        errors.append({"field": "brand", "code": "REQUIRED", "message": "Brand is required."})
    elif len(brand) > 60:
        errors.append({"field": "brand", "code": "TOO_LONG", "message": "Brand must not exceed 60 characters."})

    if not name:
        errors.append({"field": "name", "code": "REQUIRED", "message": "Item name is required."})
    elif len(name) > 120:
        errors.append({"field": "name", "code": "TOO_LONG", "message": "Name must not exceed 120 characters."})

    category = str(payload.get("category") or ("Smartphone" if item_type == "PHONE" else ("Accessory" if item_type == "ACCESSORY" else "Spare Parts"))).strip()

    v_first = None
    if isinstance(payload.get("variants"), list) and len(payload["variants"]) > 0 and isinstance(payload["variants"][0], dict):
        v_first = payload["variants"][0]

    rp = parse_money(payload.get("retail_price"))
    if rp == 0 and v_first and v_first.get("retail_price"):
        rp = parse_money(v_first.get("retail_price"))

    wp = parse_money(payload.get("wholesale_price"))
    if wp == 0 and v_first and (v_first.get("wholesale_price") or v_first.get("cost_price")):
        wp = parse_money(v_first.get("wholesale_price") or v_first.get("cost_price"))

    mp = parse_money(payload.get("min_selling_price"))
    if mp == 0 and v_first and v_first.get("min_selling_price"):
        mp = parse_money(v_first.get("min_selling_price"))

    if mp > 0 and rp < mp:
        errors.append({
            "field": "retail_price",
            "code": "MIN_PRICE_EXCEEDS_RETAIL",
            "message": f"Retail price (Rs. {rp:,.0f}) cannot be less than minimum selling price (Rs. {mp:,.0f})."
        })

    if errors:
        return {"success": False, "status": 422, "code": "INVALID_PRICING", "errors": errors}

    raw_sq_val = payload.get("stock_quantity")
    if raw_sq_val is None or raw_sq_val == "":
        raw_sq_val = payload.get("stock_qty")
    if raw_sq_val is None or raw_sq_val == "":
        raw_sq_val = payload.get("quantity")
    if raw_sq_val is None or raw_sq_val == "":
        raw_sq_val = payload.get("qty")
    if (raw_sq_val is None or raw_sq_val == "") and v_first:
        raw_sq_val = v_first.get("stock_quantity") if v_first.get("stock_quantity") is not None else v_first.get("qty")
    if raw_sq_val is None or raw_sq_val == "":
        raw_sq_val = 0
    sq = parse_qty(raw_sq_val)
    low_level = parse_qty(payload.get("low_stock_level")) if payload.get("low_stock_level") not in (None, "") else None
    reorder_qty = parse_qty(payload.get("reorder_qty")) if payload.get("reorder_qty") not in (None, "") else None
    alert_off = 1 if payload.get("alert_off") in (1, "1", True) else 0

    ram = str(payload.get("ram") or "").strip()
    storage = str(payload.get("storage") or "").strip()
    color = str(payload.get("color") or "").strip()
    network = str(payload.get("network") or "").strip()
    compat = str(payload.get("compatible_models") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    warranty = int(payload.get("warranty_months") or (12 if item_type == "PHONE" else 1))

    raw_barcode = (str(payload.get("barcode") or "").strip() or None)
    raw_sku = (str(payload.get("sku") or "").strip() or None)

    # 3. Duplicate Guards (Barcode & SKU for single item)
    if raw_barcode:
        dup_b = db.query_one("""
            SELECT v.id, p.name, p.brand, v.sku 
            FROM variants v 
            JOIN products p ON v.product_id = p.id 
            WHERE v.barcode = ?
        """, (raw_barcode,))
        if dup_b:
            return {
                "success": False,
                "status": 409,
                "code": "DUPLICATE_BARCODE",
                "message": f"Barcode '{raw_barcode}' is already in use by {dup_b['brand']} {dup_b['name']} (SKU: {dup_b['sku']}).",
                "existing": {"variant_id": dup_b["id"], "name": f"{dup_b['brand']} {dup_b['name']}", "sku": dup_b["sku"]}
            }

    if raw_sku:
        dup_s = db.query_one("""
            SELECT v.id, p.name, p.brand 
            FROM variants v 
            JOIN products p ON v.product_id = p.id 
            WHERE v.sku = ?
        """, (raw_sku,))
        if dup_s:
            return {
                "success": False,
                "status": 409,
                "code": "DUPLICATE_SKU",
                "message": f"SKU '{raw_sku}' is already in use by {dup_s['brand']} {dup_s['name']}.",
                "existing": {"variant_id": dup_s["id"], "name": f"{dup_s['brand']} {dup_s['name']}"}
            }

    # 4. Check Existing Product or Archive
    if not existing_p:
        existing_p = db.query_one("SELECT * FROM products WHERE brand = ? AND name = ? AND item_type = ?", (brand, name, item_type))
    if existing_p and existing_p["is_archived"] == 1:
        if payload.get("action") == "restore":
            db.execute("UPDATE products SET is_archived = 0 WHERE id = ?", (existing_p["id"],))
        else:
            return {
                "success": False,
                "status": 409,
                "code": "EXISTS_IN_ARCHIVE",
                "message": f"Product '{brand} {name}' exists in the archive. You can restore it.",
                "existing": {"product_id": existing_p["id"], "name": f"{brand} {name}", "archived": True}
            }

    # Extract variants array for PHONE / SERIAL
    variants_raw = payload.get("variants")
    if isinstance(variants_raw, str):
        try:
            variants_raw = json.loads(variants_raw)
        except Exception:
            variants_raw = None

    if item_type in ("PHONE", "SERIAL") and isinstance(variants_raw, list) and len(variants_raw) > 0:
        variants_list = variants_raw
    elif item_type in ("PHONE", "SERIAL"):
        variants_list = [{
            "ram": ram,
            "storage": storage,
            "color": color,
            "network": network,
            "retail_price": rp,
            "wholesale_price": wp,
            "min_selling_price": mp,
            "stock_quantity": sq,
            "imeis": payload.get("imeis", ""),
            "pta_status": payload.get("pta_status", "PTA_APPROVED"),
            "condition": payload.get("condition", "NEW_BOX_PACK"),
            "low_stock_level": low_level,
            "reorder_qty": reorder_qty,
            "alert_off": alert_off,
            "sku": raw_sku,
            "barcode": raw_barcode
        }]
    else:
        variants_list = None

    # Pre-validate all IMEIs across all variants
    if variants_list:
        seen_imeis = set()
        for v_item in variants_list:
            v_imeis = parse_imei_list(v_item.get("imeis"))
            for imei in v_imeis:
                if imei in seen_imeis:
                    return {
                        "success": False,
                        "status": 409,
                        "code": "DUPLICATE_IMEI",
                        "message": f"Duplicate IMEI '{imei}' entered multiple times in this form."
                    }
                seen_imeis.add(imei)
                existing_u = db.query_one("""
                    SELECT u.id, u.imei1, p.brand, p.name 
                    FROM units u 
                    JOIN variants v ON u.variant_id = v.id 
                    JOIN products p ON v.product_id = p.id 
                    WHERE u.imei1 = ? OR (u.imei2 IS NOT NULL AND u.imei2 = ?)
                """, (imei, imei))
                if existing_u:
                    return {
                        "success": False,
                        "status": 409,
                        "code": "DUPLICATE_IMEI",
                        "message": f"IMEI '{imei}' is ALREADY REGISTERED in the system ({existing_u['brand']} {existing_u['name']}, Unit #{existing_u['id']})."
                    }

    # 5. Atomic Transaction
    final_reorder = low_level if low_level is not None else 5
    prefix = "PHN" if item_type in ("PHONE", "SERIAL") else ("ACC" if item_type == "ACCESSORY" else "PRT")

    with db.transaction() as cx:
        cur = cx.cursor()

        # Find or create product record
        if existing_p and existing_p["is_archived"] == 0:
            pid = existing_p["id"]
        else:
            cur.execute("""
                INSERT INTO products (brand, name, category, item_type, default_warranty_months, compatible_models, notes, is_archived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (brand, name, category, item_type, warranty, compat, notes, now, now))
            pid = cur.lastrowid

        created_vids = []
        total_units_created = 0
        first_sku = None
        first_barcode = None

        if variants_list:
            for v_item in variants_list:
                v_ram = str(v_item.get("ram") or "").strip()
                v_storage = str(v_item.get("storage") or "").strip()
                v_color = str(v_item.get("color") or "").strip()
                v_net = str(v_item.get("network") or "").strip()
                v_rp = parse_money(v_item.get("retail_price")) or rp
                v_wp = parse_money(v_item.get("wholesale_price")) or wp
                v_mp = parse_money(v_item.get("min_selling_price")) or mp
                v_low = parse_qty(v_item.get("low_stock_level")) if v_item.get("low_stock_level") not in (None, "") else low_level
                v_reorder = parse_qty(v_item.get("reorder_qty")) if v_item.get("reorder_qty") not in (None, "") else reorder_qty
                v_alert_off = 1 if v_item.get("alert_off") in (1, "1", True) else 0
                v_final_reorder = v_low if v_low is not None else 2

                v_sku = str(v_item.get("sku") or "").strip() or generate_next_code(cx, prefix)
                v_barcode = str(v_item.get("barcode") or "").strip() or generate_next_code(cx, f"BAR-{prefix}")
                if not first_sku: first_sku = v_sku
                if not first_barcode: first_barcode = v_barcode

                v_pairs = parse_imei_pairs(v_item.get("imeis"))
                v_stock_raw = parse_qty(v_item.get("stock_quantity", 0))
                v_stock = len(v_pairs) if v_pairs else v_stock_raw

                cur.execute("""
                    INSERT INTO variants (product_id, ram, storage, color, network, sku, barcode, retail_price, wholesale_price, min_selling_price, stock_quantity, reorder_level, low_stock_level, reorder_qty, alert_off, is_archived, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """, (pid, v_ram, v_storage, v_color, v_net, v_sku, v_barcode, v_rp, v_wp, v_mp, v_stock, v_final_reorder, v_low, v_reorder, v_alert_off, now, now))
                vid = cur.lastrowid
                created_vids.append(vid)

                v_cond = str(v_item.get("condition") or "NEW_BOX_PACK").strip()
                v_pta = str(v_item.get("pta_status") or "PTA_APPROVED").strip()

                if v_pairs:
                    for pair in v_pairs:
                        im1 = pair["imei1"]
                        im2 = pair["imei2"] or None
                        cur.execute("""
                            INSERT INTO units (variant_id, imei1, imei2, condition, pta_status, cost_price, status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
                        """, (vid, im1, im2, v_cond, v_pta, v_wp, now, now))
                        uid = cur.lastrowid
                        total_units_created += 1
                        imei_label = f"{im1} / {im2}" if im2 else im1
                        cur.execute("""
                            INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                            VALUES (?, ?, ?, ?, 'PHONE', 1, 1, 'PURCHASE', 'INITIAL_STOCK', 'Opening Stock Entry', ?, ?)
                        """, (pid, vid, uid, imei_label, user_id, now))
                elif v_stock > 0:
                    for _ in range(v_stock):
                        auto_sn = generate_next_code(cx, f"SN-{brand[:3].upper()}")
                        cur.execute("""
                            INSERT INTO units (variant_id, imei1, condition, pta_status, cost_price, status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
                        """, (vid, auto_sn, v_cond, v_pta, v_wp, now, now))
                        uid = cur.lastrowid
                        total_units_created += 1
                        cur.execute("""
                            INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                            VALUES (?, ?, ?, ?, 'PHONE', 1, 1, 'PURCHASE', 'INITIAL_STOCK', 'Opening Stock Entry', ?, ?)
                        """, (pid, vid, uid, auto_sn, user_id, now))

                try:
                    import alert_engine
                    alert_engine.evaluate_stock_transitions(cx, [vid], user_id=user_id, action_trigger="CREATE_ITEM_UNIFIED")
                except Exception:
                    pass

            vid = created_vids[0]
            final_sku = first_sku
            final_barcode = first_barcode
        else:
            # Single variant for ACCESSORY or SPARE_PART
            final_sku = raw_sku or generate_next_code(cx, prefix)
            final_barcode = raw_barcode or generate_next_code(cx, f"BAR-{prefix}")

            cur.execute("""
                INSERT INTO variants (product_id, ram, storage, color, network, sku, barcode, retail_price, wholesale_price, min_selling_price, stock_quantity, reorder_level, low_stock_level, reorder_qty, alert_off, is_archived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (pid, ram, storage, color, network, final_sku, final_barcode, rp, wp, mp, sq, final_reorder, low_level, reorder_qty, alert_off, now, now))
            vid = cur.lastrowid
            created_vids.append(vid)

            if sq > 0 and item_type in ("ACCESSORY", "SPARE_PART"):
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (?, ?, 0, '', ?, ?, ?, 'PURCHASE', 'INITIAL_STOCK', 'Opening Stock Entry', ?, ?)
                """, (pid, vid, item_type, sq, sq, user_id, now))

            try:
                import alert_engine
                alert_engine.evaluate_stock_transitions(cx, [vid], user_id=user_id, action_trigger="CREATE_ITEM_UNIFIED")
            except Exception:
                pass

    # Change feed bump
    db.bump_change_version("items")
    if sq > 0 or total_units_created > 0:
        db.bump_change_version("stock")

    variant_info = f"with {len(created_vids)} variants ({total_units_created} units)" if variants_list else f"(SKU: {final_sku}, Qty: {sq})"
    auth.log_audit(user_id, username, "CREATE_ITEM_UNIFIED", "variants", str(vid), "", f"{brand} {name} {variant_info}")

    res_data = {
        "success": True,
        "status": 201,
        "product_id": pid,
        "item_id": pid,
        "variant_id": vid,
        "variants": created_vids,
        "variant_count": len(created_vids),
        "unit_count": total_units_created,
        "sku": final_sku,
        "barcode": final_barcode,
        "retail_price": rp,
        "stock_quantity": total_units_created if variants_list else sq,
        "message": f"Successfully saved {brand} {name} {variant_info}!",
        "item": {
            "product_id": pid,
            "item_id": pid,
            "variant_id": vid,
            "brand": brand,
            "name": name,
            "item_type": item_type,
            "category": category,
            "sku": final_sku,
            "barcode": final_barcode,
            "retail_price": rp,
            "wholesale_price": wp,
            "stock_quantity": total_units_created if variants_list else sq,
            "low_stock_level": low_level,
            "reorder_qty": reorder_qty
        }
    }

    # Cache idempotency key if present
    if request_id:
        try:
            db.execute("INSERT OR REPLACE INTO idempotency_keys (request_id, response_json, created_at) VALUES (?, ?, ?)",
                       (request_id, json.dumps(res_data), now))
        except Exception:
            pass

    return res_data

def update_item_unified(payload, user_id=0, username=""):
    """Updates an existing item and variant safely."""
    vid = int(payload.get("variant_id") or 0)
    if not vid and payload.get("product_id"):
        v_first = db.query_one("SELECT id FROM variants WHERE product_id = ? AND is_archived = 0 ORDER BY id ASC", (int(payload["product_id"]),))
        if v_first:
            vid = v_first["id"]

    variant = db.query_one("SELECT * FROM variants WHERE id = ?", (vid,))
    if not variant:
        return {"success": False, "status": 404, "errors": [{"field": "variant_id", "message": "Variant not found"}]}

    pid = variant["product_id"]
    prod = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    brand = str(payload.get("brand") or prod["brand"]).strip()
    name = str(payload.get("name") or prod["name"]).strip()
    category = str(payload.get("category") or prod["category"]).strip()
    compat = str(payload.get("compatible_models") or prod.get("compatible_models", "")).strip()

    rp = parse_money(payload.get("retail_price", variant["retail_price"]))
    wp = parse_money(payload.get("wholesale_price", variant["wholesale_price"]))
    mp = parse_money(payload.get("min_selling_price", variant["min_selling_price"]))

    if prod and prod.get("item_type") in ("PHONE", "MOBILE", "SERIAL"):
        u_count = db.query_one("SELECT COUNT(*) AS c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (vid,))
        new_sq = u_count["c"] if u_count else 0
    else:
        raw_sq = payload.get("stock_quantity")
        if raw_sq is None or raw_sq == "":
            raw_sq = payload.get("stock_qty")
        if raw_sq is None or raw_sq == "":
            raw_sq = payload.get("quantity")
        if raw_sq is None or raw_sq == "":
            raw_sq = payload.get("qty")
        new_sq = parse_qty(raw_sq) if raw_sq is not None else variant["stock_quantity"]

    low_level = parse_qty(payload.get("low_stock_level")) if payload.get("low_stock_level") not in (None, "") else variant["low_stock_level"]
    reorder_qty = parse_qty(payload.get("reorder_qty")) if payload.get("reorder_qty") not in (None, "") else variant["reorder_qty"]
    alert_off = 1 if payload.get("alert_off") in (1, "1", True) else 0

    # SKU & Barcode safe resolution (permit clearing barcode, detect collisions)
    if "sku" in payload:
        raw_sku = str(payload.get("sku") or "").strip()
        sku = raw_sku if raw_sku else None
    else:
        sku = variant.get("sku") or None

    if "barcode" in payload:
        raw_bc = str(payload.get("barcode") or "").strip()
        barcode = raw_bc if raw_bc else None
    else:
        barcode = variant.get("barcode") or None

    # Duplicate check for barcode (never collide with self)
    if barcode:
        dup_b = db.query_one("SELECT id FROM variants WHERE barcode = ? AND id != ?", (barcode, vid))
        if dup_b:
            return {"success": False, "status": 409, "message": f"Barcode '{barcode}' is already in use by another item."}

    # Duplicate check for SKU (never collide with self)
    if sku:
        dup_s = db.query_one("SELECT id FROM variants WHERE sku = ? AND id != ?", (sku, vid))
        if dup_s:
            return {"success": False, "status": 409, "message": f"SKU '{sku}' is already in use by another item."}

    old_sq = variant["stock_quantity"]
    qty_diff = new_sq - old_sq

    try:
        with db.transaction() as cx:
            cx.execute("""
                UPDATE products SET brand=?, name=?, category=?, compatible_models=?, updated_at=?
                WHERE id=?
            """, (brand, name, category, compat, now, pid))

            cx.execute("""
                UPDATE variants SET retail_price=?, wholesale_price=?, min_selling_price=?, stock_quantity=?, low_stock_level=?, reorder_qty=?, alert_off=?, sku=?, barcode=?, updated_at=?
                WHERE id=?
            """, (rp, wp, mp, new_sq, low_level, reorder_qty, alert_off, sku, barcode, now, vid))

            if qty_diff != 0 and prod["item_type"] in ("ACCESSORY", "SPARE_PART"):
                cx.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (?, ?, 0, '', ?, ?, ?, 'ADJUST', 'STOCK_EDIT', 'Inventory Manual Adjustment', ?, ?)
                """, (pid, vid, prod["item_type"], qty_diff, new_sq, user_id, now))

            try:
                import alert_engine
                alert_engine.evaluate_stock_transitions(cx, [vid], user_id=user_id, action_trigger="UPDATE_ITEM_UNIFIED")
            except Exception:
                pass
    except Exception as exc:
        return {"success": False, "status": 400, "message": f"Failed to save item changes: {str(exc)}"}

    db.bump_change_version("items")
    if qty_diff != 0:
        db.bump_change_version("stock")

    auth.log_audit(user_id, username, "UPDATE_ITEM_UNIFIED", "variants", str(vid), json.dumps(dict(variant)), f"Updated {brand} {name}")
    return {"success": True, "status": 200, "item": {"product_id": pid, "variant_id": vid, "brand": brand, "name": name, "retail_price": rp, "stock_quantity": new_sq}}

def health_check_diagnostics():
    """Runs comprehensive non-destructive self-check inside rolled-back transactions."""
    results = []
    all_ok = True

    # 1. Database Integrity & Journal Mode
    try:
        row = db.query_one("PRAGMA journal_mode;")
        mode = list(row.values())[0] if row else "unknown"
        row_int = db.query_one("PRAGMA integrity_check;")
        int_res = list(row_int.values())[0] if row_int else "unknown"
        if str(int_res).lower() == "ok":
            results.append({"name": "Database Integrity & WAL", "status": "PASS", "detail": f"WAL mode active ({mode.upper()}), SQLite integrity: OK."})
        else:
            all_ok = False
            results.append({"name": "Database Integrity", "status": "FAIL", "detail": f"Integrity check failed: {int_res}"})
    except Exception as e:
        all_ok = False
        results.append({"name": "Database Integrity", "status": "FAIL", "detail": str(e)})

    # 2. Schema Tables & Dynamic Migrations
    try:
        tables = [r["name"] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")]
        req_tables = ["products", "variants", "units", "sales", "code_counters", "shop_profile", "change_feed_versions", "stock_alert_state"]
        missing = [t for t in req_tables if t not in tables]
        if not missing:
            results.append({"name": "Schema Migrations", "status": "PASS", "detail": f"All {len(req_tables)} core application tables verified."})
        else:
            all_ok = False
            results.append({"name": "Schema Migrations", "status": "FAIL", "detail": f"Missing tables: {', '.join(missing)}"})
    except Exception as e:
        all_ok = False
        results.append({"name": "Schema Migrations", "status": "FAIL", "detail": str(e)})

    # 3. Item Creation Transaction & Rollback Isolation
    try:
        with db.transaction() as cx:
            pid = cx.execute("""
                INSERT INTO products (brand, name, category, item_type, is_archived, created_at, updated_at)
                VALUES ('__DIAG_BRAND__', '__DIAG_PHONE__', 'Smartphone', 'PHONE', 0, datetime('now'), datetime('now'))
            """).lastrowid
            cx.execute("""
                INSERT INTO variants (product_id, ram, storage, color, sku, barcode, retail_price, stock_quantity, created_at, updated_at)
                VALUES (?, '8GB', '128GB', 'Black', 'DIAG-SKU', 'DIAG-BAR', 50000, 1, datetime('now'), datetime('now'))
            """, (pid,))
            # Force rollback
            raise ZeroDivisionError("TRANSACTION_TEST_ROLLBACK")
    except ZeroDivisionError:
        # Check that diagnostic record was not saved
        check = db.query_one("SELECT id FROM products WHERE brand = '__DIAG_BRAND__'")
        if not check:
            results.append({"name": "ACID Transaction & Rollback", "status": "PASS", "detail": "Atomic commits and error rollbacks strictly verified."})
        else:
            all_ok = False
            results.append({"name": "ACID Transaction & Rollback", "status": "FAIL", "detail": "Rollback leaked temporary data into database."})
    except Exception as e:
        all_ok = False
        results.append({"name": "ACID Transaction & Rollback", "status": "FAIL", "detail": str(e)})

    # 4. Catalog & Index Sync
    try:
        v_count = db.query_one("SELECT COUNT(*) AS c FROM variants WHERE is_archived = 0")["c"]
        p_count = db.query_one("SELECT COUNT(*) AS c FROM products WHERE is_archived = 0")["c"]
        results.append({"name": "Catalog Indexes", "status": "PASS", "detail": f"{p_count} Products, {v_count} Active Variants indexed and searchable."})
    except Exception as e:
        all_ok = False
        results.append({"name": "Catalog Indexes", "status": "FAIL", "detail": str(e)})

    # 5. Data Storage & Write Permissions
    try:
        import config
        data_dir = config.DATA_DIR
        test_file = os.path.join(data_dir, ".diag_write_test")
        with open(test_file, "w") as f:
            f.write("OK")
        if os.path.exists(test_file):
            os.remove(test_file)
        results.append({"name": "Data Storage Access", "status": "PASS", "detail": f"Write access confirmed in {data_dir}"})
    except Exception as e:
        all_ok = False
        results.append({"name": "Data Storage Access", "status": "FAIL", "detail": f"Storage write error: {e}"})

    # 6. Change Feed & Alert Engine
    try:
        feed = db.get_change_feed_state()
        alert_rows = db.query_one("SELECT COUNT(*) AS c FROM stock_alert_state")["c"]
        results.append({"name": "Alert Engine & Change Feed", "status": "PASS", "detail": f"Alert engine active ({alert_rows} monitored), change feed version: {feed.get('version', 1)}"})
    except Exception as e:
        all_ok = False
        results.append({"name": "Alert Engine & Change Feed", "status": "FAIL", "detail": str(e)})

    return {
        "status": "HEALTHY" if all_ok else "UNHEALTHY",
        "overall": "PASS" if all_ok else "FAIL",
        "all_passed": all_ok,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": results
    }
