# MOBILE & ACCESSORIES ERP — Accounting, Expenses & 5-Stream Earnings Center
import json
from datetime import datetime
import db, auth, lookups

EXPENSE_CATEGORIES = [
    "Shop Rent", "Electricity / Generator / Fuel", "Staff Salary", 
    "Tea / Food", "Market Committee / Police", "Internet / PTCL", 
    "Repair Tools & Supplies", "Packaging / Bags", "Software Server Credits", "Miscellaneous"
]

# ═══════════════════════════════════════════════════════════
# 1. EXPENSES MANAGEMENT & BACK-DATING VALIDATION (FIX 4)
# ═══════════════════════════════════════════════════════════

def validate_backdate_entry(target_date, user_id=0, username="", reason="", entity=""):
    """
    Validates back-dating constraints:
    1. Rejects future dates.
    2. Enforces Admin or can_backdate permission.
    3. If target_date is in a closed day:
       - Requires reason of at least 10 chars.
       - Marks day_closings.modified_after_closing = 1.
       - Logs audit entry.
    Returns {"valid": True, "is_backdated": bool, "target_date": str} or {"valid": False, "error": str}
    """
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    d = str(target_date).strip()[:10] if target_date else today_str
    
    if not d:
        d = today_str
        
    if d > today_str:
        return {"valid": False, "error": f"Transaction date '{d}' cannot be in the future (Today is {today_str})"}
        
    is_backdated = (d < today_str)
    if is_backdated:
        # Check permissions
        u = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,)) if user_id else auth.current_user()
        if not auth.can_backdate(u):
            return {"valid": False, "error": "Access Denied: Only Administrator can back-date transactions."}
            
        # Check if target date belongs to an already closed day
        closing = db.query_one("SELECT * FROM day_closings WHERE closing_date = ?", (d,))
        if closing:
            r = str(reason).strip()
            if len(r) < 10:
                return {
                    "valid": False,
                    "error": f"Day {d} is already closed. A mandatory reason for back-dating (minimum 10 characters) is required to adjust historical balances."
                }
            # Mark day closing as modified after closing
            db.execute("UPDATE day_closings SET modified_after_closing = 1 WHERE closing_date = ?", (d,))
            auth.log_audit(user_id, username, "BACKDATE_CLOSED_DAY", entity or "day_closings", d, "", f"Back-dated into closed day {d}. Reason: {r}")

    return {"valid": True, "is_backdated": is_backdated, "target_date": d}

def record_expense(category, amount, description="", payment_method="CASH", reference="", expense_date=None, is_recurring=0, user_id=0, username="", backdate_reason=""):
    """Records a business expense with dual timestamps and backdating validation."""
    amt = float(amount)
    if amt <= 0:
        return {"success": False, "error": "Expense amount must be positive"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t_val = validate_backdate_entry(expense_date, user_id, username, backdate_reason, entity="expenses")
    if not t_val.get("valid"):
        return {"success": False, "error": t_val["error"]}

    exp_date = t_val["target_date"]
    clean_reason = backdate_reason.strip() if t_val["is_backdated"] else ""

    eid = db.execute("""
        INSERT INTO expenses (category, description, amount, payment_method, reference, user_id, expense_date, transaction_date, recorded_at, backdate_reason, is_recurring, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (category.strip(), description.strip(), amt, payment_method.strip(), reference.strip(), user_id, exp_date, exp_date, now, clean_reason, int(is_recurring), now))

    auth.log_audit(user_id, username, "RECORD_EXPENSE", "expenses", str(eid), "", f"Expense: {category} Rs. {amt:,.0f} on {exp_date}")
    return {"success": True, "expense_id": eid, "category": category, "amount": amt, "expense_date": exp_date}

def list_expenses(category="", start_date=None, end_date=None, include_void=False, limit=100):
    """Lists expenses with optional filters and robust date resolution."""
    date_expr = "COALESCE(NULLIF(expense_date, ''), NULLIF(transaction_date, ''), substr(created_at, 1, 10))"
    clauses = []
    params = []
    if not include_void:
        clauses.append("(is_void IS NULL OR is_void = 0)")
    if category:
        clauses.append("category = ?")
        params.append(category.strip())
    if start_date:
        clauses.append(f"{date_expr} >= ?")
        params.append(str(start_date).strip()[:10])
    if end_date:
        clauses.append(f"{date_expr} <= ?")
        params.append(str(end_date).strip()[:10])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    eff_limit = limit if (limit and not (start_date or end_date)) else (limit or 5000)
    query = f"SELECT * FROM expenses {where} ORDER BY {date_expr} DESC, id DESC LIMIT ?"
    params.append(eff_limit)
    rows = db.query_all(query, tuple(params))
    for r in rows:
        acc_type = lookups.get_account_type(r.get("payment_method"))
        r["account_type"] = acc_type
        r["is_cash"] = (acc_type == "CASH")
    return rows

def get_month_expenses_summary(month_str, category=""):
    """
    Computes complete monthly expense analysis, payment method split, and category totals.
    month_str: 'YYYY-MM'
    """
    import calendar
    m = month_str.strip()[:7] if month_str else datetime.now().strftime("%Y-%m")
    try:
        parts = m.split("-")
        y, mo = int(parts[0]), int(parts[1])
        last_day = calendar.monthrange(y, mo)[1]
        start_d, end_d = f"{y:04d}-{mo:02d}-01", f"{y:04d}-{mo:02d}-{last_day:02d}"
    except Exception:
        start_d, end_d = f"{m}-01", f"{m}-31"

    items = list_expenses(category=category, start_date=start_d, end_date=end_d, limit=5000)

    total_amount = 0.0
    cash_total = 0.0
    non_cash_total = 0.0
    cat_map = {}
    pm_map = {}

    for ex in items:
        amt = float(ex.get("amount") or 0)
        total_amount += amt
        if ex.get("is_cash"):
            cash_total += amt
        else:
            non_cash_total += amt

        cat = ex.get("category") or "Miscellaneous"
        cat_map[cat] = cat_map.get(cat, 0.0) + amt

        pm = ex.get("payment_method") or "Cash Drawer"
        pm_map[pm] = pm_map.get(pm, 0.0) + amt

    sorted_categories = sorted([{"category": k, "total": v} for k, v in cat_map.items()], key=lambda x: x["total"], reverse=True)
    sorted_accounts = sorted([{"account": k, "total": v} for k, v in pm_map.items()], key=lambda x: x["total"], reverse=True)

    return {
        "month": m,
        "start_date": start_d,
        "end_date": end_d,
        "items": items,
        "expenses": items,
        "count": len(items),
        "total_amount": total_amount,
        "total_expenses": total_amount,
        "cash_total": cash_total,
        "cash_expenses": cash_total,
        "non_cash_total": non_cash_total,
        "non_cash_expenses": non_cash_total,
        "by_category": sorted_categories,
        "by_account": sorted_accounts
    }

def void_expense(expense_id, reason="", user_id=0, username=""):
    """
    Admin-only action to void an expense record.
    """
    exp = db.query_one("SELECT * FROM expenses WHERE id = ?", (expense_id,))
    if not exp:
        return {"success": False, "error": "Expense not found"}
    if exp.get("is_void") == 1:
        return {"success": False, "error": "Expense is already voided"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("UPDATE expenses SET is_void = 1, backdate_reason = backdate_reason || ? WHERE id = ?", (f" [VOIDED: {reason}]", expense_id))
    auth.log_audit(user_id, username, "VOID_EXPENSE", "expenses", str(expense_id), str(exp["amount"]), f"Category: {exp['category']}, Reason: {reason}")
    return {"success": True, "message": f"Expense #{expense_id} marked voided."}


# ═══════════════════════════════════════════════════════════
# 2. 5-STREAM EARNINGS CENTER
# ═══════════════════════════════════════════════════════════

def get_earnings_center(start_date=None, end_date=None):
    """
    Calculates detailed revenue and profits across 5 distinct mobile shop streams:
    1. Phone Retail Sales (selling price - unit cost)
    2. Accessories & Glass (selling price - wholesale cost)
    3. Hardware Repair Center (labor + parts markup)
    4. Software Services Lab (charge - server/dongle cost)
    5. Quick Services (EasyPaisa, JazzCash, Load commissions)
    """
    date_filter_sales = ""
    date_filter_rep = ""
    date_filter_sft = ""
    date_filter_qs = ""
    date_filter_exp = ""
    params_sales = []
    params_rep = []
    params_sft = []
    params_qs = []
    params_exp = []

    if start_date and end_date:
        date_filter_sales = " AND substr(s.created_at, 1, 10) BETWEEN ? AND ?"
        date_filter_rep = " AND substr(delivered_at, 1, 10) BETWEEN ? AND ?"
        date_filter_sft = " AND substr(created_at, 1, 10) BETWEEN ? AND ?"
        date_filter_qs = " AND substr(timestamp, 1, 10) BETWEEN ? AND ?"
        date_filter_exp = " AND expense_date BETWEEN ? AND ?"
        params_sales = [start_date, end_date]
        params_rep = [start_date, end_date]
        params_sft = [start_date, end_date]
        params_qs = [start_date, end_date]
        params_exp = [start_date, end_date]
    elif start_date:
        date_filter_sales = " AND substr(s.created_at, 1, 10) >= ?"
        date_filter_rep = " AND substr(delivered_at, 1, 10) >= ?"
        date_filter_sft = " AND substr(created_at, 1, 10) >= ?"
        date_filter_qs = " AND substr(timestamp, 1, 10) >= ?"
        date_filter_exp = " AND expense_date >= ?"
        params_sales = [start_date]
        params_rep = [start_date]
        params_sft = [start_date]
        params_qs = [start_date]
        params_exp = [start_date]

    # Stream 1: Phone Sales
    phone_query = f"""
        SELECT 
            COALESCE(SUM(si.unit_price * si.qty), 0) AS revenue,
            COALESCE(SUM(si.cost_price * si.qty), 0) AS cost,
            COALESCE(SUM((si.unit_price - si.cost_price) * si.qty), 0) AS profit,
            COALESCE(SUM(si.qty), 0) AS units_sold
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE si.item_type = 'PHONE' AND s.status NOT IN ('CANCELLED', 'VOIDED') AND (si.is_returned IS NULL OR si.is_returned = 0) {date_filter_sales}
    """
    phone_res = db.query_one(phone_query, tuple(params_sales))

    # Stream 2: Accessories & Glass
    acc_query = f"""
        SELECT 
            COALESCE(SUM(si.unit_price * si.qty), 0) AS revenue,
            COALESCE(SUM(si.cost_price * si.qty), 0) AS cost,
            COALESCE(SUM((si.unit_price - si.cost_price) * si.qty), 0) AS profit,
            COALESCE(SUM(si.qty), 0) AS items_sold
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE si.item_type != 'PHONE' AND s.status NOT IN ('CANCELLED', 'VOIDED') AND (si.is_returned IS NULL OR si.is_returned = 0) {date_filter_sales}
    """
    acc_res = db.query_one(acc_query, tuple(params_sales))

    # Stream 3: Hardware Repairs
    rep_query = f"""
        SELECT 
            COALESCE(SUM(total_charged), 0) AS revenue,
            COALESCE(SUM(parts_cost + outsourced_cost), 0) AS cost,
            COALESCE(SUM(profit), 0) AS profit,
            COUNT(*) AS jobs_delivered
        FROM repair_jobs
        WHERE status = 'DELIVERED' {date_filter_rep}
    """
    rep_res = db.query_one(rep_query, tuple(params_rep))

    # Stream 4: Software Services Lab
    sft_query = f"""
        SELECT 
            COALESCE(SUM(price_charged), 0) AS revenue,
            COALESCE(SUM(tool_server_cost), 0) AS cost,
            COALESCE(SUM(profit), 0) AS profit,
            COUNT(*) AS tickets_completed
        FROM software_jobs
        WHERE status = 'COMPLETED' {date_filter_sft}
    """
    sft_res = db.query_one(sft_query, tuple(params_sft))

    # Stream 5: Quick Services Commission
    qs_query = f"""
        SELECT 
            COALESCE(SUM(amount), 0) AS volume,
            COALESCE(SUM(profit), 0) AS profit,
            COUNT(*) AS transactions
        FROM quick_services
        WHERE 1=1 {date_filter_qs}
    """
    qs_res = db.query_one(qs_query, tuple(params_qs))

    # Expenses
    exp_query = f"""
        SELECT COALESCE(SUM(amount), 0) AS total_expenses
        FROM expenses
        WHERE (is_void IS NULL OR is_void = 0) {date_filter_exp}
    """
    exp_res = db.query_one(exp_query, tuple(params_exp))
    total_expenses = exp_res["total_expenses"]

    total_gross_profit = (
        phone_res["profit"] + 
        acc_res["profit"] + 
        rep_res["profit"] + 
        sft_res["profit"] + 
        qs_res["profit"]
    )
    net_profit = total_gross_profit - total_expenses
    total_revenue = phone_res["revenue"] + acc_res["revenue"] + rep_res["revenue"] + sft_res["revenue"] + qs_res["volume"]

    return {
        "stream1_phones": phone_res,
        "stream2_accessories": acc_res,
        "stream3_repairs": rep_res,
        "stream4_software": sft_res,
        "stream5_quick_services": qs_res,
        "total_revenue": total_revenue,
        "total_gross_profit": total_gross_profit,
        "total_expenses": total_expenses,
        "net_profit": net_profit
    }

# ═══════════════════════════════════════════════════════════
# 3. DAY CLOSING (Z-REPORT) & CASH DRAWER RECONCILIATION
# ═══════════════════════════════════════════════════════════

def get_day_closing_data(target_date=None):
    """
    Calculates all cash inflows and outflows for the given date (default: today).
    Uses the canonical lookups.is_cash_account rule:
    - Cash drawer expenses reduce expected drawer cash.
    - Bank/wallet expenses are tracked and displayed separately.
    - Cash refunds and supplier payments reduce drawer cash.
    """
    d = target_date or datetime.now().strftime("%Y-%m-%d")

    # Inflows from POS Sales
    sales_rows = db.query_all("""
        SELECT paid_amount, balance_due, payment_method
        FROM sales
        WHERE (transaction_date = ? OR (transaction_date = '' AND substr(created_at, 1, 10) = ?))
          AND status NOT IN ('CANCELLED', 'VOIDED')
    """, (d, d))
    
    cash_sales = 0.0
    card_sales = 0.0
    online_sales = 0.0
    udhaar_sales = 0.0
    for s in sales_rows:
        udhaar_sales += float(s["balance_due"] or 0)
        pm = s["payment_method"] or "CASH"
        paid = float(s["paid_amount"] or 0)
        acc_type = lookups.get_account_type(pm)
        if acc_type == "CASH":
            cash_sales += paid
        elif "card" in pm.lower():
            card_sales += paid
        else:
            online_sales += paid

    # Udhaar collected
    udhaar_rows = db.query_all("""
        SELECT amount, payment_method
        FROM udhaar_ledger
        WHERE COALESCE(NULLIF(transaction_date, ''), substr(timestamp, 1, 10)) = ? AND transaction_type IN ('PAYMENT', 'INSTALLMENT_PAYMENT')
    """, (d,))
    udhaar_received_cash = sum(float(r["amount"] or 0) for r in udhaar_rows if lookups.is_cash_account(r["payment_method"]))
    udhaar_received_non_cash = sum(float(r["amount"] or 0) for r in udhaar_rows if not lookups.is_cash_account(r["payment_method"]))

    # Repairs income (collected in cash)
    rep_row = db.query_one("""
        SELECT COALESCE(SUM(total_charged), 0) AS repair_cash
        FROM repair_jobs
        WHERE substr(delivered_at, 1, 10) = ?
    """, (d,))
    repair_cash = float(rep_row["repair_cash"]) if rep_row else 0.0

    # Software services income
    sft_rows = db.query_all("""
        SELECT price_charged, payment_method
        FROM software_jobs
        WHERE substr(created_at, 1, 10) = ?
    """, (d,))
    software_cash = sum(float(r["price_charged"] or 0) for r in sft_rows if lookups.is_cash_account(r["payment_method"]))
    software_non_cash = sum(float(r["price_charged"] or 0) for r in sft_rows if not lookups.is_cash_account(r["payment_method"]))

    # Quick services commission
    qs_row = db.query_one("""
        SELECT COALESCE(SUM(profit), 0) AS qs_profit
        FROM quick_services
        WHERE substr(timestamp, 1, 10) = ?
    """, (d,))
    qs_comm = float(qs_row["qs_profit"]) if qs_row else 0.0

    # Itemized Expenses for the target date
    expenses_list = db.query_all("""
        SELECT * FROM expenses
        WHERE (
            substr(expense_date, 1, 10) = ? 
            OR substr(COALESCE(transaction_date, ''), 1, 10) = ?
            OR (expense_date IS NULL AND substr(created_at, 1, 10) = ?)
        )
        AND (is_void IS NULL OR is_void = 0)
        ORDER BY id DESC
    """, (d, d, d))

    cash_expenses_total = 0.0
    non_cash_expenses_total = 0.0
    cat_map = {}

    for ex in expenses_list:
        acc_type = lookups.get_account_type(ex["payment_method"])
        ex["account_type"] = acc_type
        ex["is_cash"] = (acc_type == "CASH")
        amt = float(ex["amount"] or 0)
        if ex["is_cash"]:
            cash_expenses_total += amt
        else:
            non_cash_expenses_total += amt

        cat = ex["category"] or "Miscellaneous"
        if cat not in cat_map:
            cat_map[cat] = {"category": cat, "cash_amount": 0.0, "non_cash_amount": 0.0, "total": 0.0}
        if ex["is_cash"]:
            cat_map[cat]["cash_amount"] += amt
        else:
            cat_map[cat]["non_cash_amount"] += amt
        cat_map[cat]["total"] += amt

    expenses_by_category = sorted(list(cat_map.values()), key=lambda x: x["total"], reverse=True)
    total_expenses = cash_expenses_total + non_cash_expenses_total

    # Supplier Payments
    sup_rows = db.query_all("""
        SELECT amount, payment_method
        FROM supplier_ledger
        WHERE substr(timestamp, 1, 10) = ? AND transaction_type = 'PAYMENT'
    """, (d,))
    supplier_cash = sum(float(r["amount"] or 0) for r in sup_rows if lookups.is_cash_account(r["payment_method"]))
    supplier_non_cash = sum(float(r["amount"] or 0) for r in sup_rows if not lookups.is_cash_account(r["payment_method"]))

    # Customer Refunds
    ret_rows = db.query_all("""
        SELECT refund_amount, refund_type
        FROM returns
        WHERE substr(return_date, 1, 10) = ? 
           OR substr(COALESCE(transaction_date, ''), 1, 10) = ?
           OR substr(created_at, 1, 10) = ?
    """, (d, d, d))
    refunds_cash = sum(float(r["refund_amount"] or 0) for r in ret_rows if lookups.is_cash_account(r["refund_type"]))
    refunds_non_cash = sum(float(r["refund_amount"] or 0) for r in ret_rows if not lookups.is_cash_account(r["refund_type"]))
    total_refunds = refunds_cash + refunds_non_cash

    # Fetch existing closing if already recorded
    existing = db.query_one("SELECT * FROM day_closings WHERE closing_date = ?", (d,))
    if existing:
        opening_cash = float(existing["opening_cash"] or 0)
    else:
        # Default opening cash to previous day's closing actual cash
        prev_closing = db.query_one("SELECT actual_cash FROM day_closings WHERE closing_date < ? ORDER BY closing_date DESC LIMIT 1", (d,))
        opening_cash = float(prev_closing["actual_cash"]) if prev_closing and prev_closing["actual_cash"] is not None else 0.0

    total_cash_in = (
        cash_sales +
        udhaar_received_cash +
        repair_cash +
        software_cash +
        qs_comm
    )
    total_cash_out = cash_expenses_total + supplier_cash + refunds_cash
    expected_cash = opening_cash + total_cash_in - total_cash_out

    return {
        "date": d,
        "opening_cash": opening_cash,
        "cash_sales": cash_sales,
        "card_sales": card_sales,
        "online_sales": online_sales,
        "udhaar_sales": udhaar_sales,
        "udhaar_received": udhaar_received_cash,
        "udhaar_recovered": udhaar_received_cash,
        "udhaar_received_cash": udhaar_received_cash,
        "udhaar_received_non_cash": udhaar_received_non_cash,
        "repair_income": repair_cash,
        "software_income": software_cash,
        "software_income_cash": software_cash,
        "software_income_non_cash": software_non_cash,
        "quick_service_income": qs_comm,
        "cash_expenses_total": cash_expenses_total,
        "non_cash_expenses_total": non_cash_expenses_total,
        "total_expenses": total_expenses,
        "expenses_total": cash_expenses_total,  # Drawer-deducted expenses
        "expenses_list": expenses_list,
        "expenses_by_category": expenses_by_category,
        "supplier_payments": supplier_cash,
        "supplier_payments_cash": supplier_cash,
        "supplier_payments_non_cash": supplier_non_cash,
        "refunds": refunds_cash,
        "refunds_cash": refunds_cash,
        "refunds_non_cash": refunds_non_cash,
        "total_refunds": total_refunds,
        "total_cash_in": total_cash_in,
        "total_cash_out": total_cash_out,
        "expected_cash": expected_cash,
        "existing_record": existing
    }

calculate_day_closing = get_day_closing_data

def record_day_closing(actual_cash, opening_cash=0, closing_date=None, notes="", user_id=0, username=""):
    """Saves official day closing and drawer reconciliation."""
    d = closing_date or datetime.now().strftime("%Y-%m-%d")
    data = get_day_closing_data(d)
    
    act_cash = float(actual_cash)
    op_cash = float(opening_cash) if opening_cash is not None else data["opening_cash"]
    
    # Recalculate expected with specified opening cash
    exp_cash = op_cash + data["total_cash_in"] - data["total_cash_out"]
    diff = act_cash - exp_cash
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("""
            INSERT INTO day_closings (
                closing_date, opened_at, closed_at, opening_cash, 
                cash_sales, card_sales, online_sales, udhaar_sales, udhaar_received, 
                repair_income, software_income, quick_service_income, 
                expenses_total, supplier_payments, expected_cash, actual_cash, cash_difference, 
                closed_by_id, closed_by_name, notes, created_at,
                refunds, cash_expenses_total, non_cash_expenses_total
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(closing_date) DO UPDATE SET
                closed_at = excluded.closed_at,
                opening_cash = excluded.opening_cash,
                cash_sales = excluded.cash_sales,
                card_sales = excluded.card_sales,
                online_sales = excluded.online_sales,
                udhaar_sales = excluded.udhaar_sales,
                udhaar_received = excluded.udhaar_received,
                repair_income = excluded.repair_income,
                software_income = excluded.software_income,
                quick_service_income = excluded.quick_service_income,
                expenses_total = excluded.expenses_total,
                supplier_payments = excluded.supplier_payments,
                expected_cash = excluded.expected_cash,
                actual_cash = excluded.actual_cash,
                cash_difference = excluded.cash_difference,
                closed_by_id = excluded.closed_by_id,
                closed_by_name = excluded.closed_by_name,
                notes = excluded.notes,
                refunds = excluded.refunds,
                cash_expenses_total = excluded.cash_expenses_total,
                non_cash_expenses_total = excluded.non_cash_expenses_total
        """, (
            d, f"{d} 09:00:00", now, op_cash, 
            data["cash_sales"], data["card_sales"], data["online_sales"], data["udhaar_sales"], data["udhaar_received"], 
            data["repair_income"], data["software_income"], data["quick_service_income"], 
            data["cash_expenses_total"], data["supplier_payments"], exp_cash, act_cash, diff, 
            user_id, username, notes, now,
            data["refunds_cash"], data["cash_expenses_total"], data["non_cash_expenses_total"]
        ))

    auth.log_audit(user_id, username, "DAY_CLOSING", "day_closings", d, "", f"Expected: Rs. {exp_cash:,.0f}, Actual: Rs. {act_cash:,.0f}, Diff: Rs. {diff:,.0f}")
    return {
        "success": True,
        "closing_date": d,
        "opening_cash": op_cash,
        "expected_cash": exp_cash,
        "actual_cash": act_cash,
        "cash_difference": diff,
        "closed_at": now
    }

def get_month_day_closings(month_str):
    """
    Retrieves and reconciles all day closing records for a given month (YYYY-MM).
    Returns list of daily records, status (CLOSED vs OPEN), difference, and monthly totals.
    """
    import calendar
    m = month_str.strip()[:7] if month_str else datetime.now().strftime("%Y-%m")
    try:
        parts = m.split("-")
        y, mo = int(parts[0]), int(parts[1])
        last_day = calendar.monthrange(y, mo)[1]
    except Exception:
        y, mo, last_day = 2026, 10, 31

    today = datetime.now().strftime("%Y-%m-%d")
    saved_closings = {r["closing_date"]: dict(r) for r in db.query_all(
        "SELECT * FROM day_closings WHERE substr(closing_date, 1, 7) = ? ORDER BY closing_date ASC", (m,)
    )}

    days = []
    tot = {
        "days_count": last_day,
        "closed_count": 0,
        "open_count": 0,
        "total_cash_in": 0.0,
        "total_cash_out": 0.0,
        "expected_cash": 0.0,
        "actual_cash": 0.0,
        "cash_difference": 0.0,
        "expenses_total": 0.0,
        "sales_cash": 0.0,
        "udhaar_received": 0.0,
        "services_cash": 0.0
    }

    max_day = last_day if m < today[:7] else min(last_day, int(today[-2:]))

    for day_num in range(1, max_day + 1):
        dt_str = f"{y:04d}-{mo:02d}-{day_num:02d}"
        saved = saved_closings.get(dt_str)
        if saved:
            is_closed = True
            op = float(saved.get("opening_cash") or 0)
            cs = float(saved.get("cash_sales") or 0)
            ur = float(saved.get("udhaar_received") or 0)
            rep = float(saved.get("repair_income") or 0)
            sft = float(saved.get("software_income") or 0)
            qs = float(saved.get("quick_service_income") or 0)
            services = rep + sft + qs
            inflow = cs + ur + services
            exp = float(saved.get("expenses_total") or 0)
            sup = float(saved.get("supplier_payments") or 0)
            outflow = exp + sup
            exp_c = float(saved.get("expected_cash") or 0)
            act_c = float(saved.get("actual_cash") or 0)
            diff = float(saved.get("cash_difference") or 0)
            closed_at = saved.get("closed_at") or ""
            closed_by = saved.get("closed_by_name") or "Admin"
            notes = saved.get("notes") or ""
            tot["closed_count"] += 1
        else:
            is_closed = False
            live = get_day_closing_data(dt_str)
            op = float(live.get("opening_cash") or 0)
            cs = float(live.get("cash_sales") or 0)
            ur = float(live.get("udhaar_received") or 0)
            services = float(live.get("repair_income") or 0) + float(live.get("software_income") or 0) + float(live.get("quick_service_income") or 0)
            inflow = float(live.get("total_cash_in") or 0)
            exp = float(live.get("cash_expenses_total") or 0)
            sup = float(live.get("supplier_payments") or 0)
            outflow = float(live.get("total_cash_out") or 0)
            exp_c = float(live.get("expected_cash") or 0)
            act_c = 0.0
            diff = 0.0
            closed_at = ""
            closed_by = ""
            notes = "Unclosed"
            tot["open_count"] += 1

        day_record = {
            "date": dt_str,
            "status": "CLOSED" if is_closed else "OPEN",
            "is_closed": is_closed,
            "opening_cash": op,
            "cash_sales": cs,
            "udhaar_received": ur,
            "services_cash": services,
            "inflow": inflow,
            "expenses": exp,
            "supplier_payments": sup,
            "outflow": outflow,
            "expected_cash": exp_c,
            "actual_cash": act_c,
            "difference": diff,
            "closed_at": closed_at,
            "closed_by": closed_by,
            "notes": notes
        }
        days.append(day_record)

        tot["total_cash_in"] += inflow
        tot["total_cash_out"] += outflow
        tot["expenses_total"] += exp
        tot["sales_cash"] += cs
        tot["udhaar_received"] += ur
        tot["services_cash"] += services
        if is_closed:
            tot["expected_cash"] += exp_c
            tot["actual_cash"] += act_c
            tot["cash_difference"] += diff

    # Fetch all itemized expenses for this month
    month_expenses_rows = db.query_all("""
        SELECT e.*, 
               COALESCE(NULLIF(e.expense_date, ''), substr(e.created_at, 1, 10)) AS eff_date,
               COALESCE(u.full_name, u.username, 'Admin') AS user_name
        FROM expenses e
        LEFT JOIN users u ON e.user_id = u.id
        WHERE (
            substr(e.expense_date, 1, 7) = ? 
            OR substr(COALESCE(e.transaction_date, ''), 1, 7) = ?
            OR (e.expense_date IS NULL AND substr(e.created_at, 1, 7) = ?)
        )
        AND (e.is_void IS NULL OR e.is_void = 0)
        ORDER BY eff_date DESC, e.id DESC
    """, (m, m, m))

    month_expenses = []
    cat_summary = {}
    tot_cash_exp = 0.0
    tot_non_cash_exp = 0.0

    for ex in month_expenses_rows:
        ex_d = dict(ex)
        acc_type = lookups.get_account_type(ex_d.get("payment_method"))
        ex_d["account_type"] = acc_type
        ex_d["is_cash"] = (acc_type == "CASH")
        amt = float(ex_d.get("amount") or 0)
        if ex_d["is_cash"]:
            tot_cash_exp += amt
        else:
            tot_non_cash_exp += amt
        cat = ex_d.get("category") or "General"
        if cat not in cat_summary:
            cat_summary[cat] = {"category": cat, "cash": 0.0, "non_cash": 0.0, "total": 0.0, "count": 0}
        if ex_d["is_cash"]:
            cat_summary[cat]["cash"] += amt
        else:
            cat_summary[cat]["non_cash"] += amt
        cat_summary[cat]["total"] += amt
        cat_summary[cat]["count"] += 1
        month_expenses.append(ex_d)

    return {
        "month": m,
        "days": days,
        "totals": tot,
        "expenses": month_expenses,
        "expenses_by_category": sorted(list(cat_summary.values()), key=lambda x: x["total"], reverse=True),
        "total_cash_expenses": tot_cash_exp,
        "total_non_cash_expenses": tot_non_cash_exp
    }

# ═══════════════════════════════════════════════════════════
# 4. MONTHLY REPORT & INVENTORY ANALYTICS
# ═══════════════════════════════════════════════════════════

def get_monthly_report(year, month):
    """
    Comprehensive monthly business analysis:
    - 5 streams performance
    - Expenses by category
    - Net profit margin
    - Top 5 selling phone models
    - Aging inventory alerts
    """
    m_str = f"{int(year):04d}-{int(month):02d}"
    start_d = f"{m_str}-01"
    end_d = f"{m_str}-31"

    earnings = get_earnings_center(start_d, end_d)

    # Expenses categorized
    exp_cats = db.query_all("""
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE expense_date BETWEEN ? AND ?
        GROUP BY category
        ORDER BY total DESC
    """, (start_d, end_d))

    # Top selling models
    top_models = db.query_all("""
        SELECT p.brand, p.name AS model_name, SUM(si.qty) AS total_sold, SUM(si.unit_price * si.qty) AS revenue
        FROM sale_items si
        JOIN variants v ON si.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        JOIN sales s ON si.sale_id = s.id
        WHERE substr(s.created_at, 1, 7) = ? AND s.status != 'CANCELLED'
        GROUP BY p.id
        ORDER BY total_sold DESC
        LIMIT 5
    """, (m_str,))

    # Aging phones (>30 days in stock)
    aging = db.query_one("""
        SELECT COUNT(*) AS aging_count, COALESCE(SUM(cost_price), 0) AS aging_value
        FROM units
        WHERE status = 'IN_STOCK' AND (JULIANDAY('now') - JULIANDAY(date_in)) >= 30
    """)

    return {
        "month": m_str,
        "earnings": earnings,
        "expenses_by_category": exp_cats,
        "top_selling_models": top_models,
        "aging_stock": aging
    }

# ═══════════════════════════════════════════════════════════
# 5. DATE-WISE DAILY SALES ANALYTICS (FIX 3)
# ═══════════════════════════════════════════════════════════

def get_date_wise_sales_summary(start_date, end_date, salesperson_id=None, payment_method=None, item_type=None, is_admin=True):
    """
    Computes date-wise daily sales breakdown for any date range:
    - Invoices count, phones sold, accessories sold
    - Gross sale, discounts, returns, NET sale
    - Cost, profit (Admin only; stripped for Employee)
    - Cash, card, online, udhaar payment split
    - Expenses of that day, net of the day (Admin only)
    - Totals row
    Speed target: <= 300 ms for any month.
    """
    date_expr_sales = "COALESCE(NULLIF(s.transaction_date, ''), substr(s.created_at, 1, 10))"

    # Base WHERE clauses for sales
    s_where = ["s.status NOT IN ('CANCELLED', 'VOIDED')", f"{date_expr_sales} BETWEEN ? AND ?"]
    s_params = [start_date, end_date]

    if salesperson_id:
        s_where.append("s.salesperson_id = ?")
        s_params.append(int(salesperson_id))

    if payment_method:
        pm_clean = payment_method.strip().upper()
        if pm_clean == "CASH":
            s_where.append("(UPPER(s.payment_method) LIKE '%CASH%' OR UPPER(s.payment_method) LIKE '%DRAWER%')")
        elif pm_clean == "CARD":
            s_where.append("UPPER(s.payment_method) = 'CARD'")
        elif pm_clean in ("ONLINE", "BANK"):
            s_where.append("(UPPER(s.payment_method) IN ('ONLINE', 'BANK') OR UPPER(s.payment_method) LIKE '%EASYPAISA%' OR UPPER(s.payment_method) LIKE '%JAZZCASH%')")
        elif pm_clean == "UDHAAR":
            s_where.append("s.balance_due > 0")
        else:
            s_where.append("s.payment_method = ?")
            s_params.append(payment_method)

    s_where_sql = " AND ".join(s_where)

    # 1. Daily Invoices & Revenue Breakdown
    sales_query = f"""
        SELECT 
            {date_expr_sales} AS sale_date,
            COUNT(DISTINCT s.id) AS invoices_count,
            COALESCE(SUM(s.grand_total), 0) AS gross_sale,
            COALESCE(SUM(s.discount_amount), 0) AS discount_total,
            COALESCE(SUM(CASE WHEN (UPPER(s.payment_method) LIKE '%CASH%' OR UPPER(s.payment_method) LIKE '%DRAWER%') THEN s.paid_amount ELSE 0 END), 0) AS cash_paid,
            COALESCE(SUM(CASE WHEN UPPER(s.payment_method) = 'CARD' THEN s.paid_amount ELSE 0 END), 0) AS card_paid,
            COALESCE(SUM(CASE WHEN (UPPER(s.payment_method) IN ('ONLINE', 'BANK') OR UPPER(s.payment_method) LIKE '%EASYPAISA%' OR UPPER(s.payment_method) LIKE '%JAZZCASH%') THEN s.paid_amount ELSE 0 END), 0) AS online_paid,
            COALESCE(SUM(s.balance_due), 0) AS udhaar_amount
        FROM sales s
        WHERE {s_where_sql}
        GROUP BY sale_date
    """
    sales_daily = {r["sale_date"]: dict(r) for r in db.query_all(sales_query, tuple(s_params))}

    # 2. Daily Items Sold (Phones vs Accessories, Cost, Profit)
    item_where = list(s_where)
    item_params = list(s_params)
    if item_type:
        it_clean = item_type.strip().upper()
        if it_clean == "PHONE":
            item_where.append("si.item_type = 'PHONE'")
        elif it_clean in ("ACCESSORY", "ACC"):
            item_where.append("si.item_type != 'PHONE'")

    item_where_sql = " AND ".join(item_where)
    items_query = f"""
        SELECT 
            {date_expr_sales} AS item_date,
            COALESCE(SUM(CASE WHEN si.item_type = 'PHONE' THEN si.qty ELSE 0 END), 0) AS phones_sold,
            COALESCE(SUM(CASE WHEN si.item_type != 'PHONE' THEN si.qty ELSE 0 END), 0) AS acc_sold,
            COALESCE(SUM(si.cost_price * si.qty), 0) AS cost_total,
            COALESCE(SUM((si.unit_price - si.cost_price) * si.qty - si.discount), 0) AS profit_total
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE {item_where_sql} AND (si.is_returned IS NULL OR si.is_returned = 0)
        GROUP BY item_date
    """
    items_daily = {r["item_date"]: dict(r) for r in db.query_all(items_query, tuple(item_params))}

    # 3. Daily Returns
    ret_query = """
        SELECT 
            COALESCE(return_date, substr(created_at, 1, 10)) AS ret_date,
            COALESCE(SUM(refund_amount), 0) AS refund_total
        FROM returns
        WHERE COALESCE(return_date, substr(created_at, 1, 10)) BETWEEN ? AND ?
        GROUP BY ret_date
    """
    returns_daily = {r["ret_date"]: float(r["refund_total"]) for r in db.query_all(ret_query, (start_date, end_date))}

    # 4. Daily Expenses (Admin only)
    expenses_daily = {}
    if is_admin:
        exp_query = """
            SELECT 
                substr(COALESCE(NULLIF(transaction_date, ''), expense_date, created_at), 1, 10) AS exp_date,
                COALESCE(SUM(amount), 0) AS expense_total
            FROM expenses
            WHERE (is_void IS NULL OR is_void = 0)
              AND substr(COALESCE(NULLIF(transaction_date, ''), expense_date, created_at), 1, 10) BETWEEN ? AND ?
            GROUP BY exp_date
        """
        expenses_daily = {r["exp_date"]: float(r["expense_total"]) for r in db.query_all(exp_query, (start_date, end_date))}

    # 5. Daily Udhaar Recoveries
    udh_query = """
        SELECT 
            COALESCE(NULLIF(transaction_date, ''), substr(timestamp, 1, 10)) AS udh_date,
            COALESCE(SUM(amount), 0) AS udhaar_recovered,
            COALESCE(SUM(CASE WHEN UPPER(payment_method) LIKE '%CASH%' OR UPPER(payment_method) LIKE '%DRAWER%' THEN amount ELSE 0 END), 0) AS udhaar_cash
        FROM udhaar_ledger
        WHERE transaction_type IN ('PAYMENT', 'INSTALLMENT_PAYMENT')
          AND COALESCE(NULLIF(transaction_date, ''), substr(timestamp, 1, 10)) BETWEEN ? AND ?
        GROUP BY udh_date
    """
    udh_daily = {r["udh_date"]: {"recovered": float(r["udhaar_recovered"]), "cash": float(r["udhaar_cash"])} for r in db.query_all(udh_query, (start_date, end_date))}

    # 6. Daily Quick Services (EasyPaisa, JazzCash, Load, Bills)
    qs_query = """
        SELECT 
            substr(timestamp, 1, 10) AS qs_date,
            COUNT(*) AS count,
            COALESCE(SUM(amount), 0) AS volume,
            COALESCE(SUM(profit), 0) AS profit
        FROM quick_services
        WHERE (is_void IS NULL OR is_void = 0)
          AND substr(timestamp, 1, 10) BETWEEN ? AND ?
        GROUP BY qs_date
    """
    qs_daily = {r["qs_date"]: dict(r) for r in db.query_all(qs_query, (start_date, end_date))}

    # 7. Daily Hardware Repairs Profit
    rep_query = """
        SELECT 
            substr(COALESCE(NULLIF(delivered_at, ''), created_at), 1, 10) AS rep_date,
            COUNT(*) AS count,
            COALESCE(SUM(profit), 0) AS profit
        FROM repair_jobs
        WHERE status = 'DELIVERED'
          AND substr(COALESCE(NULLIF(delivered_at, ''), created_at), 1, 10) BETWEEN ? AND ?
        GROUP BY rep_date
    """
    rep_daily = {r["rep_date"]: dict(r) for r in db.query_all(rep_query, (start_date, end_date))}

    # 8. Daily Software Services Profit
    sft_query = """
        SELECT 
            substr(created_at, 1, 10) AS sft_date,
            COUNT(*) AS count,
            COALESCE(SUM(profit), 0) AS profit
        FROM software_jobs
        WHERE status = 'COMPLETED'
          AND substr(created_at, 1, 10) BETWEEN ? AND ?
        GROUP BY sft_date
    """
    sft_daily = {r["sft_date"]: dict(r) for r in db.query_all(sft_query, (start_date, end_date))}

    # Collect all unique dates in the range
    all_dates = set(sales_daily.keys()).union(items_daily.keys()).union(returns_daily.keys()).union(udh_daily.keys()).union(qs_daily.keys()).union(rep_daily.keys()).union(sft_daily.keys())
    if is_admin:
        all_dates = all_dates.union(expenses_daily.keys())
    sorted_dates = sorted(list(all_dates), reverse=True)

    rows = []
    tot = {
        "invoices_count": 0, "phones_sold": 0, "acc_sold": 0,
        "gross_sale": 0.0, "discounts": 0.0, "returns": 0.0, "net_sale": 0.0,
        "cost": 0.0, "sales_profit": 0.0, "qs_profit": 0.0, "repair_profit": 0.0, "software_profit": 0.0,
        "profit": 0.0,
        "cash_paid": 0.0, "card_paid": 0.0, "online_paid": 0.0, "udhaar_amount": 0.0,
        "udhaar_recovered": 0.0, "udhaar_rec_cash": 0.0,
        "expenses": 0.0, "net_of_day": 0.0
    }

    for dt in sorted_dates:
        sd = sales_daily.get(dt, {})
        it = items_daily.get(dt, {})
        ret_val = returns_daily.get(dt, 0.0)
        exp_val = expenses_daily.get(dt, 0.0)
        qs_d = qs_daily.get(dt, {})
        rep_d = rep_daily.get(dt, {})
        sft_d = sft_daily.get(dt, {})

        inv_cnt = int(sd.get("invoices_count", 0))
        phones = int(it.get("phones_sold", 0))
        accs = int(it.get("acc_sold", 0))
        gross = float(sd.get("gross_sale", 0.0))
        disc = float(sd.get("discount_total", 0.0))
        net_s = max(0.0, gross - ret_val)
        c_cost = float(it.get("cost_total", 0.0))
        c_prof = float(it.get("profit_total", 0.0)) - ret_val
        qs_prof = float(qs_d.get("profit", 0.0))
        rep_prof = float(rep_d.get("profit", 0.0))
        sft_prof = float(sft_d.get("profit", 0.0))
        day_gross_profit = c_prof + qs_prof + rep_prof + sft_prof

        cash = float(sd.get("cash_paid", 0.0))
        card = float(sd.get("card_paid", 0.0))
        online = float(sd.get("online_paid", 0.0))
        udhaar = float(sd.get("udhaar_amount", 0.0))
        net_day = day_gross_profit - exp_val

        udh_info = udh_daily.get(dt, {"recovered": 0.0, "cash": 0.0})
        u_rec = float(udh_info["recovered"])
        u_rec_cash = float(udh_info["cash"])

        day_dict = {
            "date": dt,
            "invoices_count": inv_cnt,
            "phones_sold": phones,
            "accessories_sold": accs,
            "gross_sale": gross,
            "discounts": disc,
            "returns": ret_val,
            "net_sale": net_s,
            "cash_paid": cash,
            "card_paid": card,
            "online_paid": online,
            "udhaar_amount": udhaar,
            "udhaar_recovered": u_rec,
            "udhaar_rec_cash": u_rec_cash,
            "qs_count": int(qs_d.get("count", 0)),
            "qs_volume": float(qs_d.get("volume", 0.0)),
            "qs_profit": qs_prof,
        }

        if is_admin:
            day_dict["cost"] = c_cost
            day_dict["sales_profit"] = c_prof
            day_dict["qs_profit"] = qs_prof
            day_dict["repair_profit"] = rep_prof
            day_dict["software_profit"] = sft_prof
            day_dict["gross_profit"] = day_gross_profit
            day_dict["profit"] = day_gross_profit
            day_dict["expenses"] = exp_val
            day_dict["net_of_day"] = net_day

        rows.append(day_dict)

        tot["invoices_count"] += inv_cnt
        tot["phones_sold"] += phones
        tot["acc_sold"] += accs
        tot["gross_sale"] += gross
        tot["discounts"] += disc
        tot["returns"] += ret_val
        tot["net_sale"] += net_s
        tot["cost"] += c_cost
        tot["sales_profit"] += c_prof
        tot["qs_profit"] += qs_prof
        tot["repair_profit"] += rep_prof
        tot["software_profit"] += sft_prof
        tot["profit"] += day_gross_profit
        tot["cash_paid"] += cash
        tot["card_paid"] += card
        tot["online_paid"] += online
        tot["udhaar_amount"] += udhaar
        tot["udhaar_recovered"] += u_rec
        tot["udhaar_rec_cash"] += u_rec_cash
        tot["expenses"] += exp_val
        tot["net_of_day"] += net_day

    if not is_admin:
        # Strip financial sensitive totals for Employee
        tot.pop("cost", None)
        tot.pop("sales_profit", None)
        tot.pop("qs_profit", None)
        tot.pop("repair_profit", None)
        tot.pop("software_profit", None)
        tot.pop("profit", None)
        tot.pop("expenses", None)
        tot.pop("net_of_day", None)

    return {
        "days": rows,
        "totals": tot,
        "start_date": start_date,
        "end_date": end_date,
        "is_admin": is_admin
    }

# ═══════════════════════════════════════════════════════════
# 6. COMPREHENSIVE DETAILED SALES & AUDIT DATA ENGINE
# ═══════════════════════════════════════════════════════════

def get_detailed_sales_report_data(start_date, end_date, salesperson_id=None, payment_method=None, is_admin=True):
    """
    Retrieves full comprehensive sales and business report data:
    - All sales with itemized sold items (product name, model, variant, IMEIs, qty, price, discount, total, profit)
    - All expenses with complete details (date, description, category, account, user, amount)
    - All udhaar payments collected in period
    - Top products sold summary
    - Drawer closing status (if start_date == end_date)
    - Aggregated financial totals
    """
    date_expr_sales = "COALESCE(NULLIF(s.transaction_date, ''), substr(s.created_at, 1, 10))"

    s_where = ["s.status NOT IN ('CANCELLED', 'VOIDED')", f"{date_expr_sales} BETWEEN ? AND ?"]
    s_params = [start_date, end_date]

    if salesperson_id:
        s_where.append("s.salesperson_id = ?")
        s_params.append(int(salesperson_id))

    if payment_method:
        pm_clean = payment_method.strip().upper()
        if pm_clean == "CASH":
            s_where.append("(UPPER(s.payment_method) LIKE '%CASH%' OR UPPER(s.payment_method) LIKE '%DRAWER%')")
        elif pm_clean == "CARD":
            s_where.append("UPPER(s.payment_method) = 'CARD'")
        elif pm_clean in ("ONLINE", "BANK"):
            s_where.append("(UPPER(s.payment_method) IN ('ONLINE', 'BANK') OR UPPER(s.payment_method) LIKE '%EASYPAISA%' OR UPPER(s.payment_method) LIKE '%JAZZCASH%')")
        elif pm_clean == "UDHAAR":
            s_where.append("s.balance_due > 0")
        else:
            s_where.append("s.payment_method = ?")
            s_params.append(payment_method)

    s_where_sql = " AND ".join(s_where)

    sales_rows = db.query_all(f"""
        SELECT s.*, 
               {date_expr_sales} AS effective_date,
               COALESCE(s.salesperson_name, u.full_name, 'Staff') AS staff_name
        FROM sales s
        LEFT JOIN users u ON s.salesperson_id = u.id
        WHERE {s_where_sql}
        ORDER BY effective_date DESC, s.created_at DESC, s.id DESC
    """, tuple(s_params))

    sales_list = [dict(s) for s in sales_rows]
    sale_ids = [s["id"] for s in sales_list]
    items_by_sale = {}

    if sale_ids:
        placeholders = ",".join("?" for _ in sale_ids)
        items = db.query_all(f"""
            SELECT si.*
            FROM sale_items si
            WHERE si.sale_id IN ({placeholders})
            ORDER BY si.id ASC
        """, tuple(sale_ids))
        for it in items:
            it_d = dict(it)
            if not is_admin:
                it_d.pop("cost_price", None)
                it_d.pop("profit", None)
            items_by_sale.setdefault(it["sale_id"], []).append(it_d)

    # Attach items to each sale and calculate stats
    prod_map = {}
    phones_sold = 0
    acc_sold = 0
    total_cost = 0.0
    total_profit = 0.0

    for s in sales_list:
        s["items"] = items_by_sale.get(s["id"], [])
        for it in s["items"]:
            if it.get("is_returned"):
                continue
            qty = int(it.get("qty") or 1)
            line_tot = float(it.get("line_total") or 0)
            cost_p = float(it.get("cost_price") or 0)
            prof = float(it.get("profit") or 0)

            if it.get("item_type") == "PHONE":
                phones_sold += qty
            else:
                acc_sold += qty

            if is_admin:
                total_cost += cost_p * qty
                total_profit += prof

            key = (it.get("item_name") or "Product", it.get("variant_details") or "", it.get("item_type") or "ACC")
            if key not in prod_map:
                prod_map[key] = {
                    "item_name": key[0],
                    "variant_details": key[1],
                    "item_type": key[2],
                    "qty": 0,
                    "revenue": 0.0,
                    "profit": 0.0
                }
            prod_map[key]["qty"] += qty
            prod_map[key]["revenue"] += line_tot
            if is_admin:
                prod_map[key]["profit"] += prof

    products_sold_summary = sorted(list(prod_map.values()), key=lambda x: x["revenue"], reverse=True)

    # Itemized Expenses query
    expenses_rows = db.query_all("""
        SELECT e.*, 
               COALESCE(NULLIF(e.expense_date, ''), substr(e.created_at, 1, 10)) AS eff_date,
               COALESCE(u.full_name, u.username, 'Admin') AS user_name
        FROM expenses e
        LEFT JOIN users u ON e.user_id = u.id
        WHERE (
            substr(e.expense_date, 1, 10) BETWEEN ? AND ?
            OR substr(COALESCE(e.transaction_date, ''), 1, 10) BETWEEN ? AND ?
            OR (e.expense_date IS NULL AND substr(e.created_at, 1, 10) BETWEEN ? AND ?)
        )
        AND (e.is_void IS NULL OR e.is_void = 0)
        ORDER BY eff_date DESC, e.id DESC
    """, (start_date, end_date, start_date, end_date, start_date, end_date))

    cash_exp_tot = 0.0
    non_cash_exp_tot = 0.0
    exp_cats = {}
    expenses_list = []

    for ex in expenses_rows:
        ex_d = dict(ex)
        acc_type = lookups.get_account_type(ex_d.get("payment_method"))
        ex_d["account_type"] = acc_type
        ex_d["is_cash"] = (acc_type == "CASH")
        amt = float(ex_d.get("amount") or 0)
        if ex_d["is_cash"]:
            cash_exp_tot += amt
        else:
            non_cash_exp_tot += amt
        cat = ex_d.get("category") or "General"
        if cat not in exp_cats:
            exp_cats[cat] = {"category": cat, "cash": 0.0, "non_cash": 0.0, "total": 0.0, "count": 0}
        if ex_d["is_cash"]:
            exp_cats[cat]["cash"] += amt
        else:
            exp_cats[cat]["non_cash"] += amt
        exp_cats[cat]["total"] += amt
        exp_cats[cat]["count"] += 1
        expenses_list.append(ex_d)

    total_expenses = cash_exp_tot + non_cash_exp_tot

    # Udhaar recoveries collected
    udhaar_rows = db.query_all("""
        SELECT ul.*, 
               COALESCE(NULLIF(ul.transaction_date, ''), substr(ul.timestamp, 1, 10)) AS eff_date,
               COALESCE(c.name, 'Customer') AS customer_name, 
               COALESCE(c.phone, '') AS customer_phone
        FROM udhaar_ledger ul
        LEFT JOIN customers c ON ul.customer_id = c.id
        WHERE COALESCE(NULLIF(ul.transaction_date, ''), substr(ul.timestamp, 1, 10)) BETWEEN ? AND ?
          AND ul.transaction_type IN ('PAYMENT', 'INSTALLMENT_PAYMENT')
        ORDER BY eff_date DESC, ul.id DESC
    """, (start_date, end_date))

    udhaar_list = []
    udhaar_rec_cash = 0.0
    udhaar_rec_non_cash = 0.0
    for u in udhaar_rows:
        u_d = dict(u)
        is_c = lookups.is_cash_account(u_d.get("payment_method"))
        u_d["is_cash"] = is_c
        amt = float(u_d.get("amount") or 0)
        if is_c:
            udhaar_rec_cash += amt
        else:
            udhaar_rec_non_cash += amt
        udhaar_list.append(u_d)

    # Quick Services query (EasyPaisa, JazzCash, Loads, Bills)
    qs_rows = db.query_all("""
        SELECT qs.*, 
               COALESCE(NULLIF(substr(qs.timestamp, 1, 10), ''), '') AS eff_date,
               COALESCE(u.full_name, u.username, 'Staff') AS agent_name
        FROM quick_services qs
        LEFT JOIN users u ON qs.agent_id = u.id
        WHERE (qs.is_void IS NULL OR qs.is_void = 0)
          AND substr(qs.timestamp, 1, 10) BETWEEN ? AND ?
        ORDER BY qs.timestamp DESC, qs.id DESC
    """, (start_date, end_date))

    qs_list = []
    qs_tot_send = 0.0
    qs_tot_recv = 0.0
    qs_tot_profit = 0.0
    qs_cash_inflow = 0.0
    qs_cash_outflow = 0.0
    for q in qs_rows:
        qd = dict(q)
        act = (qd.get("action_type") or "SEND").strip().upper()
        amt = float(qd.get("amount") or 0)
        comm = float(qd.get("profit") or qd.get("fee_commission") or 0)
        qd["action_type"] = act
        qd["comm_amount"] = comm
        qs_tot_profit += comm

        if act in ("RECEIVE", "CASH_OUT", "WITHDRAWAL"):
            qs_tot_recv += amt
            cash_given = max(0.0, amt - comm)
            qd["cash_flow_type"] = "OUT"
            qd["cash_flow_amount"] = cash_given
            qs_cash_outflow += cash_given
        else:
            qs_tot_send += amt
            cash_taken = amt + comm
            qd["cash_flow_type"] = "IN"
            qd["cash_flow_amount"] = cash_taken
            qs_cash_inflow += cash_taken

        qs_list.append(qd)

    # Hardware Repairs & Software Services profit queries
    rep_row = db.query_one("""
        SELECT COUNT(*) AS rep_count,
               COALESCE(SUM(total_charged), 0) AS rep_revenue,
               COALESCE(SUM(profit), 0) AS rep_profit
        FROM repair_jobs
        WHERE status = 'DELIVERED'
          AND substr(COALESCE(NULLIF(delivered_at, ''), created_at), 1, 10) BETWEEN ? AND ?
    """, (start_date, end_date))
    rep_profit = float(rep_row["rep_profit"]) if rep_row else 0.0
    rep_revenue = float(rep_row["rep_revenue"]) if rep_row else 0.0
    rep_count = int(rep_row["rep_count"]) if rep_row else 0

    sft_row = db.query_one("""
        SELECT COUNT(*) AS sft_count,
               COALESCE(SUM(price_charged), 0) AS sft_revenue,
               COALESCE(SUM(profit), 0) AS sft_profit
        FROM software_jobs
        WHERE status = 'COMPLETED'
          AND substr(created_at, 1, 10) BETWEEN ? AND ?
    """, (start_date, end_date))
    sft_profit = float(sft_row["sft_profit"]) if sft_row else 0.0
    sft_revenue = float(sft_row["sft_revenue"]) if sft_row else 0.0
    sft_count = int(sft_row["sft_count"]) if sft_row else 0

    # Totals computation
    gross_sale = sum(float(s.get("grand_total") or 0) for s in sales_list)
    discount_tot = sum(float(s.get("discount_amount") or 0) for s in sales_list)
    paid_tot = sum(float(s.get("paid_amount") or 0) for s in sales_list)
    due_tot = sum(float(s.get("balance_due") or 0) for s in sales_list)
    ret_tot = sum(float(s.get("returned_amount") or 0) for s in sales_list)
    net_sale = gross_sale - ret_tot

    cash_sales = sum(float(s.get("paid_amount") or 0) for s in sales_list if lookups.is_cash_account(s.get("payment_method")))
    card_sales = sum(float(s.get("paid_amount") or 0) for s in sales_list if "card" in (s.get("payment_method") or "").lower())
    online_sales = sum(float(s.get("paid_amount") or 0) for s in sales_list if not lookups.is_cash_account(s.get("payment_method")) and "card" not in (s.get("payment_method") or "").lower())

    total_gross_income = total_profit + qs_tot_profit + rep_profit + sft_profit
    net_profit = total_gross_income - total_expenses

    day_closing = None
    if start_date == end_date:
        try:
            day_closing = get_day_closing_data(start_date)
        except Exception:
            day_closing = None

    totals = {
        "invoices_count": len(sales_list),
        "phones_sold": phones_sold,
        "acc_sold": acc_sold,
        "gross_sale": gross_sale,
        "discounts": discount_tot,
        "returns": ret_tot,
        "net_sale": net_sale,
        "paid_total": paid_tot,
        "balance_due": due_tot,
        "cash_sales": cash_sales,
        "card_sales": card_sales,
        "online_sales": online_sales,
        "udhaar_recovered": udhaar_rec_cash + udhaar_rec_non_cash,
        "udhaar_rec_cash": udhaar_rec_cash,
        "udhaar_rec_non_cash": udhaar_rec_non_cash,
        "expenses_total": total_expenses,
        "cash_expenses_total": cash_exp_tot,
        "non_cash_expenses_total": non_cash_exp_tot,
        "total_cash_drawer_inflow": cash_sales + udhaar_rec_cash,
        "net_cash_drawer": (cash_sales + udhaar_rec_cash) - cash_exp_tot,
        "qs_count": len(qs_list),
        "qs_send_vol": qs_tot_send,
        "qs_recv_vol": qs_tot_recv,
        "qs_total_vol": qs_tot_send + qs_tot_recv,
        "qs_profit": qs_tot_profit,
        "qs_cash_inflow": qs_cash_inflow,
        "qs_cash_outflow": qs_cash_outflow,
        "repair_profit": rep_profit,
        "repair_revenue": rep_revenue,
        "repair_count": rep_count,
        "software_profit": sft_profit,
        "software_revenue": sft_revenue,
        "software_count": sft_count,
        "total_gross_income": total_gross_income,
    }

    if is_admin:
        totals["cost"] = total_cost
        totals["sales_profit"] = total_profit
        totals["profit"] = total_gross_income
        totals["net_of_period"] = net_profit
        totals["net_profit"] = net_profit

    return {
        "start_date": start_date,
        "end_date": end_date,
        "is_single_day": (start_date == end_date),
        "is_admin": is_admin,
        "sales": sales_list,
        "products_sold": products_sold_summary,
        "expenses": expenses_list,
        "expenses_by_category": sorted(list(exp_cats.values()), key=lambda x: x["total"], reverse=True),
        "udhaar_recoveries": udhaar_list,
        "quick_services": qs_list,
        "qs_totals": {
            "count": len(qs_list),
            "send_vol": qs_tot_send,
            "recv_vol": qs_tot_recv,
            "total_vol": qs_tot_send + qs_tot_recv,
            "profit": qs_tot_profit,
            "cash_inflow": qs_cash_inflow,
            "cash_outflow": qs_cash_outflow,
        },
        "day_closing": day_closing,
        "totals": totals
    }

