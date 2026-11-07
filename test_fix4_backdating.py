# test_fix4_backdating.py
# Comprehensive test suite for Gate 5: Back-Dated Transactions & Dual Timestamps

import pytest
from datetime import datetime, timedelta
import db, auth, pos, accounting, purchasing, credit, inventory

@pytest.fixture(autouse=True)
def init_test_db():
    db.init_db()

def test_future_date_rejected():
    """Future dates must be strictly rejected by validate_backdate_entry."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    val = accounting.validate_backdate_entry(tomorrow, user_id=1, username="admin")
    assert val["valid"] is False
    assert "cannot be in the future" in val["error"]

def test_staff_permission_check():
    """Non-admin user without can_backdate permission must be rejected with 403 / Access Denied."""
    past_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    staff_user = db.query_one("SELECT * FROM users WHERE role = 'staff'")
    if not staff_user:
        staff_id = db.execute("INSERT INTO users (username, password_hash, role, can_backdate) VALUES ('staff_test', 'hash123', 'staff', 0)")
        staff_user = db.query_one("SELECT * FROM users WHERE id = ?", (staff_id,))

    # Staff with can_backdate = 0
    db.execute("UPDATE users SET can_backdate = 0 WHERE id = ?", (staff_user["id"],))
    val = accounting.validate_backdate_entry(past_date, user_id=staff_user["id"], username=staff_user["username"])
    assert val["valid"] is False
    assert "Access Denied" in val["error"] or "Administrator" in val["error"]

    # Staff granted can_backdate = 1
    db.execute("UPDATE users SET can_backdate = 1 WHERE id = ?", (staff_user["id"],))
    val_allowed = accounting.validate_backdate_entry(past_date, user_id=staff_user["id"], username=staff_user["username"])
    assert val_allowed["valid"] is True
    assert val_allowed["is_backdated"] is True
    assert val_allowed["target_date"] == past_date

def test_closed_day_mandatory_reason_and_flag():
    """Entering into a closed day requires >= 10 char reason and sets modified_after_closing = 1."""
    closed_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    
    # Setup official day closing
    db.execute("DELETE FROM day_closings WHERE closing_date = ?", (closed_date,))
    db.execute("""
        INSERT INTO day_closings (closing_date, opening_cash, actual_cash, expected_cash, cash_difference, closed_by_id, closed_by_name, modified_after_closing, closed_at)
        VALUES (?, 10000, 10000, 10000, 0, 1, 'admin', 0, ?)
    """, (closed_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # Try without reason -> Fails
    val_no_reason = accounting.validate_backdate_entry(closed_date, user_id=1, username="admin", reason="")
    assert val_no_reason["valid"] is False
    assert "minimum 10 characters" in val_no_reason["error"]

    # Try with short reason (< 10 chars) -> Fails
    val_short = accounting.validate_backdate_entry(closed_date, user_id=1, username="admin", reason="short")
    assert val_short["valid"] is False
    assert "minimum 10 characters" in val_short["error"]

    # Valid reason >= 10 chars -> Succeeds and marks modified_after_closing
    val_ok = accounting.validate_backdate_entry(closed_date, user_id=1, username="admin", reason="Audited missing bill voucher #1042")
    assert val_ok["valid"] is True
    
    closing = db.query_one("SELECT * FROM day_closings WHERE closing_date = ?", (closed_date,))
    assert closing["modified_after_closing"] == 1

def test_backdated_pos_sale_dual_timestamps_and_aggregates():
    """Back-dated POS sale preserves business date in transaction_date and real wall-clock in recorded_at."""
    sale_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
    
    # 1. Create product and accessory variant
    pid = inventory.create_product("Anker", "PowerCore 20000", "Accessories", "ACCESSORY", 1, notes="Backdate test")
    vid = inventory.create_variant(pid, color="Black", retail_price=6500, wholesale_price=4500, stock_qty=10)
    db.execute("DELETE FROM sales_daily_by_variant WHERE variant_id = ?", (vid,))

    # 2. Process backdated sale
    cart = [{
        "item_type": "ACCESSORY",
        "variant_id": vid,
        "unit_id": 0,
        "item_name": "Anker PowerCore 20000 Black",
        "unit_price": 6500,
        "qty": 1
    }]

    res = pos.pos_checkout(
        cart,
        customer_name="Backdate Customer",
        customer_phone="03001234999",
        paid_amount=6500,
        payment_method="CASH",
        sale_date=sale_date,
        backdate_reason="Historical invoice entry",
        user_id=1,
        username="admin"
    )
    assert res["success"] is True
    sale_id = res["sale_id"]

    # 3. Verify dual timestamps on sales table
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    assert sale["transaction_date"] == sale_date
    assert sale["recorded_at"][:10] == datetime.now().strftime("%Y-%m-%d")
    assert sale["backdate_reason"] == "Historical invoice entry"

    # 4. Verify daily aggregates updated for sale_date
    agg = db.query_one("SELECT * FROM sales_daily_by_variant WHERE date = ? AND variant_id = ?", (sale_date, vid))
    assert agg is not None
    assert agg["units_sold"] == 1
    assert agg["gross_revenue"] == 6500.0

    # 5. Verify stock ledger dual timestamps
    slog = db.query_one("SELECT * FROM stock_ledger WHERE reference = ?", (sale["invoice_no"],))
    assert slog is not None
    assert slog["transaction_date"] == sale_date
    assert slog["recorded_at"][:10] == datetime.now().strftime("%Y-%m-%d")

def test_backdated_expense_and_purchasing():
    """Back-dated expense and purchase record dual timestamps on ledgers."""
    target_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    # Clean existing
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (target_date,))
    db.execute("DELETE FROM day_closings WHERE closing_date = ?", (target_date,))

    # Record backdated expense
    exp_res = accounting.record_expense(
        category="Tea / Food",
        amount=1200,
        description="Past tea bill",
        payment_method="Cash Drawer",
        expense_date=target_date,
        user_id=1,
        username="admin",
        backdate_reason="Voucher found in drawer"
    )
    assert exp_res["success"] is True
    exp = db.query_one("SELECT * FROM expenses WHERE id = ?", (exp_res["expense_id"],))
    assert exp["transaction_date"] == target_date
    assert exp["recorded_at"][:10] == datetime.now().strftime("%Y-%m-%d")
    assert exp["backdate_reason"] == "Voucher found in drawer"

    # Record backdated supplier payment
    sup_id = purchasing.create_supplier("Test Supplier Co", phone="03115555555", user_id=1, username="admin")
    pay_res = purchasing.record_supplier_payment(
        supplier_id=sup_id,
        amount=5000,
        payment_method="CASH",
        reference="RCP-55",
        notes="Old cash slip",
        payment_date=target_date,
        backdate_reason="Ledger reconciliation",
        user_id=1,
        username="admin"
    )
    assert pay_res["success"] is True
    sup_ledger = db.query_one("SELECT * FROM supplier_ledger WHERE id = ?", (pay_res["ledger_id"],))
    assert sup_ledger["transaction_date"] == target_date
    assert sup_ledger["recorded_at"][:10] == datetime.now().strftime("%Y-%m-%d")
    assert sup_ledger["backdate_reason"] == "Ledger reconciliation"

    # Record backdated udhaar payment
    cust_id = credit.create_customer("Udhaar Tester", "03221112233", user_id=1, username="admin")
    db.execute("UPDATE customers SET balance_udhaar = 10000 WHERE id = ?", (cust_id,))
    udh_res = credit.record_udhaar_payment(
        customer_id=cust_id,
        amount=3000,
        payment_method="CASH",
        notes="Paid earlier",
        payment_date=target_date,
        backdate_reason="Customer showed bank receipt",
        user_id=1,
        username="admin"
    )
    assert udh_res["success"] is True
    udh_ledger = db.query_one("SELECT * FROM udhaar_ledger WHERE id = ?", (udh_res["ledger_id"],))
    assert udh_ledger["transaction_date"] == target_date
    assert udh_ledger["recorded_at"][:10] == datetime.now().strftime("%Y-%m-%d")
    assert udh_ledger["backdate_reason"] == "Customer showed bank receipt"
