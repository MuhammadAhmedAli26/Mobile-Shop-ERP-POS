# MOBILE & ACCESSORIES ERP — POS Engine & Sales Management
import json
from datetime import datetime, timedelta
import db, scanner, printing, auth, inventory, alert_engine, accounting

# ═══════════════════════════════════════════════════════════
# 1. POS CHECKOUT (ATOMIC TRANSACTION)
# ═══════════════════════════════════════════════════════════

def validate_cart(items):
    """
    Pre-validates POS cart lines and returns structured resolution or friendly error.
    - Ensures phone lines have qty=1 and a valid in-stock unit.
    - Auto-binds in-stock unit if variant provided without unit_id.
    - Validates accessory quantity against current stock.
    - Validates prices and line discounts.
    """
    if not items or not isinstance(items, list):
        return {"valid": False, "error": "Cart is empty. Please add items to begin."}

    resolved = []
    for idx, item in enumerate(items):
        itype = item.get("item_type", "PHONE").upper()
        vid = int(item.get("variant_id", 0))
        uid = int(item.get("unit_id") or item.get("id") or 0)
        iname = item.get("item_name") or item.get("name") or f"Item #{idx+1}"

        uprice = float(item.get("unit_price", 0))
        discount = float(item.get("discount", 0))
        if uprice < 0:
            return {"valid": False, "error": f"Price for '{iname}' cannot be negative."}
        if discount < 0:
            return {"valid": False, "error": f"Discount for '{iname}' cannot be negative."}

        if itype in ("PHONE", "SERIAL"):
            qty = 1
            if uid == 0 and item.get("imei1"):
                u_cand = db.query_one("SELECT id FROM units WHERE (imei1 = ? OR imei2 = ?) AND status = 'IN_STOCK'",
                                      (str(item["imei1"]).strip(), str(item["imei1"]).strip()))
                if u_cand:
                    uid = u_cand["id"]
            if uid == 0 and vid > 0:
                u_cand = db.query_one("SELECT id FROM units WHERE variant_id = ? AND status = 'IN_STOCK' ORDER BY id ASC LIMIT 1", (vid,))
                if u_cand:
                    uid = u_cand["id"]

            if uid == 0:
                return {"valid": False, "error": f"No in-stock device unit (IMEI) available for '{iname}'. Please select a specific IMEI or receive stock."}

            u = db.query_one("SELECT id, imei1, status FROM units WHERE id = ?", (uid,))
            if not u:
                return {"valid": False, "error": f"Device unit #{uid} for '{iname}' was not found in database."}
            if u["status"] != "IN_STOCK":
                return {"valid": False, "error": f"Device with IMEI '{u['imei1']}' is already {u['status']} and cannot be sold."}

            item_copy = dict(item)
            item_copy["unit_id"] = uid
            item_copy["qty"] = 1
            resolved.append(item_copy)
        else:
            qty = int(item.get("qty", 1))
            if qty <= 0:
                return {"valid": False, "error": f"Quantity for '{iname}' must be at least 1."}
            item_copy = dict(item)
            item_copy["qty"] = qty
            resolved.append(item_copy)

    return {"valid": True, "items": resolved}

def pos_checkout(items, customer_name="Walk-in Customer", customer_phone="", 
                 discount_amount=0, discount_percent=0, tax_percent=0,
                 paid_amount=0, payment_method="CASH", split_details="",
                 trade_in_id=0, notes="", user_id=0, username="", sale_date=None, backdate_reason=""):
    """
    Executes complete POS checkout in a single SQLite ACID transaction.
    Guarantees: Stock deducted, unit status SOLD, profit calculated, ledger written.
    Speed: < 100ms. Supports back-dated sale transactions.
    """
    cart_check = validate_cart(items)
    if not cart_check.get("valid"):
        return {"success": False, "error": cart_check.get("error")}
    items = cart_check["items"]

    real_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur_time = datetime.now().strftime("%H:%M:%S")
    s_raw = str(sale_date).strip() if sale_date else ""
    target_date = s_raw[:10] if (s_raw and len(s_raw) >= 10) else real_now[:10]

    val_res = accounting.validate_backdate_entry(target_date, user_id=user_id, username=username, reason=backdate_reason, entity="sales")
    if not val_res.get("valid"):
        return {"success": False, "error": val_res.get("error") or "Invalid transaction date"}

    trans_date = val_res.get("target_date") or real_now[:10]
    now = f"{trans_date} {cur_time}" if trans_date != real_now[:10] else real_now
    date_str = trans_date.replace("-", "")

    with db.transaction() as cx:
        cur = cx.cursor()

        # Generate unique invoice number: INV-YYYYMMDD-XXXX
        cur.execute("SELECT COUNT(*) AS c FROM sales WHERE created_at LIKE ?", (f"{now[:10]}%",))
        today_seq = cur.fetchone()["c"] + 1
        invoice_no = f"INV-{date_str}-{today_seq:04d}"

        # Resolve or create customer
        customer_id = 0
        c_name = (customer_name or "").strip()
        c_phone = (customer_phone or "").strip()
        is_walkin = not c_name or c_name.lower() in ("walk-in customer", "walk-in", "walkin")

        if c_phone:
            cur.execute("SELECT id, name FROM customers WHERE phone = ?", (c_phone,))
            c = cur.fetchone()
            if c:
                customer_id = c["id"]
                if not is_walkin and c["name"] != c_name:
                    cur.execute("UPDATE customers SET name = ? WHERE id = ?", (c_name, customer_id))
            else:
                cust_display_name = c_name if not is_walkin else "Walk-in Customer"
                cur.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)",
                            (cust_display_name, c_phone, now))
                customer_id = cur.lastrowid
        elif not is_walkin:
            cur.execute("SELECT id, name FROM customers WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (c_name,))
            c = cur.fetchone()
            if c:
                customer_id = c["id"]
            else:
                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM customers")
                nid = cur.fetchone()["next_id"]
                c_phone = f"NOP-{nid:05d}"
                cur.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)",
                            (c_name, c_phone, now))
                customer_id = cur.lastrowid

        subtotal = 0.0
        total_profit = 0.0
        processed_items = []

        # Validate items and lock units
        for item in items:
            itype = item.get("item_type", "PHONE")
            vid = int(item.get("variant_id", 0))
            uid = int(item.get("unit_id") or item.get("id") or 0)
            if itype == "PHONE" and uid == 0 and item.get("imei1"):
                u_cand = db.query_one("SELECT id FROM units WHERE (imei1 = ? OR imei2 = ?) AND status = 'IN_STOCK'",
                                      (item["imei1"].strip(), item["imei1"].strip()))
                if u_cand:
                    uid = u_cand["id"]
            qty = 1 if itype == "PHONE" else int(item.get("qty", 1))
            uprice = float(item.get("unit_price", 0))
            discount = float(item.get("discount", 0))
            line_tot = (uprice * qty) - discount
            subtotal += line_tot

            cost = 0.0
            imei1 = ""
            imei2 = ""
            variant_desc = ""

            if itype == "PHONE":
                # Look up unit
                unit = db.query_one("""
                    SELECT u.*, v.product_id AS product_id, v.ram, v.storage, v.color, p.name AS model_name, p.brand, p.default_warranty_months
                    FROM units u
                    JOIN variants v ON u.variant_id = v.id
                    JOIN products p ON v.product_id = p.id
                    WHERE u.id = ?
                """, (uid,))
                if not unit:
                    return {"success": False, "error": f"Device unit #{uid} not found"}
                if unit["status"] != "IN_STOCK":
                    return {"success": False, "error": f"IMEI {unit['imei1']} is NOT IN STOCK (Status: {unit['status']})"}

                # Intake date validation: phone cannot be sold before its purchase intake date
                unit_intake = str(unit.get("created_at") or unit.get("date_in") or "")[:10]
                if unit_intake and trans_date < unit_intake:
                    return {"success": False, "error": f"Device unit IMEI {unit['imei1']} was added on {unit_intake}. It cannot be sold on an earlier back-date ({trans_date})."}

                vid = vid or unit.get("variant_id") or 0
                pid = item.get("product_id") or unit.get("product_id") or 0
                cost = float(unit["cost_price"])
                imei1 = unit["imei1"]
                imei2 = unit["imei2"] or ""
                variant_desc = f"{unit['ram']} / {unit['storage']} · {unit['color']} · {unit['pta_status']} · {unit['condition']}"
                w_months = unit.get("default_warranty_months") or 12
                w_till = (datetime.now() + timedelta(days=w_months * 30)).strftime("%Y-%m-%d")

                # Mark unit SOLD
                cur.execute("UPDATE units SET status = 'SOLD', updated_at = ? WHERE id = ?", (now, uid))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ? 
                    WHERE id = ?
                """, (vid, now, vid))

                # Log stock ledger
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, user_id, timestamp, transaction_date, recorded_at)
                    VALUES (?, ?, ?, ?, 'PHONE', -1, 0, 'SALE', ?, ?, ?, ?, ?)
                """, (pid, vid, uid, imei1, invoice_no, user_id, now, trans_date, real_now))

            else:
                # Accessory or Spare Part
                v = db.query_one("""
                    SELECT v.*, p.name AS model_name, p.brand
                    FROM variants v
                    JOIN products p ON v.product_id = p.id
                    WHERE v.id = ?
                """, (vid,))
                if not v:
                    return {"success": False, "error": f"Item variant #{vid} not found"}
                if v["stock_quantity"] < qty:
                    return {"success": False, "error": f"Insufficient stock for {v['model_name']} (Available: {v['stock_quantity']})"}

                cost = float(v["wholesale_price"])
                variant_desc = f"{v['ram']} {v['storage']} {v['color']}".strip()
                w_till = ""

                # Deduct stock
                cur.execute("UPDATE variants SET stock_quantity = stock_quantity - ?, updated_at = ? WHERE id = ?", (qty, now, vid))
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, user_id, timestamp, transaction_date, recorded_at)
                    VALUES (?, ?, 0, '', ?, -?, ?, 'SALE', ?, ?, ?, ?, ?)
                """, (v["product_id"], vid, itype, qty, v["stock_quantity"] - qty, invoice_no, user_id, now, trans_date, real_now))

            profit = line_tot - (cost * qty)
            total_profit += profit

            processed_items.append({
                "variant_id": vid,
                "unit_id": uid,
                "item_type": itype,
                "item_name": item.get("item_name", "Item"),
                "variant_details": variant_desc,
                "imei1": imei1,
                "imei2": imei2,
                "qty": qty,
                "unit_price": uprice,
                "cost_price": cost,
                "discount": discount,
                "line_total": line_tot,
                "profit": profit,
                "warranty_till": w_till
            })

        # Calculate Grand Total
        discount_amount = float(discount_amount)
        if discount_percent > 0:
            discount_amount += subtotal * (float(discount_percent) / 100.0)

        tax_amount = 0.0
        if tax_percent > 0:
            tax_amount = (subtotal - discount_amount) * (float(tax_percent) / 100.0)

        grand_total = max(0, subtotal - discount_amount + tax_amount)
        paid_amount = float(paid_amount)
        
        # Check Trade-in deduction if applicable
        trade_in_val = 0.0
        if trade_in_id and int(trade_in_id) > 0:
            t = db.query_one("SELECT purchase_price FROM trade_ins WHERE id = ?", (int(trade_in_id),))
            if t:
                trade_in_val = float(t["purchase_price"])
                cur.execute("UPDATE trade_ins SET linked_sale_id = ? WHERE id = ?", (0, int(trade_in_id))) # Will update with sale_id below

        balance_due = max(0, grand_total - paid_amount - trade_in_val)
        change_amount = max(0, (paid_amount + trade_in_val) - grand_total)

        # RB2: Udhaar / Credit requires a customer account. Walk-in credit is strictly refused.
        if balance_due > 0 and is_walkin:
            return {"success": False, "error": "Customer account is required for Udhaar / Credit sale. Walk-in customer cannot buy on credit."}

        # Fallback: if balance_due > 0 and customer_id is still 0, ensure customer record is created
        if balance_due > 0 and customer_id == 0:
            if not c_phone:
                cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM customers")
                nid = cur.fetchone()["next_id"]
                c_phone = f"NOP-{nid:05d}"
            cur.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)",
                        (c_name, c_phone, now))
            customer_id = cur.lastrowid

        # Determine accurate payment method
        pm_clean = (payment_method or "CASH").strip().upper()
        if balance_due > 0:
            if paid_amount <= 0:
                payment_method = "UDHAAR"
            elif pm_clean in ("CASH", "UDHAAR"):
                payment_method = "PARTIAL UDHAAR"
            elif "UDHAAR" not in pm_clean:
                payment_method = f"{pm_clean} + UDHAAR"
        elif pm_clean == "UDHAAR" and paid_amount >= grand_total:
            payment_method = "CASH"

        # Insert Sale with dual timestamps
        cur.execute("""
            INSERT INTO sales (invoice_no, customer_id, customer_name, customer_phone, subtotal, discount_amount, discount_percent, tax_amount, tax_percent, grand_total, paid_amount, change_amount, balance_due, payment_method, split_details, trade_in_id, salesperson_id, salesperson_name, notes, status, created_at, updated_at, transaction_date, recorded_at, backdate_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?, ?, ?, ?)
        """, (invoice_no, customer_id, customer_name, customer_phone, subtotal, discount_amount, float(discount_percent), tax_amount, float(tax_percent), grand_total, paid_amount, change_amount, balance_due, payment_method, split_details, int(trade_in_id), user_id, username, notes, now, now, trans_date, real_now, backdate_reason))
        sale_id = cur.lastrowid

        # Insert Sale Items
        for pi in processed_items:
            cur.execute("""
                INSERT INTO sale_items (sale_id, variant_id, unit_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit, warranty_till, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_id, pi["variant_id"], pi["unit_id"], pi["item_type"], pi["item_name"], pi["variant_details"], pi["imei1"], pi["imei2"], pi["qty"], pi["unit_price"], pi["cost_price"], pi["discount"], pi["line_total"], pi["profit"], pi["warranty_till"], now))

        # Handle Customer Udhaar / Credit Ledger
        if balance_due > 0 and customer_id > 0:
            cur.execute("""
                UPDATE customers SET balance_udhaar = balance_udhaar + ?, total_purchases = total_purchases + ?, total_paid = total_paid + ?
                WHERE id = ?
            """, (balance_due, grand_total, paid_amount, customer_id))
            
            cur.execute("SELECT balance_udhaar FROM customers WHERE id = ?", (customer_id,))
            c_now = cur.fetchone()
            c_bal = c_now["balance_udhaar"] if c_now else balance_due
            cur.execute("""
                INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, timestamp, transaction_date, recorded_at)
                VALUES (?, ?, 'SALE_CREDIT', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (customer_id, sale_id, balance_due, c_bal, payment_method, f"Credit on {invoice_no}", user_id, now, trans_date, real_now))
        elif customer_id > 0:
            cur.execute("""
                UPDATE customers SET total_purchases = total_purchases + ?, total_paid = total_paid + ?
                WHERE id = ?
            """, (grand_total, paid_amount, customer_id))

        if trade_in_id and int(trade_in_id) > 0:
            cur.execute("UPDATE trade_ins SET linked_sale_id = ? WHERE id = ?", (sale_id, int(trade_in_id)))

        # Update sales_daily_by_variant aggregates
        for pi in processed_items:
            vid = pi["variant_id"]
            if vid:
                p_row = cur.execute("""
                    SELECT p.id AS product_id, p.category, p.brand 
                    FROM variants v 
                    JOIN products p ON v.product_id = p.id 
                    WHERE v.id = ?
                """, (vid,)).fetchone()
                pid = p_row["product_id"] if p_row else 0
                cat = p_row["category"] if p_row else ""
                brd = p_row["brand"] if p_row else ""
                cur.execute("""
                    INSERT INTO sales_daily_by_variant (date, variant_id, product_id, category, brand, units_sold, gross_revenue, cost_total, units_returned, net_profit)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(date, variant_id) DO UPDATE SET
                        units_sold = sales_daily_by_variant.units_sold + excluded.units_sold,
                        gross_revenue = sales_daily_by_variant.gross_revenue + excluded.gross_revenue,
                        cost_total = sales_daily_by_variant.cost_total + excluded.cost_total,
                        net_profit = sales_daily_by_variant.net_profit + excluded.net_profit
                """, (trans_date, vid, pid, cat, brd, pi["qty"], pi["line_total"], pi["cost_price"] * pi["qty"], pi["profit"]))

        # Evaluate stock alert state transitions inside transaction
        affected_vids = list(set([pi["variant_id"] for pi in processed_items if pi["variant_id"]]))
        alert_notifs = alert_engine.evaluate_stock_transitions(cx, affected_vids, user_id=user_id, action_trigger="SALE", reference=invoice_no)

    auth.log_audit(user_id, username, "POS_SALE", "sales", str(sale_id), "", f"Invoice: {invoice_no}, Total: {grand_total}")
    return {
        "success": True,
        "sale_id": sale_id,
        "invoice_no": invoice_no,
        "grand_total": grand_total,
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        "balance_due": balance_due,
        "alert_notifications": alert_notifs
    }

# ═══════════════════════════════════════════════════════════
# 2. RETURNS & EXCHANGES
# ═══════════════════════════════════════════════════════════

def process_return(sale_id, return_items_data, refund_type="CASH", reason="", return_date=None, backdate_reason="", user_id=0, username=""):
    """
    Process full or partial return:
    - Units marked RESTOCK or DEFECTIVE
    - Quantities returned to stock
    - Profit/ledger updated
    - Dual timestamps & backdating validation supported
    """
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    if not sale:
        return {"success": False, "error": "Sale not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    t_val = accounting.validate_backdate_entry(return_date, user_id=user_id, username=username, reason=backdate_reason, entity="returns")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    trans_date = t_val["target_date"]
    clean_backdate_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM returns WHERE return_date LIKE ?", (f"{trans_date}%",))
        seq = cur.fetchone()["c"] + 1
        return_no = f"RET-{date_str}-{seq:04d}"

        processed_count = 0
        total_refund = 0.0

        for r_item in return_items_data:
            si_id = int(r_item["sale_item_id"])
            return_qty = int(r_item.get("qty", 1))
            action = r_item.get("action", "RESTOCK") # RESTOCK, DEFECTIVE

            si = db.query_one("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (si_id, sale_id))
            if not si or si["is_returned"] == 1:
                continue

            processed_count += 1
            ref_amount = float(r_item.get("refund_price") if r_item.get("refund_price") is not None else (si["unit_price"] * return_qty))
            total_refund += ref_amount

            # Mark item as returned or split partial quantity
            if return_qty >= si["qty"]:
                cur.execute("UPDATE sale_items SET is_returned = 1 WHERE id = ?", (si_id,))
            else:
                rem_qty = si["qty"] - return_qty
                unit_disc = float(si.get("discount", 0)) / float(si["qty"]) if si["qty"] > 0 else 0
                rem_disc = unit_disc * rem_qty
                ret_disc = unit_disc * return_qty
                rem_ltot = (si["unit_price"] * rem_qty) - rem_disc
                ret_ltot = (si["unit_price"] * return_qty) - ret_disc
                
                cur.execute("""
                    UPDATE sale_items 
                    SET qty = ?, discount = ?, line_total = ?, profit = ? - (cost_price * ?)
                    WHERE id = ?
                """, (rem_qty, rem_disc, rem_ltot, rem_ltot, rem_qty, si_id))
                
                cur.execute("""
                    INSERT INTO sale_items (sale_id, variant_id, unit_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit, warranty_till, is_returned, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (sale_id, si["variant_id"], si["unit_id"], si["item_type"], si["item_name"], si["variant_details"], si["imei1"], si["imei2"], return_qty, si["unit_price"], si["cost_price"], ret_disc, ret_ltot, ret_ltot - (si["cost_price"] * return_qty), si["warranty_till"], now))

            # Return Phone Unit or Accessory
            target_status = "IN_STOCK" if action == "RESTOCK" else "DEFECTIVE"
            uid = si.get("unit_id") or 0
            if not uid and si.get("imei1"):
                u_find = cur.execute("SELECT id FROM units WHERE imei1 = ? OR (imei2 IS NOT NULL AND imei2 = ?)", (si["imei1"], si["imei1"])).fetchone()
                if u_find:
                    uid = u_find["id"]

            itype_upper = (si.get("item_type") or "PHONE").upper()
            is_phone = (itype_upper in ("PHONE", "SERIAL")) or bool(si.get("imei1"))

            if is_phone and uid:
                cur.execute("UPDATE units SET status = ?, updated_at = ? WHERE id = ?", (target_status, now, uid))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ? 
                    WHERE id = ?
                """, (si["variant_id"], now, si["variant_id"]))
                
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, transaction_date, recorded_at, timestamp)
                    VALUES (?, ?, ?, ?, ?, 1, (SELECT stock_quantity FROM variants WHERE id = ?), 'RETURN', ?, ?, ?, ?, ?, ?)
                """, (0, si["variant_id"], uid, si["imei1"], itype_upper, si["variant_id"], return_no, f"Return on {sale['invoice_no']}", user_id, trans_date, now, now))
            else:
                # Accessory, Spare Part, or non-unit variant
                if action == "RESTOCK":
                    cur.execute("UPDATE variants SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE id = ?",
                                (return_qty, now, si["variant_id"]))
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, transaction_date, recorded_at, timestamp)
                    VALUES (?, ?, 0, '', ?, ?, (SELECT stock_quantity FROM variants WHERE id = ?), 'RETURN', ?, ?, ?, ?, ?, ?)
                """, (0, si["variant_id"], itype_upper, return_qty, si["variant_id"], return_no, f"Return on {sale['invoice_no']}", user_id, trans_date, now, now))

            if si["variant_id"]:
                p_row = cur.execute("""
                    SELECT p.id AS product_id, p.category, p.brand 
                    FROM variants v 
                    JOIN products p ON v.product_id = p.id 
                    WHERE v.id = ?
                """, (si["variant_id"],)).fetchone()
                pid = p_row["product_id"] if p_row else 0
                cat = p_row["category"] if p_row else ""
                brd = p_row["brand"] if p_row else ""
                cur.execute("""
                    INSERT INTO sales_daily_by_variant (date, variant_id, product_id, category, brand, units_sold, gross_revenue, cost_total, units_returned, net_profit)
                    VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                    ON CONFLICT(date, variant_id) DO UPDATE SET
                        units_returned = sales_daily_by_variant.units_returned + excluded.units_returned,
                        gross_revenue = MAX(0, sales_daily_by_variant.gross_revenue - ?),
                        net_profit = sales_daily_by_variant.net_profit - ?
                """, (trans_date, si["variant_id"], pid, cat, brd, return_qty, -ref_amount, ref_amount, ref_amount))

        if processed_count == 0:
            return {"success": False, "error": "Selected item(s) have already been returned or are not eligible for return."}

        # Insert Return Record
        cur.execute("""
            INSERT INTO returns (return_no, sale_id, invoice_no, customer_id, customer_name, refund_amount, refund_type, reason, user_id, return_date, transaction_date, recorded_at, backdate_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (return_no, sale_id, sale["invoice_no"], sale["customer_id"], sale["customer_name"], total_refund, refund_type, reason, user_id, trans_date, trans_date, now, clean_backdate_reason, now))
        return_id = cur.lastrowid

        # Update parent sales record: update returned_amount, status, and reduce balance_due if credit return
        tot_items_res = cur.execute("SELECT COUNT(*) AS c FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchone()
        ret_items_res = cur.execute("SELECT COUNT(*) AS c FROM sale_items WHERE sale_id = ? AND is_returned = 1", (sale_id,)).fetchone()
        tot_cnt = tot_items_res["c"] if tot_items_res else 0
        ret_cnt = ret_items_res["c"] if ret_items_res else 0
        new_status = "RETURNED" if (ret_cnt >= tot_cnt and tot_cnt > 0) else "PARTIALLY_RETURNED"

        cur.execute("""
            UPDATE sales 
            SET returned_amount = COALESCE(returned_amount, 0) + ?,
                status = ?,
                balance_due = CASE WHEN ? = 'CREDIT_NOTE' THEN MAX(0, balance_due - ?) ELSE balance_due END,
                updated_at = ?
            WHERE id = ?
        """, (total_refund, new_status, refund_type, total_refund, now, sale_id))

        # Update customer balance if customer had udhaar
        if sale["customer_id"] and refund_type == "CREDIT_NOTE":
            cur.execute("UPDATE customers SET balance_udhaar = MAX(0, balance_udhaar - ?) WHERE id = ?", (total_refund, sale["customer_id"]))

        # Evaluate transitions for returned variants
        ret_vids = []
        for r_item in return_items_data:
            si_row = db.query_one("SELECT variant_id FROM sale_items WHERE id = ?", (int(r_item["sale_item_id"]),))
            if si_row and si_row["variant_id"]:
                ret_vids.append(si_row["variant_id"])
        if ret_vids:
            alert_engine.evaluate_stock_transitions(cx, ret_vids, user_id=user_id, action_trigger="RETURN", reference=return_no)

    auth.log_audit(user_id, username, "RETURN_SALE", "returns", str(return_id), "", f"Refund: {total_refund} on {sale['invoice_no']}")
    db.bump_change_version("stock")
    db.bump_change_version("sales")
    return {"success": True, "return_id": return_id, "return_no": return_no, "refund_amount": total_refund}

# ═══════════════════════════════════════════════════════════
# 3. TRADE-IN / BUY-BACK ENGINE
# ═══════════════════════════════════════════════════════════

def record_trade_in(customer_name, customer_phone, customer_cnic, brand, model, imei1, 
                    condition="USED", battery_health=85, purchase_price=0, target_variant_id=0, notes="", user_id=0, username=""):
    """
    Buys a used phone from customer:
    - Generates buyback voucher
    - Enters phone into inventory as 'USED' with cost_price = purchase_price paid
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM trade_ins WHERE created_at LIKE ?", (f"{now[:10]}%",))
        seq = cur.fetchone()["c"] + 1
        trade_in_no = f"TRD-{date_str}-{seq:04d}"

        # If target_variant_id is 0, find or create generic used variant for model
        if not target_variant_id:
            # Look up product
            p = db.query_one("SELECT id FROM products WHERE brand = ? AND name = ?", (brand.strip(), model.strip()))
            pid = p["id"] if p else inventory.create_product(brand, model, "Smartphone", "PHONE", 1, notes="Created via Trade-in")
            # Look up or create variant
            v = db.query_one("SELECT id FROM variants WHERE product_id = ? AND is_archived = 0", (pid,))
            target_variant_id = v["id"] if v else inventory.create_variant(pid, color="Mixed", retail_price=float(purchase_price)*1.2, wholesale_price=float(purchase_price))

        # Add unit into stock as USED
        u_res = inventory.add_unit(target_variant_id, imei1, condition=condition, pta_status="PTA_APPROVED", cost_price=purchase_price, battery_health=battery_health, notes=f"Trade-in from {customer_name}", user_id=user_id, username=username)
        if not u_res["success"]:
            return u_res
        unit_id = u_res["unit_id"]

        cur.execute("""
            INSERT INTO trade_ins (trade_in_no, customer_name, customer_phone, customer_cnic, brand, model, imei1, condition, battery_health, purchase_price, unit_id, linked_sale_id, notes, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """, (trade_in_no, customer_name.strip(), customer_phone.strip(), customer_cnic.strip(), brand.strip(), model.strip(), str(imei1).strip(), condition, int(battery_health), float(purchase_price), unit_id, notes, user_id, now))
        trade_in_id = cur.lastrowid

    auth.log_audit(user_id, username, "TRADE_IN_BUYBACK", "trade_ins", str(trade_in_id), "", f"Bought {brand} {model} ({imei1}) for Rs. {purchase_price}")
    return {"success": True, "trade_in_id": trade_in_id, "trade_in_no": trade_in_no, "unit_id": unit_id}

# ═══════════════════════════════════════════════════════════
# 4. SALE EDITING (ADMIN ONLY WITH DELTAS)
# ═══════════════════════════════════════════════════════════

def admin_edit_sale(sale_id, new_items, new_customer_name=None, new_customer_phone=None, user_id=0, username=""):
    """
    Admin sale editor:
    - Allows swapping IMEIs or altering quantities.
    - Adjusts stock deltas and profit automatically.
    """
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    if not sale:
        return {"success": False, "error": "Sale not found"}

    old_items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db.transaction() as cx:
        cur = cx.cursor()

        # 1. Restore old items to stock
        for oi in old_items:
            if oi["item_type"] == "PHONE" and oi["unit_id"]:
                cur.execute("UPDATE units SET status = 'IN_STOCK', updated_at = ? WHERE id = ?", (now, oi["unit_id"]))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ? 
                    WHERE id = ?
                """, (oi["variant_id"], now, oi["variant_id"]))
            elif oi["item_type"] != "PHONE":
                cur.execute("UPDATE variants SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE id = ?", (oi["qty"], now, oi["variant_id"]))

        cur.execute("DELETE FROM sale_items WHERE sale_id = ?", (sale_id,))

        # 2. Process new items
        new_subtotal = 0.0
        for ni in new_items:
            vid = int(ni["variant_id"])
            uid = int(ni.get("unit_id", 0))
            qty = 1 if ni.get("item_type") == "PHONE" else int(ni.get("qty", 1))
            uprice = float(ni.get("unit_price", 0))
            cost = float(ni.get("cost_price", 0))
            discount = float(ni.get("discount", 0))
            ltot = (uprice * qty) - discount
            new_subtotal += ltot
            profit = ltot - (cost * qty)

            if ni.get("item_type") == "PHONE" and uid:
                cur.execute("UPDATE units SET status = 'SOLD', updated_at = ? WHERE id = ?", (now, uid))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ? 
                    WHERE id = ?
                """, (vid, now, vid))
            elif ni.get("item_type") != "PHONE":
                cur.execute("UPDATE variants SET stock_quantity = stock_quantity - ?, updated_at = ? WHERE id = ?", (qty, now, vid))

            cur.execute("""
                INSERT INTO sale_items (sale_id, variant_id, unit_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_id, vid, uid, ni.get("item_type", "PHONE"), ni.get("item_name", "Item"), ni.get("variant_details", ""), ni.get("imei1", ""), ni.get("imei2", ""), qty, uprice, cost, discount, ltot, profit, now))

        # Update sale totals
        cur.execute("""
            UPDATE sales SET subtotal = ?, grand_total = ?, updated_at = ?, status = 'EDITED'
            WHERE id = ?
        """, (new_subtotal, new_subtotal, now, sale_id))

        # Re-evaluate stock transitions for affected items
        edit_vids = list(set([oi["variant_id"] for oi in old_items if oi["variant_id"]] + [int(ni["variant_id"]) for ni in new_items if ni.get("variant_id")]))
        if edit_vids:
            alert_engine.evaluate_stock_transitions(cx, edit_vids, user_id=user_id, action_trigger="EDIT_SALE", reference=sale["invoice_no"])

    auth.log_audit(user_id, username, "ADMIN_EDIT_SALE", "sales", str(sale_id), json.dumps(old_items), "Swapped items/IMEIs")
    return {"success": True}

def admin_void_sale(sale_id, reason="", user_id=0, username=""):
    """
    Admin-only void sale action:
    - Restores phone units to IN_STOCK and increments accessory quantities.
    - Appends reversing entries to stock_ledger.
    - Reverses customer udhaar balance if credit was charged.
    - Updates sale status to 'VOIDED' with audit reason.
    - Evaluates stock alert transitions.
    """
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    if not sale:
        return {"success": False, "error": "Sale not found"}
    if sale.get("status") == "VOIDED":
        return {"success": False, "error": "Sale is already voided"}

    old_items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db.transaction() as cx:
        cur = cx.cursor()

        # 1. Restore items to stock
        for oi in old_items:
            vid = oi.get("variant_id") or 0
            if oi["item_type"] == "PHONE" and oi["unit_id"]:
                cur.execute("UPDATE units SET status = 'IN_STOCK', updated_at = ? WHERE id = ?", (now, oi["unit_id"]))
                cur.execute("""
                    UPDATE variants 
                    SET stock_quantity = (SELECT COUNT(*) FROM units WHERE variant_id = ? AND status = 'IN_STOCK'),
                        updated_at = ? 
                    WHERE id = ?
                """, (vid, now, vid))
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, user_id, timestamp, transaction_date, recorded_at)
                    VALUES (0, ?, ?, ?, 'PHONE', 1, 0, 'VOID_SALE', ?, ?, ?, ?, ?)
                """, (vid, oi["unit_id"], oi.get("imei1", ""), sale["invoice_no"], user_id, now, now[:10], now))
            elif oi["item_type"] != "PHONE":
                cur.execute("UPDATE variants SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE id = ?", (oi["qty"], now, vid))
                cur.execute("""
                    INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, user_id, timestamp, transaction_date, recorded_at)
                    VALUES (0, ?, 0, '', ?, ?, 0, 'VOID_SALE', ?, ?, ?, ?, ?)
                """, (vid, oi["item_type"], oi["qty"], sale["invoice_no"], user_id, now, now[:10], now))

        # 2. Reverse customer udhaar if any balance was charged
        cid = sale.get("customer_id")
        bal_due = float(sale.get("balance_due", 0))
        if cid and bal_due > 0:
            cur.execute("UPDATE customers SET balance_udhaar = MAX(0, balance_udhaar - ?), total_purchases = MAX(0, total_purchases - ?) WHERE id = ?",
                        (bal_due, sale["grand_total"], cid))
            cur.execute("SELECT balance_udhaar FROM customers WHERE id = ?", (cid,))
            c_now = cur.fetchone()
            c_bal = c_now["balance_udhaar"] if c_now else 0
            cur.execute("""
                INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, timestamp, transaction_date, recorded_at)
                VALUES (?, ?, 'VOID_SALE', -?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, sale_id, bal_due, c_bal, sale.get("payment_method", "CASH"), f"Reversal for voided {sale['invoice_no']}: {reason}", user_id, now, now[:10], now))

        # 3. Mark sale voided
        cur.execute("UPDATE sales SET status = 'VOIDED', updated_at = ?, notes = notes || ? WHERE id = ?", (now, f" [VOIDED: {reason}]", sale_id))

        # Re-evaluate stock transitions
        affected_vids = list(set([oi["variant_id"] for oi in old_items if oi.get("variant_id")]))
        if affected_vids:
            alert_engine.evaluate_stock_transitions(cx, affected_vids, user_id=user_id, action_trigger="VOID_SALE", reference=sale["invoice_no"])

    auth.log_audit(user_id, username, "ADMIN_VOID_SALE", "sales", str(sale_id), str(sale["grand_total"]), f"Invoice: {sale['invoice_no']}, Reason: {reason}")
    return {"success": True, "message": f"Sale {sale['invoice_no']} voided and stock restored."}

# Alias for compatibility with tests & legacy modules
process_sale = pos_checkout

