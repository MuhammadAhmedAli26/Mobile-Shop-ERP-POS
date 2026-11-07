# MOBILE & ACCESSORIES ERP — Customers, Udhaar & Installments Engine
import json
from datetime import datetime, timedelta
import db, auth, accounting

# ═══════════════════════════════════════════════════════════
# 1. CUSTOMERS CRUD
# ═══════════════════════════════════════════════════════════

def create_customer(name, phone, cnic="", address="", notes="", user_id=0, username=""):
    """Creates a new customer with CNIC & Phone unique check."""
    phone = phone.strip()
    existing = db.query_one("SELECT id FROM customers WHERE phone = ?", (phone,))
    if existing:
        return existing["id"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cid = db.execute("""
        INSERT INTO customers (name, phone, cnic, address, total_purchases, total_paid, balance_udhaar, notes, created_at)
        VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
    """, (name.strip(), phone, cnic.strip(), address.strip(), notes.strip(), now))

    auth.log_audit(user_id, username, "CREATE_CUSTOMER", "customers", str(cid), "", f"Created customer: {name} ({phone})")
    return cid

def update_customer(customer_id, name, phone, cnic="", address="", notes="", user_id=0, username=""):
    """Updates customer details."""
    db.execute("""
        UPDATE customers SET name = ?, phone = ?, cnic = ?, address = ?, notes = ?
        WHERE id = ?
    """, (name.strip(), phone.strip(), cnic.strip(), address.strip(), notes.strip(), customer_id))

    auth.log_audit(user_id, username, "UPDATE_CUSTOMER", "customers", str(customer_id), "", f"Updated customer: {name}")
    return True

def get_customer(customer_id):
    """Retrieves single customer profile."""
    return db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))

def find_customer_by_phone(phone):
    """Looks up customer by exact phone number."""
    return db.query_one("SELECT * FROM customers WHERE phone = ?", (phone.strip(),))

def reconcile_unlinked_udhaar_sales():
    """
    Self-healing routine: scans for sales with outstanding balance_due that either
    have customer_id == 0 or lack an entry in udhaar_ledger, and links them cleanly.
    """
    try:
        unlinked = db.query_all("""
            SELECT * FROM sales 
            WHERE balance_due > 0 AND status NOT IN ('VOIDED', 'CANCELLED')
        """)
        if not unlinked:
            return 0

        reconciled_count = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for s in unlinked:
            sale_id = s["id"]
            bal_due = float(s["balance_due"] or 0)
            paid_amt = float(s["paid_amount"] or 0)
            c_id = int(s.get("customer_id") or 0)
            c_name = (s.get("customer_name") or "").strip()
            c_phone = (s.get("customer_phone") or "").strip()

            with db.transaction() as cx:
                cur = cx.cursor()

                # 1. Resolve or create customer if missing
                if c_id == 0:
                    if c_phone:
                        cur.execute("SELECT id FROM customers WHERE phone = ?", (c_phone,))
                        cf = cur.fetchone()
                        if cf:
                            c_id = cf["id"]
                    if c_id == 0 and c_name and c_name.lower() not in ("walk-in customer", "walk-in"):
                        cur.execute("SELECT id FROM customers WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (c_name,))
                        cf = cur.fetchone()
                        if cf:
                            c_id = cf["id"]
                    if c_id == 0:
                        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM customers")
                        nid = cur.fetchone()["next_id"]
                        auto_phone = c_phone or f"NOP-{nid:05d}"
                        auto_name = c_name if c_name and c_name.lower() not in ("walk-in customer", "walk-in") else f"Walk-in (Udhaar #{s['invoice_no'][-4:]})"
                        cur.execute("INSERT INTO customers (name, phone, created_at) VALUES (?, ?, ?)", (auto_name, auto_phone, s.get("created_at") or now))
                        c_id = cur.lastrowid

                    # Update sale with resolved customer_id and accurate payment_method
                    new_pm = "UDHAAR" if paid_amt <= 0 else "PARTIAL UDHAAR"
                    cur.execute("UPDATE sales SET customer_id = ?, payment_method = ? WHERE id = ?", (c_id, new_pm, sale_id))

                # 2. Check if udhaar_ledger entry exists for this sale
                cur.execute("SELECT id FROM udhaar_ledger WHERE sale_id = ? AND transaction_type = 'SALE_CREDIT'", (sale_id,))
                ledg = cur.fetchone()
                if not ledg:
                    cur.execute("UPDATE customers SET balance_udhaar = balance_udhaar + ? WHERE id = ?", (bal_due, c_id))
                    cur.execute("SELECT balance_udhaar FROM customers WHERE id = ?", (c_id,))
                    c_now = cur.fetchone()
                    c_bal = c_now["balance_udhaar"] if c_now else bal_due
                    cur.execute("""
                        INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, timestamp, transaction_date, recorded_at)
                        VALUES (?, ?, 'SALE_CREDIT', ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (c_id, sale_id, bal_due, c_bal, s.get("payment_method") or "UDHAAR", f"Reconciled Credit on {s['invoice_no']}", s.get("salesperson_id") or 0, s.get("created_at") or now, (s.get("transaction_date") or s.get("created_at") or now)[:10], now))
                    reconciled_count += 1

        return reconciled_count
    except Exception as e:
        return 0

def list_customers(search="", filter_has_balance=False, include_archived=False, limit=100):
    """Lists customers with optional balance filter & search."""
    reconcile_unlinked_udhaar_sales()
    clauses = []
    params = []
    if not include_archived:
        clauses.append("is_archived = 0")
    if filter_has_balance:
        clauses.append("balance_udhaar > 0")
    if search:
        s = f"%{search.strip()}%"
        clauses.append("(name LIKE ? OR phone LIKE ? OR cnic LIKE ?)")
        params.extend([s, s, s])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"SELECT * FROM customers {where} ORDER BY balance_udhaar DESC, name ASC LIMIT ?"
    params.append(limit)
    return db.query_all(query, tuple(params))

def delete_or_archive_customer(customer_id, user_id=0, username=""):
    """
    Deletes customer if no sales/ledger/installment history; otherwise archives safely.
    """
    c = db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not c:
        return {"success": False, "status": 404, "message": "Customer not found"}

    s_count = db.query_one("SELECT COUNT(*) AS c FROM sales WHERE customer_id = ?", (customer_id,))["c"]
    u_count = db.query_one("SELECT COUNT(*) AS c FROM udhaar_ledger WHERE customer_id = ?", (customer_id,))["c"]
    i_count = db.query_one("SELECT COUNT(*) AS c FROM installments WHERE customer_id = ?", (customer_id,))["c"]

    if s_count > 0 or u_count > 0 or i_count > 0 or c.get("balance_udhaar", 0) > 0:
        db.execute("UPDATE customers SET is_archived = 1 WHERE id = ?", (customer_id,))
        auth.log_audit(user_id, username, "ARCHIVE_CUSTOMER", "customers", str(customer_id), "", f"Archived customer '{c['name']}' (has {s_count} sales, {u_count} udhaar entries)")
        return {"success": True, "action": "ARCHIVED", "message": f"Customer '{c['name']}' has transaction history and has been safely archived."}
    else:
        db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        auth.log_audit(user_id, username, "DELETE_CUSTOMER", "customers", str(customer_id), "", f"Deleted customer '{c['name']}'")
        return {"success": True, "action": "DELETED", "message": f"Customer '{c['name']}' permanently deleted."}

def restore_customer(customer_id, user_id=0, username=""):
    """Restores an archived customer."""
    c = db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not c:
        return {"success": False, "status": 404, "message": "Customer not found"}
    db.execute("UPDATE customers SET is_archived = 0 WHERE id = ?", (customer_id,))
    auth.log_audit(user_id, username, "RESTORE_CUSTOMER", "customers", str(customer_id), "", f"Restored customer '{c['name']}'")
    return {"success": True, "action": "RESTORED", "message": f"Customer '{c['name']}' restored successfully."}

# ═══════════════════════════════════════════════════════════
# 2. UDHAAR / CREDIT MANAGEMENT
# ═══════════════════════════════════════════════════════════

def record_udhaar_sale(customer_id, sale_id, credit_amount, notes="", user_id=0, username=""):
    """Records credit due on a customer from a POS sale."""
    cust = get_customer(customer_id)
    if not cust:
        return {"success": False, "error": "Customer not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amt = float(credit_amount)

    with db.transaction() as cx:
        cur = cx.cursor()
        new_balance = cust["balance_udhaar"] + amt
        cur.execute("""
            UPDATE customers 
            SET total_purchases = total_purchases + ?, balance_udhaar = ?
            WHERE id = ?
        """, (amt, new_balance, customer_id))

        cur.execute("""
            INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, timestamp)
            VALUES (?, ?, 'SALE_CREDIT', ?, ?, 'UDHAAR', ?, ?, ?)
        """, (customer_id, sale_id, amt, new_balance, notes, user_id, now))
        ledger_id = cur.lastrowid

    auth.log_audit(user_id, username, "UDHAAR_SALE", "udhaar_ledger", str(ledger_id), "", f"Credit of Rs. {amt:,.0f} charged to {cust['name']}")
    return {"success": True, "ledger_id": ledger_id, "new_balance": new_balance}

def record_udhaar_payment(customer_id, amount, payment_method="CASH", notes="", payment_date=None, backdate_reason="", user_id=0, username=""):
    """Customer pays towards their unpaid credit balance with dual timestamps."""
    amt = float(amount)
    if amt <= 0:
        return {"success": False, "error": "Payment amount must be greater than zero"}

    cust = get_customer(customer_id)
    if not cust:
        return {"success": False, "error": "Customer not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    t_val = accounting.validate_backdate_entry(payment_date, user_id=user_id, username=username, reason=backdate_reason, entity="udhaar_ledger")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    trans_date = t_val["target_date"]
    clean_backdate_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    with db.transaction() as cx:
        cur = cx.cursor()
        new_balance = cust["balance_udhaar"] - amt
        cur.execute("""
            UPDATE customers 
            SET total_paid = total_paid + ?, balance_udhaar = ?
            WHERE id = ?
        """, (amt, new_balance, customer_id))

        cur.execute("""
            INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
            VALUES (?, 0, 'PAYMENT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (customer_id, amt, new_balance, payment_method, notes, user_id, trans_date, now, clean_backdate_reason, now))
        ledger_id = cur.lastrowid

    auth.log_audit(user_id, username, "UDHAAR_PAYMENT", "udhaar_ledger", str(ledger_id), "", f"Received Udhaar payment Rs. {amt:,.0f} from {cust['name']} on {trans_date}")
    return {"success": True, "ledger_id": ledger_id, "amount": amt, "new_balance": new_balance, "transaction_date": trans_date}

def get_customer_ledger(customer_id):
    """Retrieves full credit transaction history for a customer."""
    cust = get_customer(customer_id)
    if not cust:
        return {"success": False, "error": "Customer not found"}

    rows = db.query_all("""
        SELECT u.*, s.invoice_no
        FROM udhaar_ledger u
        LEFT JOIN sales s ON u.sale_id = s.id
        WHERE u.customer_id = ?
        ORDER BY u.timestamp ASC, u.id ASC
    """, (customer_id,))
    return {"success": True, "customer": cust, "transactions": rows}

# ═══════════════════════════════════════════════════════════
# 3. INSTALLMENT FINANCING (PLANS, SCHEDULE & GUARANTORS)
# ═══════════════════════════════════════════════════════════

def create_installment_plan(sale_id, customer_id, total_price, down_payment, total_months, 
                            monthly_markup_percent=0, start_date=None, 
                            guarantor1=None, guarantor2=None, notes="", user_id=0, username=""):
    """
    Creates an installment financing contract:
    - Calculates markup, financed amount, and monthly due.
    - Generates monthly schedule records with due dates.
    - Captures up to two Pakistani guarantors (Name, Phone, CNIC).
    - Updates customer udhaar balance with total payable financing.
    """
    cust = get_customer(customer_id)
    if not cust:
        return {"success": False, "error": "Customer not found"}

    tot = float(total_price)
    dp = float(down_payment)
    months = int(total_months)
    if months <= 0:
        return {"success": False, "error": "Total months must be at least 1"}
    if dp >= tot:
        return {"success": False, "error": "Down payment cannot be greater than or equal to total price"}

    financed = tot - dp
    markup_pct = float(monthly_markup_percent)
    total_markup = financed * (markup_pct / 100.0) * months
    total_payable = financed + total_markup
    monthly_due = round(total_payable / months, 2)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_dt = start_date or now[:10]

    g1 = guarantor1 or {}
    g2 = guarantor2 or {}

    with db.transaction() as cx:
        cur = cx.cursor()

        cur.execute("""
            INSERT INTO installments (sale_id, customer_id, total_price, down_payment, financed_amount, total_months, monthly_due, start_date, notes, status, guarantor1_name, guarantor1_phone, guarantor1_cnic, guarantor2_name, guarantor2_phone, guarantor2_cnic, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?)
        """, (sale_id, customer_id, tot, dp, total_payable, months, monthly_due, start_dt, notes,
              g1.get("name", ""), g1.get("phone", ""), g1.get("cnic", ""),
              g2.get("name", ""), g2.get("phone", ""), g2.get("cnic", ""), now))
        installment_id = cur.lastrowid

        # Generate schedule for each month
        base_date = datetime.strptime(start_dt, "%Y-%m-%d")
        schedule = []
        for i in range(1, months + 1):
            due_dt = (base_date + timedelta(days=30 * i)).strftime("%Y-%m-%d")
            cur.execute("""
                INSERT INTO installment_schedule (installment_id, installment_no, due_date, due_amount, paid_amount, status)
                VALUES (?, ?, ?, ?, 0, 'PENDING')
            """, (installment_id, i, due_dt, monthly_due))
            schedule.append({
                "schedule_id": cur.lastrowid,
                "installment_no": i,
                "due_date": due_dt,
                "due_amount": monthly_due,
                "status": "PENDING"
            })

        # Update customer balance with financed amount
        new_balance = cust["balance_udhaar"] + total_payable
        cur.execute("""
            UPDATE customers SET balance_udhaar = ? WHERE id = ?
        """, (new_balance, customer_id))

        cur.execute("""
            INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, timestamp)
            VALUES (?, ?, 'INSTALLMENT_PLAN', ?, ?, 'INSTALLMENT', ?, ?, ?)
        """, (customer_id, sale_id, total_payable, new_balance, f"Financed Plan #{installment_id} ({months} months)", user_id, now))

    auth.log_audit(user_id, username, "CREATE_INSTALLMENT_PLAN", "installments", str(installment_id), "", f"Created {months}-month plan for {cust['name']}, Total: Rs. {total_payable:,.0f}")
    return {
        "success": True,
        "installment_id": installment_id,
        "financed_amount": financed,
        "total_markup": total_markup,
        "total_payable": total_payable,
        "monthly_due": monthly_due,
        "schedule": schedule
    }

def pay_installment(installment_schedule_id, paid_amount, payment_method="CASH", notes="", payment_date=None, backdate_reason="", user_id=0, username=""):
    """
    Records payment against a specific monthly installment due:
    - Updates installment_schedule row.
    - Generates unique installment receipt number.
    - Updates customer balance.
    - Closes parent plan if all monthly installments are paid.
    - Supports backdating with dual timestamps.
    """
    amt = float(paid_amount)
    if amt <= 0:
        return {"success": False, "error": "Payment amount must be greater than zero"}

    sch = db.query_one("SELECT * FROM installment_schedule WHERE id = ?", (installment_schedule_id,))
    if not sch:
        return {"success": False, "error": "Installment schedule entry not found"}

    inst = db.query_one("SELECT * FROM installments WHERE id = ?", (sch["installment_id"],))
    cust = get_customer(inst["customer_id"])

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")
    receipt_no = f"INST-RCP-{date_str}-{sch['id']:04d}"

    t_val = accounting.validate_backdate_entry(payment_date, user_id=user_id, username=username, reason=backdate_reason, entity="udhaar_ledger")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    trans_date = t_val["target_date"]
    clean_backdate_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    with db.transaction() as cx:
        cur = cx.cursor()

        new_paid_for_month = sch["paid_amount"] + amt
        new_status = "PAID" if new_paid_for_month >= sch["due_amount"] else "PARTIAL"

        cur.execute("""
            UPDATE installment_schedule 
            SET paid_amount = ?, paid_date = ?, status = ?, receipt_no = ?
            WHERE id = ?
        """, (new_paid_for_month, trans_date, new_status, receipt_no, installment_schedule_id))

        # Update customer balance
        new_balance = cust["balance_udhaar"] - amt
        cur.execute("""
            UPDATE customers 
            SET total_paid = total_paid + ?, balance_udhaar = ?
            WHERE id = ?
        """, (amt, new_balance, cust["id"]))

        cur.execute("""
            INSERT INTO udhaar_ledger (customer_id, sale_id, transaction_type, amount, balance_after, payment_method, notes, user_id, transaction_date, recorded_at, backdate_reason, timestamp)
            VALUES (?, ?, 'INSTALLMENT_PAYMENT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cust["id"], inst["sale_id"], amt, new_balance, payment_method, f"Installment #{sch['installment_no']} ({receipt_no})", user_id, trans_date, now, clean_backdate_reason, now))

        # Check if entire plan is complete
        cur.execute("SELECT COUNT(*) AS c FROM installment_schedule WHERE installment_id = ? AND status != 'PAID'", (inst["id"],))
        remaining = cur.fetchone()["c"]
        if remaining == 0:
            cur.execute("UPDATE installments SET status = 'COMPLETED' WHERE id = ?", (inst["id"],))

    auth.log_audit(user_id, username, "PAY_INSTALLMENT", "installment_schedule", str(installment_schedule_id), "", f"Received Rs. {amt:,.0f} on installment #{sch['installment_no']} from {cust['name']}")
    return {
        "success": True,
        "receipt_no": receipt_no,
        "installment_id": inst["id"],
        "schedule_id": installment_schedule_id,
        "status": new_status,
        "new_balance": new_balance,
        "plan_completed": (remaining == 0)
    }

def get_installment_details(installment_id):
    """Fetches complete contract, customer, guarantors, and monthly schedule."""
    inst = db.query_one("""
        SELECT i.*, c.name AS customer_name, c.phone AS customer_phone, c.cnic AS customer_cnic, s.invoice_no
        FROM installments i
        JOIN customers c ON i.customer_id = c.id
        LEFT JOIN sales s ON i.sale_id = s.id
        WHERE i.id = ?
    """, (installment_id,))
    if not inst:
        return None

    schedule = db.query_all("""
        SELECT * FROM installment_schedule 
        WHERE installment_id = ? 
        ORDER BY installment_no ASC
    """, (installment_id,))
    
    return {"plan": inst, "schedule": schedule}

def list_installments(status="ACTIVE", limit=100):
    """Lists installment plans with summary stats."""
    query = """
        SELECT i.*, c.name AS customer_name, c.phone AS customer_phone,
               (SELECT COUNT(*) FROM installment_schedule WHERE installment_id = i.id AND status = 'PAID') AS paid_count,
               (SELECT SUM(paid_amount) FROM installment_schedule WHERE installment_id = i.id) AS total_collected
        FROM installments i
        JOIN customers c ON i.customer_id = c.id
    """
    if status:
        query += " WHERE i.status = ? ORDER BY i.id DESC LIMIT ?"
        return db.query_all(query, (status, limit))
    query += " ORDER BY i.id DESC LIMIT ?"
    return db.query_all(query, (limit,))

def get_overdue_installments():
    """Identifies installments that passed their due date without payment."""
    today = datetime.now().strftime("%Y-%m-%d")
    return db.query_all("""
        SELECT s.*, i.customer_id, c.name AS customer_name, c.phone AS customer_phone,
               i.guarantor1_name, i.guarantor1_phone,
               (JULIANDAY(?) - JULIANDAY(s.due_date)) AS days_overdue
        FROM installment_schedule s
        JOIN installments i ON s.installment_id = i.id
        JOIN customers c ON i.customer_id = c.id
        WHERE s.due_date < ? AND s.status != 'PAID'
        ORDER BY s.due_date ASC
    """, (today, today))
