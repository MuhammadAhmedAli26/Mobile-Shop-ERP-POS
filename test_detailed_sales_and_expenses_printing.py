# Test suite for detailed sales with items, itemized expenses, and comprehensive reporting
import os
import pytest
from datetime import datetime
import db, accounting, printing, lookups

@pytest.fixture(autouse=True)
def setup_test_db():
    db.init_db()

def get_test_variant_id():
    v = db.query_one("SELECT id FROM variants LIMIT 1")
    if v:
        return v["id"]
    # Create product and variant if empty
    db.execute("INSERT OR IGNORE INTO brands (name) VALUES ('TestBrand')")
    b_id = db.query_one("SELECT id FROM brands WHERE name='TestBrand'")["id"]
    db.execute("INSERT OR IGNORE INTO categories (name) VALUES ('Smartphones')")
    c_id = db.query_one("SELECT id FROM categories WHERE name='Smartphones'")["id"]
    db.execute("""
        INSERT INTO products (brand_id, category_id, name, item_type)
        VALUES (?, ?, 'TestPhone', 'PHONE')
    """, (b_id, c_id))
    p_id = db.query_one("SELECT last_insert_rowid() as id")["id"]
    db.execute("""
        INSERT INTO variants (product_id, color, storage, retail_price, cost_price, barcode)
        VALUES (?, 'Black', '128GB', 50000, 40000, 'TESTVAR001')
    """, (p_id,))
    return db.query_one("SELECT last_insert_rowid() as id")["id"]

def test_detailed_sales_and_expenses_data_engine():
    """Verify get_detailed_sales_report_data returns all items, IMEIs, expenses and totals."""
    test_date = "2026-10-14"
    v_id = get_test_variant_id()
    
    # 1. Clean test records
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-001')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-001'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))
    db.execute("DELETE FROM day_closings WHERE closing_date = ?", (test_date,))
    db.execute("DELETE FROM udhaar_ledger WHERE transaction_date = ?", (test_date,))

    # 2. Insert test sale with items (Phone + Accessory)
    db.execute("""
        INSERT INTO sales (invoice_no, customer_name, customer_phone, grand_total, paid_amount, balance_due, payment_method, status, transaction_date, created_at)
        VALUES ('INV-TEST-001', 'Babar Azam', '03001234567', 150000, 100000, 50000, 'CASH', 'COMPLETED', ?, ? || ' 11:30:00')
    """, (test_date, test_date))
    sale_row = db.query_one("SELECT id FROM sales WHERE invoice_no = 'INV-TEST-001'")
    sale_id = sale_row["id"]

    db.execute("""
        INSERT INTO sale_items (sale_id, variant_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit)
        VALUES (?, ?, 'PHONE', 'Samsung Galaxy S24 Ultra', '12GB/512GB Titanium Black', '358901234567890', '358901234567891', 1, 145000, 130000, 0, 145000, 15000)
    """, (sale_id, v_id))

    db.execute("""
        INSERT INTO sale_items (sale_id, variant_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit)
        VALUES (?, ?, 'ACC', 'Samsung 45W Fast Charger', 'Type-C Cable Included', NULL, NULL, 1, 5000, 3500, 0, 5000, 1500)
    """, (sale_id, v_id))

    # 3. Insert test expenses (Cash drawer vs Bank)
    e1 = accounting.record_expense(
        category="Bills / Utilities",
        amount=6500,
        description="Shop electricity bill via Meezan",
        payment_method="Meezan Bank",
        expense_date=test_date,
        user_id=1,
        username="admin",
        backdate_reason="Audit test"
    )
    assert e1["success"] is True

    e2 = accounting.record_expense(
        category="Tea / Refreshment",
        amount=850,
        description="Afternoon tea & biscuits for customers",
        payment_method="Cash Drawer",
        expense_date=test_date,
        user_id=1,
        username="admin",
        backdate_reason="Audit test"
    )
    assert e2["success"] is True

    # 4. Insert test udhaar payment recovery
    db.execute("""
        INSERT INTO udhaar_ledger (customer_id, transaction_type, amount, payment_method, notes, transaction_date, timestamp)
        VALUES (1, 'PAYMENT', 15000, 'Cash Drawer', 'Collected previous balance', ?, ? || ' 15:00:00')
    """, (test_date, test_date))

    # 5. Fetch detailed data
    data = accounting.get_detailed_sales_report_data(test_date, test_date, is_admin=True)

    # Verify Sales
    assert len(data["sales"]) >= 1
    s0 = next(s for s in data["sales"] if s["invoice_no"] == "INV-TEST-001")
    assert s0["customer_name"] == "Babar Azam"
    assert len(s0["items"]) == 2
    
    phone_item = next(it for it in s0["items"] if it["item_type"] == "PHONE")
    assert phone_item["item_name"] == "Samsung Galaxy S24 Ultra"
    assert phone_item["imei1"] == "358901234567890"
    assert phone_item["line_total"] == 145000

    acc_item = next(it for it in s0["items"] if it["item_type"] == "ACC")
    assert acc_item["item_name"] == "Samsung 45W Fast Charger"
    assert acc_item["line_total"] == 5000

    # Verify Expenses
    assert len(data["expenses"]) >= 2
    tea_exp = next(e for e in data["expenses"] if "tea & biscuits" in e["description"].lower())
    assert tea_exp["is_cash"] is True
    assert tea_exp["amount"] == 850

    bill_exp = next(e for e in data["expenses"] if "electricity bill" in e["description"].lower())
    assert bill_exp["is_cash"] is False
    assert bill_exp["amount"] == 6500

    # Verify Totals
    tot = data["totals"]
    assert tot["invoices_count"] >= 1
    assert tot["phones_sold"] >= 1
    assert tot["acc_sold"] >= 1
    assert tot["cash_sales"] >= 100000
    assert tot["balance_due"] >= 50000
    assert tot["cash_expenses_total"] >= 850
    assert tot["non_cash_expenses_total"] >= 6500

    # Clean up test rows
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-001')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-001'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))
    db.execute("DELETE FROM udhaar_ledger WHERE transaction_date = ?", (test_date,))

def test_render_daily_sales_detailed_html():
    """Verify render_daily_sales_report generates full A4 report with itemized products and expenses."""
    test_date = "2026-10-15"
    v_id = get_test_variant_id()

    # Clean previous
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-002')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-002'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))

    # Insert test data
    db.execute("""
        INSERT INTO sales (invoice_no, customer_name, customer_phone, grand_total, paid_amount, balance_due, payment_method, status, transaction_date, created_at)
        VALUES ('INV-TEST-002', 'Shaheen Afridi', '03119876543', 95000, 95000, 0, 'CASH', 'COMPLETED', ?, ? || ' 12:00:00')
    """, (test_date, test_date))
    sale_row = db.query_one("SELECT id FROM sales WHERE invoice_no = 'INV-TEST-002'")
    s_id = sale_row["id"]

    db.execute("""
        INSERT INTO sale_items (sale_id, variant_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit)
        VALUES (?, ?, 'PHONE', 'Redmi Note 13 Pro', '8GB/256GB Midnight Black', '864201234567890', '864201234567891', 1, 95000, 85000, 0, 95000, 10000)
    """, (s_id, v_id))

    e = accounting.record_expense(
        category="Tea / Refreshment",
        amount=500,
        description="Daily staff refreshment samosas",
        payment_method="Cash Drawer",
        expense_date=test_date,
        user_id=1,
        username="admin",
        backdate_reason="Audit test"
    )
    assert e["success"] is True

    html = printing.render_daily_sales_report(test_date, test_date, is_admin=True)

    # Check key report components
    assert "DATE-WISE DAILY SALES & REVENUE REPORT" in html
    assert "NET SALES VOLUME" in html
    assert "ITEMIZED INVOICES & PRODUCTS SOLD" in html
    assert "Redmi Note 13 Pro" in html
    assert "864201234567890" in html
    assert "Shaheen Afridi" in html
    assert "ITEMIZED SHOP EXPENSES" in html
    assert "Daily staff refreshment samosas" in html
    assert "Rs. 500" in html

    # Clean up
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-002')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-002'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))

def test_render_day_closing_z_report_includes_details():
    """Verify Z-report thermal print includes itemized expenses and sold products."""
    test_date = "2026-10-16"
    v_id = get_test_variant_id()

    # Clean previous
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-003')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-003'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))

    db.execute("""
        INSERT INTO sales (invoice_no, customer_name, customer_phone, grand_total, paid_amount, balance_due, payment_method, status, transaction_date, created_at)
        VALUES ('INV-TEST-003', 'Rizwan Ahmed', '03221234567', 45000, 45000, 0, 'CASH', 'COMPLETED', ?, ? || ' 14:00:00')
    """, (test_date, test_date))
    sale_row = db.query_one("SELECT id FROM sales WHERE invoice_no = 'INV-TEST-003'")
    s_id = sale_row["id"]

    db.execute("""
        INSERT INTO sale_items (sale_id, variant_id, item_type, item_name, variant_details, imei1, imei2, qty, unit_price, cost_price, discount, line_total, profit)
        VALUES (?, ?, 'PHONE', 'Infinix Note 40', '8GB/256GB Gold', '352401234567890', NULL, 1, 45000, 40000, 0, 45000, 5000)
    """, (s_id, v_id))

    e = accounting.record_expense(
        category="Shop Stationery",
        amount=350,
        description="Thermal paper rolls for receipt printer",
        payment_method="Cash Drawer",
        expense_date=test_date,
        user_id=1,
        username="admin",
        backdate_reason="Audit test"
    )
    assert e["success"] is True

    z_html = printing.render_day_closing_z_report(test_date)

    assert "DAILY CLOSING Z-REPORT" in z_html
    assert "PRODUCTS SOLD TODAY:" in z_html
    assert "Infinix Note 40" in z_html
    assert "ITEMIZED EXPENSES (DETAILS):" in z_html
    assert "Thermal paper rolls for receipt printer" in z_html
    assert "Rs. 350" in z_html

    # Clean up
    db.execute("DELETE FROM sale_items WHERE sale_id IN (SELECT id FROM sales WHERE invoice_no = 'INV-TEST-003')")
    db.execute("DELETE FROM sales WHERE invoice_no = 'INV-TEST-003'")
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))
