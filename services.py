# MOBILE & ACCESSORIES ERP — Software Services & Hardware Repair Workshop Engine
import json
from datetime import datetime
import db, auth, scanner, alert_engine

# ═══════════════════════════════════════════════════════════
# 1. SOFTWARE SERVICES (QUICK RE-FLASH, UNLOCK, FRP)
# ═══════════════════════════════════════════════════════════

def list_software_catalog():
    """Lists available standard software services."""
    return db.query_all("SELECT * FROM software_catalog WHERE is_active = 1 ORDER BY id ASC")

def add_software_catalog_item(name, description="", default_price=0, default_cost=0):
    """Adds a new service to software catalog."""
    return db.execute("""
        INSERT INTO software_catalog (name, description, default_price, default_cost, is_active)
        VALUES (?, ?, ?, ?, 1)
    """, (name.strip(), description.strip(), float(default_price), float(default_cost)))

def create_software_job(brand_model, service_id=0, price_charged=None, tool_server_cost=None, 
                        customer_name="Walk-in", customer_phone="", customer_cnic="", imei="", 
                        payment_method="CASH", technician_name="Software Lab", notes="", user_id=0, username=""):
    """
    Creates a quick software job ticket in < 10 seconds.
    Calculates profit = price_charged - tool_server_cost.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    sname = "Custom Software Service"
    dprice = 1500.0
    dcost = 0.0

    if service_id:
        srv = db.query_one("SELECT * FROM software_catalog WHERE id = ?", (service_id,))
        if srv:
            sname = srv["name"]
            dprice = srv["default_price"]
            dcost = srv["default_cost"]

    charged = float(price_charged) if price_charged is not None else dprice
    cost = float(tool_server_cost) if tool_server_cost is not None else dcost
    profit = charged - cost

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM software_jobs WHERE created_at LIKE ?", (f"{now[:10]}%",))
        seq = cur.fetchone()["c"] + 1
        ticket_no = f"SFT-{date_str}-{seq:04d}"

        cur.execute("""
            INSERT INTO software_jobs (ticket_no, customer_name, customer_phone, customer_cnic, brand_model, imei, service_id, service_name, price_charged, tool_server_cost, profit, payment_method, technician_id, technician_name, owner_confirmed, notes, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'COMPLETED', ?)
        """, (ticket_no, customer_name.strip(), customer_phone.strip(), customer_cnic.strip(), brand_model.strip(), imei.strip(), service_id, sname, charged, cost, profit, payment_method, user_id, technician_name.strip(), notes.strip(), now))
        job_id = cur.lastrowid

    auth.log_audit(user_id, username, "SOFTWARE_JOB", "software_jobs", str(job_id), "", f"{ticket_no}: {sname} for {brand_model} (Rs. {charged:,.0f})")
    return {
        "success": True,
        "job_id": job_id,
        "ticket_no": ticket_no,
        "service_name": sname,
        "price_charged": charged,
        "profit": profit
    }

def get_software_job(job_id_or_ticket):
    """Retrieves software job by id or ticket number."""
    if str(job_id_or_ticket).startswith("SFT-"):
        return db.query_one("SELECT * FROM software_jobs WHERE ticket_no = ?", (job_id_or_ticket,))
    return db.query_one("SELECT * FROM software_jobs WHERE id = ?", (job_id_or_ticket,))

def list_software_jobs(search="", limit=100):
    """Lists software jobs with search."""
    if search:
        s = f"%{search.strip()}%"
        return db.query_all("""
            SELECT * FROM software_jobs 
            WHERE ticket_no LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ? OR brand_model LIKE ? OR imei LIKE ?
            ORDER BY id DESC LIMIT ?
        """, (s, s, s, s, s, limit))
    return db.query_all("SELECT * FROM software_jobs ORDER BY id DESC LIMIT ?", (limit,))

def cancel_or_void_software_job(job_id, reason="", user_id=0, username=""):
    """Cancels or voids a software job ticket."""
    job = db.query_one("SELECT * FROM software_jobs WHERE id = ?", (job_id,))
    if not job:
        return {"success": False, "error": "Software job not found"}
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("UPDATE software_jobs SET status = 'CANCELLED', notes = notes || ? WHERE id = ?", (f" [CANCELLED: {reason}]", job_id))
    auth.log_audit(user_id, username, "CANCEL_SOFTWARE_JOB", "software_jobs", str(job_id), job.get("status", ""), f"Cancelled: {reason}")
    return {"success": True, "message": f"Software ticket #{job['ticket_no']} cancelled."}

# ═══════════════════════════════════════════════════════════
# 2. HARDWARE REPAIR WORKSHOP (JOB CARDS, SPARE PARTS & DELIVERIES)
# ═══════════════════════════════════════════════════════════

VALID_REPAIR_STATUSES = [
    "RECEIVED", "DIAGNOSING", "WAITING_PARTS", "IN_REPAIR", "READY", "DELIVERED", "RETURNED_UNREPAIRED", "CANCELLED"
]

def create_repair_job(customer_name, customer_phone, brand, model, complaint, 
                      imei="", accessories_received="", estimate=0, advance_paid=0, 
                      expected_delivery="", technician_name="Workshop Master", warranty_days=30, 
                      user_id=0, username=""):
    """
    Creates a new hardware repair job card.
    Status starts at 'RECEIVED'.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.now().strftime("%Y%m%d")

    est = float(estimate)
    adv = float(advance_paid)
    bal = est - adv

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM repair_jobs WHERE created_at LIKE ?", (f"{now[:10]}%",))
        seq = cur.fetchone()["c"] + 1
        job_no = f"REP-{date_str}-{seq:04d}"

        cur.execute("""
            INSERT INTO repair_jobs (job_no, customer_name, customer_phone, brand, model, imei, accessories_received, complaint, estimate, advance_paid, balance_due, technician_id, technician_name, outsourced_cost, labor_charge, parts_cost, total_charged, profit, warranty_days, expected_delivery, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?, 0, ?, ?, 'RECEIVED', ?, ?)
        """, (job_no, customer_name.strip(), customer_phone.strip(), brand.strip(), model.strip(), imei.strip(), accessories_received.strip(), complaint.strip(), est, adv, bal, user_id, technician_name.strip(), est, int(warranty_days), expected_delivery.strip(), now, now))
        repair_id = cur.lastrowid

    auth.log_audit(user_id, username, "CREATE_REPAIR_JOB", "repair_jobs", str(repair_id), "", f"{job_no}: {brand} {model} for {customer_name}")
    return {
        "success": True,
        "repair_id": repair_id,
        "job_no": job_no,
        "estimate": est,
        "advance_paid": adv,
        "balance_due": bal
    }

def update_repair_status(repair_id, new_status, technician_name=None, user_id=0, username=""):
    """Transitions repair job card to next stage."""
    status_upper = new_status.upper().strip()
    if status_upper not in VALID_REPAIR_STATUSES:
        return {"success": False, "error": f"Invalid status: {new_status}"}

    job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id,))
    if not job:
        return {"success": False, "error": "Repair job not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delivered_at = now if status_upper == "DELIVERED" else job["delivered_at"]
    tech = technician_name or job["technician_name"]

    db.execute("""
        UPDATE repair_jobs 
        SET status = ?, technician_name = ?, delivered_at = ?, updated_at = ?
        WHERE id = ?
    """, (status_upper, tech, delivered_at, now, repair_id))

    auth.log_audit(user_id, username, "UPDATE_REPAIR_STATUS", "repair_jobs", str(repair_id), job["status"], status_upper)
    return {"success": True, "repair_id": repair_id, "new_status": status_upper}

def add_repair_part(repair_id, spare_variant_id, qty=1, charge_price=None, user_id=0, username=""):
    """
    Attaches a spare part from inventory to a repair job:
    - Deducts spare part stock from variants table.
    - Records in repair_parts_used and stock_ledger.
    - Updates repair job parts_cost.
    """
    job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id,))
    if not job:
        return {"success": False, "error": "Repair job not found"}

    v = db.query_one("""
        SELECT v.*, p.name AS product_name, p.brand
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.id = ?
    """, (spare_variant_id,))
    if not v:
        return {"success": False, "error": f"Spare part variant #{spare_variant_id} not found"}

    q = int(qty)
    if q <= 0:
        return {"success": False, "error": "Quantity must be > 0"}

    cost_p = float(v["wholesale_price"])
    charge_p = float(charge_price) if charge_price is not None else float(v["retail_price"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    part_display_name = f"{v['brand']} {v['product_name']} ({v['color'] or 'Standard'})"

    with db.transaction() as cx:
        cur = cx.cursor()

        # Deduct from variants stock
        cur.execute("UPDATE variants SET stock_quantity = stock_quantity - ?, updated_at = ? WHERE id = ?", (q, now, spare_variant_id))
        cur.execute("SELECT stock_quantity FROM variants WHERE id = ?", (spare_variant_id,))
        rem_stock = cur.fetchone()["stock_quantity"]

        # Insert repair part usage
        cur.execute("""
            INSERT INTO repair_parts_used (repair_id, spare_variant_id, part_name, qty, cost_price, charge_price, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (repair_id, spare_variant_id, part_display_name, q, cost_p, charge_p, now))

        # Log in stock ledger
        cur.execute("""
            INSERT INTO stock_ledger (product_id, variant_id, unit_id, imei, item_type, change_qty, balance_qty, action_type, reference, notes, user_id, timestamp)
            VALUES (?, ?, 0, '', 'SPARE_PART', ?, ?, 'REPAIR_USE', ?, ?, ?, ?)
        """, (v["product_id"], spare_variant_id, -q, rem_stock, job["job_no"], f"Fitted to {job['brand']} {job['model']}", user_id, now))

        # Recalculate repair parts cost & total
        cur.execute("SELECT SUM(cost_price * qty) AS total_parts_cost, SUM(charge_price * qty) AS total_parts_charge FROM repair_parts_used WHERE repair_id = ?", (repair_id,))
        part_sums = cur.fetchone()
        tot_parts_cost = part_sums["total_parts_cost"] or 0
        tot_parts_charge = part_sums["total_parts_charge"] or 0

        # Update repair_jobs parts cost and transition to IN_REPAIR if still WAITING_PARTS
        new_status = "IN_REPAIR" if job["status"] in ("WAITING_PARTS", "DIAGNOSING") else job["status"]
        cur.execute("""
            UPDATE repair_jobs 
            SET parts_cost = ?, status = ?, updated_at = ?
            WHERE id = ?
        """, (tot_parts_cost, new_status, now, repair_id))

        # Re-evaluate stock alert state for spare part
        alert_engine.evaluate_stock_transitions(cx, [spare_variant_id], user_id=user_id, action_trigger="REPAIR_USE", reference=job["job_no"])

    auth.log_audit(user_id, username, "ATTACH_REPAIR_PART", "repair_parts_used", str(repair_id), "", f"Fitted {part_display_name} x {q}")
    return {
        "success": True,
        "repair_id": repair_id,
        "part_name": part_display_name,
        "qty": q,
        "cost_price": cost_p,
        "charge_price": charge_p,
        "total_parts_cost": tot_parts_cost,
        "total_parts_charge": tot_parts_charge
    }

def complete_and_deliver_repair(repair_id, final_labor_charge, paid_amount, payment_method="CASH", user_id=0, username=""):
    """
    Finalizes repair job, collects payment, and marks DELIVERED:
    - Calculates total charged = labor_charge + sum(parts charges).
    - Calculates profit = total charged - (parts cost + outsourced cost).
    - Collects payment and records balance.
    """
    job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id,))
    if not job:
        return {"success": False, "error": "Repair job not found"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    labor = float(final_labor_charge)
    paid = float(paid_amount)

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("SELECT SUM(cost_price * qty) AS c, SUM(charge_price * qty) AS ch FROM repair_parts_used WHERE repair_id = ?", (repair_id,))
        p_row = cur.fetchone()
        parts_cost = p_row["c"] or 0.0
        parts_charge = p_row["ch"] or 0.0

        total_charged = labor + parts_charge
        profit = total_charged - (parts_cost + job["outsourced_cost"])
        total_collected = job["advance_paid"] + paid
        balance_due = max(0.0, total_charged - total_collected)

        cur.execute("""
            UPDATE repair_jobs 
            SET labor_charge = ?, parts_cost = ?, total_charged = ?, profit = ?, 
                balance_due = ?, status = 'DELIVERED', delivered_at = ?, updated_at = ?
            WHERE id = ?
        """, (labor, parts_cost, total_charged, profit, balance_due, now, now, repair_id))

    auth.log_audit(user_id, username, "DELIVER_REPAIR", "repair_jobs", str(repair_id), "", f"Delivered {job['job_no']}. Charged: Rs. {total_charged:,.0f}, Profit: Rs. {profit:,.0f}")
    return {
        "success": True,
        "repair_id": repair_id,
        "job_no": job["job_no"],
        "labor_charge": labor,
        "parts_charge": parts_charge,
        "total_charged": total_charged,
        "profit": profit,
        "balance_due": balance_due,
        "status": "DELIVERED"
    }

def get_repair_job(repair_id_or_job_no):
    """Retrieves full repair job card with attached spare parts."""
    if str(repair_id_or_job_no).startswith("REP-"):
        job = db.query_one("SELECT * FROM repair_jobs WHERE job_no = ?", (repair_id_or_job_no,))
    else:
        job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id_or_job_no,))
    
    if not job:
        return None

    parts = db.query_all("SELECT * FROM repair_parts_used WHERE repair_id = ? ORDER BY id ASC", (job["id"],))
    return {"job": job, "parts": parts}

def list_repair_jobs(status=None, search="", limit=100):
    """Lists repair jobs with status filter and search."""
    clauses = []
    params = []
    if status:
        clauses.append("status = ?")
        params.append(status.upper().strip())
    if search:
        s = f"%{search.strip()}%"
        clauses.append("(job_no LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ? OR imei LIKE ? OR model LIKE ?)")
        params.extend([s, s, s, s, s])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"SELECT * FROM repair_jobs {where} ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return db.query_all(query, tuple(params))

def cancel_or_void_repair_job(repair_id, reason="", user_id=0, username=""):
    """
    Cancels a repair job, restoring any allocated spare parts back to inventory.
    """
    job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id,))
    if not job:
        return {"success": False, "error": "Repair job not found"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cur = cx.cursor()
        # Restore any used spare parts
        parts = db.query_all("SELECT * FROM repair_parts_used WHERE repair_id = ?", (repair_id,))
        for p in parts:
            cur.execute("UPDATE variants SET stock_quantity = stock_quantity + ?, updated_at = ? WHERE id = ?", (p["qty"], now, p["spare_variant_id"]))
        cur.execute("UPDATE repair_jobs SET status = 'CANCELLED', updated_at = ? WHERE id = ?", (now, repair_id))
    auth.log_audit(user_id, username, "CANCEL_REPAIR_JOB", "repair_jobs", str(repair_id), job["status"], f"Cancelled: {reason}")
    return {"success": True, "message": f"Repair job #{job['job_no']} cancelled and parts returned to stock."}

# ═══════════════════════════════════════════════════════════
# 3. QUICK SERVICES (EASYPAISA, JAZZCASH, MOBILE LOAD)
# ═══════════════════════════════════════════════════════════

def record_quick_service(service_type, amount, fee_commission, customer_phone="", network="", notes="", user_id=0, username="", action_type="SEND", payment_method="CASH"):
    """
    Records Pakistani mobile shop quick earnings:
    - EasyPaisa / JazzCash Cash-in (SEND) / Cash-out (RECEIVE)
    - Mobile Load / Top-up
    - SIM card issuance
    - Utility Bill Payment
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amt = float(amount)
    comm = float(fee_commission)
    act = (action_type or "SEND").strip().upper()
    pm = (payment_method or "CASH").strip().upper()

    try:
        qid = db.execute("""
            INSERT INTO quick_services (service_type, network, customer_phone, amount, fee_commission, profit, agent_id, notes, timestamp, action_type, payment_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (service_type.upper().strip(), network.strip(), customer_phone.strip(), amt, comm, comm, user_id, notes.strip(), now, act, pm))
    except Exception:
        qid = db.execute("""
            INSERT INTO quick_services (service_type, network, customer_phone, amount, fee_commission, profit, agent_id, notes, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (service_type.upper().strip(), network.strip(), customer_phone.strip(), amt, comm, comm, user_id, notes.strip(), now))

    auth.log_audit(user_id, username, "QUICK_SERVICE", "quick_services", str(qid), "", f"{act} {service_type} Rs. {amt:,.0f} (Comm/Profit: Rs. {comm:,.0f})")
    return {"success": True, "quick_service_id": qid, "service_type": service_type, "commission": comm, "action_type": act}

def list_quick_services(include_void=False, limit=100):
    """Lists recent quick service transactions."""
    where = "" if include_void else "WHERE (is_void IS NULL OR is_void = 0)"
    return db.query_all(f"SELECT * FROM quick_services {where} ORDER BY id DESC LIMIT ?", (limit,))

def void_quick_service(service_id, reason="", user_id=0, username=""):
    """Admin-only void action for mistaken quick service transaction."""
    qs = db.query_one("SELECT * FROM quick_services WHERE id = ?", (service_id,))
    if not qs:
        return {"success": False, "error": "Quick service transaction not found"}
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("UPDATE quick_services SET is_void = 1, notes = notes || ? WHERE id = ?", (f" [VOIDED: {reason}]", service_id))
    auth.log_audit(user_id, username, "VOID_QUICK_SERVICE", "quick_services", str(service_id), str(qs["amount"]), f"Voided: {reason}")
    return {"success": True, "message": f"Quick service #{qs['id']} voided."}

