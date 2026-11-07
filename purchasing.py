# MOBILE & ACCESSORIES ERP — Purchasing, Receiving & Supplier Ledger Engine
import json
from datetime import datetime
import db, auth, scanner, alert_engine, accounting

# ═══════════════════════════════════════════════════════════
# 1. SUPPLIERS CRUD
# ═══════════════════════════════════════════════════════════

def create_supplier(name, phone="", address="", email="", company="", notes="", user_id=0, username=""):
    """Creates a new supplier."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sid = db.execute("""
        INSERT INTO suppliers (name, phone, address, email, company, total_purchased, total_paid, balance, notes, is_archived, created_at)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, 0, ?)
    """, (name.strip(), phone.strip(), address.strip(), email.strip(), company.strip(), notes.strip(), now))
    
    auth.log_audit(user_id, username, "CREATE_SUPPLIER", "suppliers", str(sid), "", f"Created supplier: {name}")
    return sid

def update_supplier(supplier_id, name, phone="", address="", email="", company="", notes="", user_id=0, username=""):
    """Updates supplier information."""
    db.execute("""
        UPDATE suppliers SET name = ?, phone = ?, address = ?, email = ?, company = ?, notes = ?
        WHERE id = ?
    """, (name.strip(), phone.strip(), address.strip(), email.strip(), company.strip(), notes.strip(), supplier_id))
    
    auth.log_audit(user_id, username, "UPDATE_SUPPLIER", "suppliers", str(supplier_id), "", f"Updated supplier: {name}")
    return True

def get_supplier(supplier_id):
    """Retrieves single supplier record."""
    return db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))

def list_suppliers(search="", limit=100):
    """Lists suppliers with optional name/phone/company search."""
    if search:
        s = f"%{search.strip()}%"
        return db.query_all("""
            SELECT * FROM suppliers 
            WHERE is_archived = 0 AND (name LIKE ? OR phone LIKE ? OR company LIKE ?)
            ORDER BY name ASC LIMIT ?
        """, (s, s, s, limit))
    return db.query_all("SELECT * FROM suppliers WHERE is_archived = 0 ORDER BY name ASC LIMIT ?", (limit,))

def delete_or_archive_supplier(supplier_id, user_id=0, username=""):
    """
    Deletes supplier if no purchase history/ledger; otherwise archives safely.
    """
    sup = db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
    if not sup:
        return {"success": False, "status": 404, "message": "Supplier not found"}

    p_count = db.query_one("SELECT COUNT(*) AS c FROM purchases WHERE supplier_id = ?", (supplier_id,))["c"]
    l_count = db.query_one("SELECT COUNT(*) AS c FROM supplier_ledger WHERE supplier_id = ?", (supplier_id,))["c"]

    if p_count > 0 or l_count > 0 or sup.get("balance", 0) != 0:
        db.execute("UPDATE suppliers SET is_archived = 1 WHERE id = ?", (supplier_id,))
        auth.log_audit(user_id, username, "ARCHIVE_SUPPLIER", "suppliers", str(supplier_id), "", f"Archived supplier '{sup['name']}' (has {p_count} purchases, {l_count} ledger rows)")
        return {"success": True, "action": "ARCHIVED", "message": f"Supplier '{sup['name']}' has transaction history and has been safely archived."}
    else:
        db.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        auth.log_audit(user_id, username, "DELETE_SUPPLIER", "suppliers", str(supplier_id), "", f"Deleted supplier '{sup['name']}'")
        return {"success": True, "action": "DELETED", "message": f"Supplier '{sup['name']}' permanently deleted."}

def restore_supplier(supplier_id, user_id=0, username=""):
    """Restores an archived supplier."""
    sup = db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
    if not sup:
        return {"success": False, "status": 404, "message": "Supplier not found"}
    db.execute("UPDATE suppliers SET is_archived = 0 WHERE id = ?", (supplier_id,))
    auth.log_audit(user_id, username, "RESTORE_SUPPLIER", "suppliers", str(supplier_id), "", f"Restored supplier '{sup['name']}'")
    return {"success": True, "action": "RESTORED", "message": f"Supplier '{sup['name']}' restored successfully."}

# ═══════════════════════════════════════════════════════════
# 2. PURCHASE RECEIVING (BULK PHONE SCANNING & ACCESSORIES)
# ═══════════════════════════════════════════════════════════

def create_purchase(supplier_id, items, invoice_no="", purchase_date=None, 
                    paid_amount=0, payment_method="CASH", notes="", backdate_reason="", user_id=0, username=""):
    """
    Executes a purchase order / goods receiving in an ACID transaction:
    - Phones: Validates IMEIs, creates units in stock, logs stock ledger.
    - Accessories/Parts: Increments variant stock quantity, logs stock ledger.
    - Updates supplier balance and writes supplier ledger transaction.
    - Dual timestamps & backdating validation supported.
    """
    if not items:
        return {"success": False, "error": "No items provided in purchase"}

    sup = get_supplier(supplier_id)
    if not sup:
        return {"success": False, "error": f"Supplier #{supplier_id} not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    t_val = accounting.validate_backdate_entry(purchase_date, user_id=user_id, username=username, reason=backdate_reason, entity="purchases")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    purch_date = t_val["target_date"]
    clean_backdate_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    with db.transaction() as cx:
        cur = cx.cursor()

        # Generate purchase invoice number if not provided
        if not invoice_no:
            cur.execute("SELECT COUNT(*) AS c FROM purchases WHERE created_at LIKE ?", (f"{now[:10]}%",))
            seq = cur.fetchone()["c"] + 1
            invoice_no = f"PUR-{date_str}-{seq:04d}"

        total_purchase_amount = 0.0

        # Step A: Validate and prepare items
        validated_items = []
        for it in items:
            itype = it.get("item_type", "PHONE").upper()
            vid = it.get("variant_id")
            cur.execute("""
                SELECT v.id AS variant_id, v.product_id, v.wholesale_price, p.name AS product_name, p.brand, p.item_type AS prod_type
                FROM variants v
                JOIN products p ON v.product_id = p.id
                WHERE v.id = ?
            """, (vid,))
            vrow = cur.fetchone()
            if not vrow:
                return {"success": False, "error": f"Variant #{vid} not found"}

            unit_cost = float(it.get("unit_cost", 0))

            if itype == "PHONE":
                imeis = it.get("imeis", [])
                if not imeis:
                    return {"success": False, "error": f"No IMEIs provided for phone variant #{vid}"}
                
                # Check for existing duplicate IMEIs in DB
                for imei_info in imeis:
                    i1 = str(imei_info.get("imei1", "")).strip()
                    i2 = str(imei_info.get("imei2", "")).strip()
                    if not i1:
                        return {"success": False, "error": "IMEI 1 is required for phone unit"}
                    
                    cur.execute("SELECT id, imei1, status FROM units WHERE imei1 = ? OR imei2 = ?", (i1, i1))
                    dup = cur.fetchone()
                    if dup:
                        return {"success": False, "error": f"IMEI {i1} already exists in database (Unit #{dup['id']}, status: {dup['status']})"}

                    if i2:
                        cur.execute("SELECT id, imei1, status FROM units WHERE imei1 = ? OR imei2 = ?", (i2, i2))
                        dup2 = cur.fetchone()
                        if dup2:
                            return {"success": False, "error": f"IMEI 2 {i2} already exists in database (Unit #{dup2['id']})"}

                item_total = unit_cost * len(imeis)
                total_purchase_amount += item_total
                validated_items.append({
                    "item_type": "PHONE",
                    "variant_id": vid,
                    "product_id": vrow["product_id"],
                    "qty": len(imeis),
                    "unit_cost": unit_cost,
                    "total_cost": item_total,
                    "imeis": imeis
                })

            else:
                # Accessory or Spare Part
                qty = int(it.get("qty", 1))
                if qty <= 0:
                    return {"success": False, "error": "Quantity must be greater than 0"}
                item_total = unit_cost * qty
                total_purchase_amount += item_total
                validated_items.append({
                    "item_type": itype,
                    "variant_id": vid,
                    "product_id": vrow["product_id"],
                    "qty": qty,
                    "unit_cost": unit_cost,
                    "total_cost": item_total,
                    "imeis": []
                })

        paid = float(paid_amount)
        balance_due = total_purchase_amount - paid

        # Step B: Insert into purchases table
        cur.execute("""
            INSERT INTO purchases (invoice_no, supplier_id, supplier_name, total_amount, paid_amount, balance_amount, payment_method, status, purchase_date, transaction_date, recorded_at, backdate_reason, notes, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?, ?, ?, ?, ?, ?)
        """, (invoice_no, supplier_id, sup["name"], total_purchase_amount, paid, balance_due, payment_method, purch_date, purch_date, now, clean_backdate_reason, notes, user_id, now))
        purchase_id = cur.lastrowid

        # Step C: Insert items & update inventory
        for vitem in validated_items:
            cur.execute("""
                INSERT INTO purchase_items (purchase_id, variant_id, item_type, qty, unit_cost, total_cost, imeis_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (purchase_id, vitem["variant_id"], vitem["item_type"], vitem["qty"], vitem["unit_cost"], vitem["total_cost"], json.dumps(vitem["imeis"]), now))

            if vitem["item_type"] == "PHONE":
                for uinfo in vitem["imeis"]:
                    i1 = str(uinfo.get("imei1", "")).strip()
                    i2 = str(uinfo.get("imei2", "")).strip() or None
                    sno = str(uinfo.get("serial_no", "")).strip() or None
                    cond = uinfo.get("condition", "NEW_BOX_PACK")
                    pta = uinfo.get("pta_status", "PTA_APPROVED")
                    bhealth = int(uinfo.get("battery_health", 100))
                    unotes = uinfo.get("notes", "")

                    cur.execute("""
                        INSERT INTO units (variant_id, imei1, imei2, serial_no, condition, pta_status, cost_price, supplier_id, purchase_ref, purchase_id, date_in, battery_health, notes, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_STOCK', ?, ?)
                    """, (vitem["variant_id"], i1, i2, sno, cond, pta, vitem["unit_cost"], supplier_id, invoice_no, purchase_id, purch_date, bhealth, unotes, now, now))
                    unit_id = cur.lastrowid

                    cur.execute("""
                        INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, transaction_date, recorded_at, timestamp)
                        VALUES (?, ?, ?, ?, 'PHONE', 1, 1, 'PURCHASE', ?, ?, ?, ?, ?, ?)
                    """, (vitem["product_id"], vitem["variant_id"], unit_id, i1, invoice_no, f"Received from {sup['name']}", user_id, purch_date, now, now))

                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ?
                    WHERE id = ?
                """, (vitem["variant_id"], now, vitem["variant_id"]))

            else:
                # Increment accessory / spare part stock
                cur.execute("""
                    UPDATE variants SET stock_quantity = stock_quantity + ?, updated_at = ?
                    WHERE id = ?
                """, (vitem["qty"], now, vitem["variant_id"]))
                
                cur.execute("SELECT stock_quantity FROM variants WHERE id = ?", (vitem["variant_id"],))
                new_stock = cur.fetchone()["stock_quantity"]

                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, transaction_date, recorded_at, timestamp)
                    VALUES (?, ?, 0, '', ?, ?, ?, 'PURCHASE', ?, ?, ?, ?, ?, ?)
                """, (vitem["product_id"], vitem["variant_id"], vitem["item_type"], vitem["qty"], new_stock, invoice_no, f"Received from {sup['name']}", user_id, purch_date, now, now))

        # Step D: Update Supplier Ledger & Outstanding Balance
        new_sup_balance = sup["balance"] + balance_due
        cur.execute("""
            UPDATE suppliers 
            SET total_purchased = total_purchased + ?, total_paid = total_paid + ?, balance = ?
            WHERE id = ?
        """, (total_purchase_amount, paid, new_sup_balance, supplier_id))

        # Log purchase debit in supplier ledger
        cur.execute("""
            INSERT INTO supplier_ledger (supplier_id, transaction_type, amount, balance_after, payment_method, reference, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
            VALUES (?, 'PURCHASE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (supplier_id, total_purchase_amount, sup["balance"] + total_purchase_amount, payment_method, invoice_no, f"Goods Received (Bill #{invoice_no})", user_id, purch_date, now, clean_backdate_reason, now))

        if paid > 0:
            cur.execute("""
                INSERT INTO supplier_ledger (supplier_id, transaction_type, amount, balance_after, payment_method, reference, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
                VALUES (?, 'PAYMENT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (supplier_id, paid, new_sup_balance, payment_method, invoice_no, f"Paid against Bill #{invoice_no}", user_id, purch_date, now, clean_backdate_reason, now))

        # Step E: Update alert states and clear on-order tracking
        affected_vids = list(set([vitem["variant_id"] for vitem in validated_items if vitem.get("variant_id")]))
        if affected_vids:
            alert_engine.evaluate_stock_transitions(cx, affected_vids, user_id=user_id, action_trigger="PURCHASE", reference=invoice_no)
            for vitem in validated_items:
                alert_engine.clear_on_order_on_receipt(cx, vitem["variant_id"], vitem["qty"])

    auth.log_audit(user_id, username, "RECEIVE_PURCHASE", "purchases", str(purchase_id), "", f"Received bill #{invoice_no} total Rs. {total_purchase_amount:,.0f} from {sup['name']}")
    return {
        "success": True,
        "purchase_id": purchase_id,
        "invoice_no": invoice_no,
        "total_amount": total_purchase_amount,
        "paid_amount": paid,
        "balance_due": balance_due,
        "new_supplier_balance": new_sup_balance
    }

# ═══════════════════════════════════════════════════════════
# 3. SUPPLIER PAYMENTS & RETURN TO SUPPLIER
# ═══════════════════════════════════════════════════════════

def record_supplier_payment(supplier_id, amount, payment_method="CASH", reference="", notes="", payment_date=None, backdate_reason="", user_id=0, username=""):
    """Records a payment made to a supplier (Cash, Bank Transfer, Cheque) with dual timestamps."""
    if float(amount) <= 0:
        return {"success": False, "error": "Payment amount must be positive"}

    sup = get_supplier(supplier_id)
    if not sup:
        return {"success": False, "error": f"Supplier #{supplier_id} not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amt = float(amount)

    t_val = accounting.validate_backdate_entry(payment_date, user_id=user_id, username=username, reason=backdate_reason, entity="supplier_ledger")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    trans_date = t_val["target_date"]
    clean_backdate_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    with db.transaction() as cx:
        cur = cx.cursor()
        new_balance = sup["balance"] - amt
        cur.execute("""
            UPDATE suppliers 
            SET total_paid = total_paid + ?, balance = ?
            WHERE id = ?
        """, (amt, new_balance, supplier_id))

        cur.execute("""
            INSERT INTO supplier_ledger (supplier_id, transaction_type, amount, balance_after, payment_method, reference, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
            VALUES (?, 'PAYMENT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (supplier_id, amt, new_balance, payment_method, reference, notes, user_id, trans_date, now, clean_backdate_reason, now))
        ledger_id = cur.lastrowid

    auth.log_audit(user_id, username, "SUPPLIER_PAYMENT", "supplier_ledger", str(ledger_id), "", f"Paid Rs. {amt:,.0f} to {sup['name']} on {trans_date}")
    return {"success": True, "ledger_id": ledger_id, "amount": amt, "new_balance": new_balance, "transaction_date": trans_date}

def return_to_supplier(supplier_id, items, debit_amount, reason="", user_id=0, username=""):
    """
    Returns defective or unsold units/goods to supplier (Debit Note).
    - Unit status marked 'RETURNED_TO_SUPPLIER'.
    - Accessory stock decremented.
    - Supplier balance reduced by debit_amount.
    """
    sup = get_supplier(supplier_id)
    if not sup:
        return {"success": False, "error": f"Supplier #{supplier_id} not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    debit = float(debit_amount)

    with db.transaction() as cx:
        cur = cx.cursor()

        for it in items:
            itype = it.get("item_type", "PHONE")
            if itype == "PHONE":
                unit_id = it.get("unit_id")
                cur.execute("SELECT * FROM units WHERE id = ?", (unit_id,))
                u = cur.fetchone()
                if not u:
                    return {"success": False, "error": f"Unit #{unit_id} not found"}
                if u["status"] != "IN_STOCK" and u["status"] != "DEFECTIVE":
                    return {"success": False, "error": f"Unit #{unit_id} cannot be returned (status: {u['status']})"}

                cur.execute("UPDATE units SET status = 'RETURNED_TO_SUPPLIER', updated_at = ? WHERE id = ?", (now, unit_id))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ?
                    WHERE id = ?
                """, (u["variant_id"], now, u["variant_id"]))
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (0, ?, ?, ?, 'PHONE', -1, 0, 'RETURN_TO_SUPPLIER', ?, ?, ?, ?)
                """, (u["variant_id"], unit_id, u["imei1"], f"SUP-{supplier_id}", reason, user_id, now))

            else:
                vid = it.get("variant_id")
                qty = int(it.get("qty", 1))
                cur.execute("UPDATE variants SET stock_quantity = stock_quantity - ?, updated_at = ? WHERE id = ?", (qty, now, vid))
                cur.execute("SELECT stock_quantity FROM variants WHERE id = ?", (vid,))
                new_stk = cur.fetchone()["stock_quantity"]
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
                    VALUES (0, ?, 0, '', ?, ?, ?, 'RETURN_TO_SUPPLIER', ?, ?, ?, ?)
                """, (vid, itype, -qty, new_stk, f"SUP-{supplier_id}", reason, user_id, now))

        new_balance = sup["balance"] - debit
        cur.execute("""
            UPDATE suppliers SET total_purchased = total_purchased - ?, balance = ? WHERE id = ?
        """, (debit, new_balance, supplier_id))

        cur.execute("""
            INSERT INTO supplier_ledger (supplier_id, transaction_type, amount, balance_after, payment_method, reference, notes, user_id, timestamp)
            VALUES (?, 'RETURN', ?, ?, 'DEBIT_NOTE', '', ?, ?, ?)
        """, (supplier_id, debit, new_balance, reason, user_id, now))
        ledger_id = cur.lastrowid

        # Re-evaluate stock transitions for returned items
        ret_vids = []
        for it in items:
            vid = it.get("variant_id")
            if not vid and it.get("unit_id"):
                cur.execute("SELECT variant_id FROM units WHERE id = ?", (it["unit_id"],))
                urow = cur.fetchone()
                if urow:
                    vid = urow["variant_id"]
            if vid:
                ret_vids.append(vid)
        if ret_vids:
            alert_engine.evaluate_stock_transitions(cx, list(set(ret_vids)), user_id=user_id, action_trigger="RETURN_TO_SUPPLIER", reference=f"SUP-{supplier_id}")

    auth.log_audit(user_id, username, "RETURN_TO_SUPPLIER", "supplier_ledger", str(ledger_id), "", f"Returned goods to {sup['name']}, Debit Rs. {debit:,.0f}")
    return {"success": True, "ledger_id": ledger_id, "new_balance": new_balance}

def get_supplier_ledger(supplier_id):
    """Retrieves chronological ledger transactions for a supplier."""
    sup = get_supplier(supplier_id)
    if not sup:
        return {"success": False, "error": "Supplier not found"}
    
    rows = db.query_all("""
        SELECT * FROM supplier_ledger 
        WHERE supplier_id = ? 
        ORDER BY timestamp ASC, id ASC
    """, (supplier_id,))
    return {"success": True, "supplier": sup, "transactions": rows}

def list_purchases(supplier_id=None, limit=100):
    """Lists recent purchases with supplier information."""
    if supplier_id:
        return db.query_all("""
            SELECT p.*, s.phone AS supplier_phone
            FROM purchases p
            JOIN suppliers s ON p.supplier_id = s.id
            WHERE p.supplier_id = ?
            ORDER BY p.id DESC LIMIT ?
        """, (supplier_id, limit))
    return db.query_all("""
        SELECT p.*, s.phone AS supplier_phone
        FROM purchases p
        JOIN suppliers s ON p.supplier_id = s.id
        ORDER BY p.id DESC LIMIT ?
    """, (limit,))

def void_purchase(purchase_id, reason="", user_id=0, username=""):
    """
    Voids a purchase order with full inventory reversal and supplier ledger adjustment.
    Refuses if any purchased phone unit is already SOLD.
    """
    purch = db.query_one("SELECT * FROM purchases WHERE id = ?", (purchase_id,))
    if not purch:
        return {"success": False, "error": "Purchase not found"}
    if purch.get("status") == "VOIDED":
        return {"success": False, "error": "Purchase is already voided"}

    # Check if any unit from this purchase was already SOLD
    sold_u = db.query_one("SELECT COUNT(*) AS c FROM units WHERE purchase_id = ? AND status != 'IN_STOCK'", (purchase_id,))
    if sold_u and sold_u["c"] > 0:
        return {"success": False, "error": f"Cannot void purchase: {sold_u['c']} phone units from this intake have already been sold or altered."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cur = cx.cursor()
        p_items = db.query_all("SELECT * FROM purchase_items WHERE purchase_id = ?", (purchase_id,))
        for pi in p_items:
            vid = pi["variant_id"]
            itype = pi.get("item_type", "PHONE")
            qty = pi["qty"]
            if itype == "PHONE":
                cur.execute("DELETE FROM units WHERE purchase_id = ?", (purchase_id,))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ?
                    WHERE id = ?
                """, (vid, now, vid))
            else:
                cur.execute("UPDATE variants SET stock_quantity = MAX(0, stock_quantity - ?), updated_at = ? WHERE id = ?", (qty, now, vid))
            
            cur.execute("""
                INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, user_id, timestamp, transaction_date, recorded_at)
                VALUES (0, ?, 0, '', ?, -?, 0, 'VOID_PURCHASE', ?, ?, ?, ?, ?)
            """, (vid, itype, qty, purch["invoice_no"], user_id, now, now[:10], now))

        # Reverse supplier balance
        sup_id = purch["supplier_id"]
        if sup_id:
            balance_charge = purch["total_amount"] - purch["paid_amount"]
            cur.execute("UPDATE suppliers SET total_purchased = total_purchased - ?, total_paid = total_paid - ?, balance = balance - ? WHERE id = ?",
                        (purch["total_amount"], purch["paid_amount"], balance_charge, sup_id))
            sup_now = cur.execute("SELECT balance FROM suppliers WHERE id = ?", (sup_id,)).fetchone()
            cur.execute("""
                INSERT INTO supplier_ledger (supplier_id, transaction_type, amount, balance_after, payment_method, reference, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
                VALUES (?, 'VOID_PURCHASE', ?, ?, ?, ?, ?, ?, ?, ?, '', ?)
            """, (sup_id, -purch["total_amount"], sup_now["balance"] if sup_now else 0, purch["payment_method"], purch["invoice_no"], f"Voided {purch['invoice_no']}: {reason}", user_id, now[:10], now, now))

        cur.execute("UPDATE purchases SET status = 'VOIDED', notes = notes || ? WHERE id = ?", (f" [VOIDED: {reason}]", purchase_id))

    auth.log_audit(user_id, username, "VOID_PURCHASE", "purchases", str(purchase_id), "", f"Invoice: {purch['invoice_no']}, Reason: {reason}")
    return {"success": True, "message": f"Purchase {purch['invoice_no']} voided and inventory reversed."}
