# MOBILE & ACCESSORIES ERP — Generic Lookup Lists & Categories Service
import re
from datetime import datetime
import db

def normalize_lookup_key(text):
    if not text:
        return ""
    # Strip whitespace, lower case, remove non-alphanumeric
    cleaned = re.sub(r'[\s\-_.,/]+', '', str(text).strip().lower())
    return cleaned

def get_lookup_list(list_key, include_archived=False):
    sql = "SELECT id, list_key, label, sort_order, is_active, is_system, created_by, created_at, default_low_stock_level, default_reorder_qty FROM lookup_lists WHERE list_key = ?"
    params = [list_key]
    if not include_archived:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order ASC, label COLLATE NOCASE ASC"
    rows = db.query_all(sql, params)
    return rows

def get_lookup_item_by_id(item_id):
    return db.query_one("SELECT * FROM lookup_lists WHERE id = ?", (item_id,))

def find_duplicate_item(list_key, label):
    norm_target = normalize_lookup_key(label)
    items = get_lookup_list(list_key, include_archived=True)
    for it in items:
        if normalize_lookup_key(it["label"]) == norm_target:
            return it
    return None

def add_lookup_item(list_key, label, user_id=0, username="Admin", default_low_stock_level=None, default_reorder_qty=None):
    label = str(label).strip()
    if not label:
        return {"success": False, "error": "Label cannot be empty"}
    
    # Duplicate check
    existing = find_duplicate_item(list_key, label)
    if existing:
        if not existing["is_active"]:
            # Reactivate if it was archived
            db.execute("UPDATE lookup_lists SET is_active = 1 WHERE id = ?", (existing["id"],))
            existing["is_active"] = 1
        return {"success": True, "item": existing, "already_exists": True}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    max_sort_row = db.query_one("SELECT MAX(sort_order) as m FROM lookup_lists WHERE list_key = ?", (list_key,))
    next_sort = (max_sort_row["m"] or 0) + 10 if max_sort_row else 10

    acc_type = get_account_type(label) if list_key == "payment_account" else "CASH"
    new_id = db.execute("""
        INSERT INTO lookup_lists (list_key, label, sort_order, is_active, is_system, created_by, created_at, default_low_stock_level, default_reorder_qty, account_type)
        VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?, ?)
    """, (list_key, label, next_sort, user_id, now, default_low_stock_level, default_reorder_qty, acc_type))

    # Audit log
    db.execute("""
        INSERT INTO audit_log (user_id, username, action, entity, entity_id, old_value, new_value, timestamp)
        VALUES (?, ?, 'CREATE_LOOKUP', 'lookup_lists', ?, '', ?, ?)
    """, (user_id, username, str(new_id), f"{list_key}:{label}", now))

    new_item = get_lookup_item_by_id(new_id)
    return {"success": True, "item": new_item, "already_exists": False}

def update_lookup_item(item_id, new_label, user_id=0, username="Admin", default_low_stock_level=None, default_reorder_qty=None):
    new_label = str(new_label).strip()
    if not new_label:
        return {"success": False, "error": "Label cannot be empty"}
    
    current = get_lookup_item_by_id(item_id)
    if not current:
        return {"success": False, "error": "Lookup item not found"}
    
    # Check duplicate in same list excluding itself
    dup = find_duplicate_item(current["list_key"], new_label)
    if dup and dup["id"] != current["id"]:
        return {"success": False, "error": f"Item '{new_label}' already exists in this list"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_low = current["default_low_stock_level"] if default_low_stock_level is None else default_low_stock_level
    target_reorder = current["default_reorder_qty"] if default_reorder_qty is None else default_reorder_qty
    acc_type = get_account_type(new_label) if current["list_key"] == "payment_account" else current.get("account_type", "CASH")
    db.execute("""
        UPDATE lookup_lists 
        SET label = ?, default_low_stock_level = ?, default_reorder_qty = ?, account_type = ?
        WHERE id = ?
    """, (new_label, target_low, target_reorder, acc_type, item_id))

    db.execute("""
        INSERT INTO audit_log (user_id, username, action, entity, entity_id, old_value, new_value, timestamp)
        VALUES (?, ?, 'UPDATE_LOOKUP', 'lookup_lists', ?, ?, ?, ?)
    """, (user_id, username, str(item_id), current["label"], new_label, now))

    return {"success": True, "item": get_lookup_item_by_id(item_id)}

def archive_lookup_item(item_id, user_id=0, username="Admin"):
    current = get_lookup_item_by_id(item_id)
    if not current:
        return {"success": False, "error": "Lookup item not found"}
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE lookup_lists SET is_active = 0 WHERE id = ?", (item_id,))

    db.execute("""
        INSERT INTO audit_log (user_id, username, action, entity, entity_id, old_value, new_value, timestamp)
        VALUES (?, ?, 'ARCHIVE_LOOKUP', 'lookup_lists', ?, ?, 'is_active:0', ?)
    """, (user_id, username, str(item_id), current["label"], now))

    return {"success": True}

def restore_lookup_item(item_id, user_id=0, username="Admin"):
    current = get_lookup_item_by_id(item_id)
    if not current:
        return {"success": False, "error": "Lookup item not found"}
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE lookup_lists SET is_active = 1 WHERE id = ?", (item_id,))

    db.execute("""
        INSERT INTO audit_log (user_id, username, action, entity, entity_id, old_value, new_value, timestamp)
        VALUES (?, ?, 'RESTORE_LOOKUP', 'lookup_lists', ?, ?, 'is_active:1', ?)
    """, (user_id, username, str(item_id), current["label"], now))

    return {"success": True}

def bulk_add_lookup_items(list_key, lines_text, user_id=0, username="Admin"):
    lines = [line.strip() for line in lines_text.splitlines() if line.strip()]
    added = 0
    skipped = 0
    items = []
    for line in lines:
        res = add_lookup_item(list_key, line, user_id, username)
        if res.get("success"):
            if res.get("already_exists"):
                skipped += 1
            else:
                added += 1
            items.append(res["item"])
    return {"success": True, "added": added, "skipped": skipped, "items": items}

def get_item_usage_count(list_key, label):
    if not label:
        return 0
    try:
        if list_key == "brand":
            r = db.query_one("SELECT count(*) c FROM products WHERE brand = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "category":
            r = db.query_one("SELECT count(*) c FROM products WHERE category = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "condition":
            r = db.query_one("SELECT count(*) c FROM units WHERE condition = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "pta_status":
            r = db.query_one("SELECT count(*) c FROM units WHERE pta_status = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "expense_category":
            r = db.query_one("SELECT count(*) c FROM expenses WHERE category = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "technician":
            r = db.query_one("SELECT count(*) c FROM repair_jobs WHERE technician_name = ?", (label,))
            return r["c"] if r else 0
        elif list_key == "repair_complaint":
            r = db.query_one("SELECT count(*) c FROM repair_jobs WHERE complaint LIKE ?", (f"%{label}%",))
            return r["c"] if r else 0
    except Exception:
        pass
    return 0

def merge_lookup_items(list_key, source_id, target_id, user_id=0, username="Admin"):
    source = get_lookup_item_by_id(source_id)
    target = get_lookup_item_by_id(target_id)
    if not source or not target:
        return {"success": False, "error": "Source or target item not found"}
    
    src_label = source["label"]
    tgt_label = target["label"]

    with db.transaction() as cx:
        if list_key == "brand":
            cx.execute("UPDATE products SET brand = ? WHERE brand = ?", (tgt_label, src_label))
        elif list_key == "category":
            cx.execute("UPDATE products SET category = ? WHERE category = ?", (tgt_label, src_label))
        elif list_key == "expense_category":
            cx.execute("UPDATE expenses SET category = ? WHERE category = ?", (tgt_label, src_label))
        elif list_key == "technician":
            cx.execute("UPDATE repair_jobs SET technician_name = ? WHERE technician_name = ?", (tgt_label, src_label))
            cx.execute("UPDATE software_jobs SET technician_name = ? WHERE technician_name = ?", (tgt_label, src_label))

        # Archive the source item
        cx.execute("UPDATE lookup_lists SET is_active = 0 WHERE id = ?", (source_id,))

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cx.execute("""
            INSERT INTO audit_log (user_id, username, action, entity, entity_id, old_value, new_value, timestamp)
            VALUES (?, ?, 'MERGE_LOOKUP', 'lookup_lists', ?, ?, ?, ?)
        """, (user_id, username, str(source_id), src_label, f"Merged into {tgt_label} (ID {target_id})", now))

    return {"success": True, "message": f"Successfully merged '{src_label}' into '{tgt_label}'"}

# ═══════════════════════════════════════════════════════════
# CANONICAL PAYMENT ACCOUNTS & TYPES (FIX 2)
# ═══════════════════════════════════════════════════════════

ACCOUNT_TYPE_CASH = "CASH"
ACCOUNT_TYPE_BANK = "BANK"
ACCOUNT_TYPE_WALLET = "WALLET"

def get_account_type(account_str):
    """
    Canonical rule function: maps any payment account or payment method string
    to exactly one of: 'CASH', 'BANK', 'WALLET'.
    
    Rule:
    - 'Cash Drawer', 'CASH', 'cash', ' Cash ', 'counter', 'petty cash', empty/None -> 'CASH'
    - 'EasyPaisa', 'JazzCash', 'wallet', 'UPaisa', 'SadaPay', 'NayaPay' -> 'WALLET'
    - 'Bank', 'Online', 'Card', 'POS', 'Raast', 'Meezan', 'HBL', 'MCB', 'Alfalah', 'Allied', etc. -> 'BANK'
    """
    if not account_str:
        return ACCOUNT_TYPE_CASH
    s = str(account_str).strip().lower()
    if not s:
        return ACCOUNT_TYPE_CASH
    
    # 1. Heuristics for wallet (checked first so 'jazzcash' doesn't falsely match generic 'cash')
    if any(w in s for w in ["easypaisa", "jazzcash", "wallet", "upaisa", "sadapay", "nayapay"]):
        return ACCOUNT_TYPE_WALLET

    # 2. Heuristics for cash
    if "cash" in s or "drawer" in s or "counter" in s:
        return ACCOUNT_TYPE_CASH

    # 3. Heuristics for bank / card / online
    if any(b in s for b in ["bank", "card", "online", "raast", "alfalah", "meezan", "hbl", "mcb", "allied", "ubl", "askari", "faysal", "cheque", "pos", "transfer"]):
        return ACCOUNT_TYPE_BANK
    
    # 4. Check against active lookup_lists if explicitly configured
    try:
        row = db.query_one(
            "SELECT account_type FROM lookup_lists WHERE list_key = 'payment_account' AND LOWER(label) = ? AND is_active = 1",
            (s,)
        )
        if row and row.get("account_type"):
            return row["account_type"].upper()
    except Exception:
        pass

    # Default fallback
    return ACCOUNT_TYPE_CASH

def is_cash_account(account_str):
    """Returns True if the account/method represents physical drawer cash."""
    return get_account_type(account_str) == ACCOUNT_TYPE_CASH

def cash_type_of(account_str):
    """Alias for get_account_type."""
    return get_account_type(account_str)

def migrate_normalize_payment_accounts():
    """
    Idempotent migration:
    - Ensures account_type column exists on lookup_lists
    - Updates lookup_lists payment_account items with canonical account_type
    - Normalizes payment_method strings in expenses, sales, purchases, supplier_ledger, udhaar_ledger, returns
    - Reports total rows affected.
    """
    affected = 0
    with db.transaction() as cx:
        cur = cx.cursor()
        
        # 1. Ensure column in lookup_lists
        try:
            cur.execute("ALTER TABLE lookup_lists ADD COLUMN account_type TEXT DEFAULT 'CASH'")
        except Exception:
            pass

        # 2. Update lookup_lists payment_account items
        accs = cur.execute("SELECT id, label, account_type FROM lookup_lists WHERE list_key = 'payment_account'").fetchall()
        for a in accs:
            expected_type = get_account_type(a["label"])
            if (a["account_type"] or "").upper() != expected_type:
                cur.execute("UPDATE lookup_lists SET account_type = ? WHERE id = ?", (expected_type, a["id"]))
                affected += 1
                
        # 3. Normalize expenses with empty/null payment_method to 'Cash Drawer'
        cur.execute("UPDATE expenses SET payment_method = 'Cash Drawer' WHERE payment_method IS NULL OR TRIM(payment_method) = ''")
        affected += cur.rowcount
        
        # 4. Trim whitespace on expenses payment_method
        cur.execute("UPDATE expenses SET payment_method = TRIM(payment_method) WHERE payment_method != TRIM(payment_method)")
        affected += cur.rowcount
        
        # 5. Normalize supplier_ledger payment_method
        cur.execute("UPDATE supplier_ledger SET payment_method = 'Cash Drawer' WHERE payment_method IS NULL OR TRIM(payment_method) = ''")
        affected += cur.rowcount
        cur.execute("UPDATE supplier_ledger SET payment_method = TRIM(payment_method) WHERE payment_method != TRIM(payment_method)")
        affected += cur.rowcount

        # 6. Normalize udhaar_ledger payment_method
        cur.execute("UPDATE udhaar_ledger SET payment_method = 'Cash Drawer' WHERE payment_method IS NULL OR TRIM(payment_method) = ''")
        affected += cur.rowcount
        cur.execute("UPDATE udhaar_ledger SET payment_method = TRIM(payment_method) WHERE payment_method != TRIM(payment_method)")
        affected += cur.rowcount

        # 7. Normalize returns refund_type
        cur.execute("UPDATE returns SET refund_type = 'CASH' WHERE refund_type IS NULL OR TRIM(refund_type) = ''")
        affected += cur.rowcount
        cur.execute("UPDATE returns SET refund_type = TRIM(refund_type) WHERE refund_type != TRIM(refund_type)")
        affected += cur.rowcount

    return {"success": True, "rows_affected": affected}

