# MOBILE & ACCESSORIES ERP — Fix 2 Automated Test Suite (Day Closing Expenses & Canonical Accounts)
import os, pytest
from datetime import datetime
import db, lookups, accounting, printing

@pytest.fixture(autouse=True)
def setup_test_db():
    db.init_db()
    lookups.migrate_normalize_payment_accounts()

def test_canonical_account_rule():
    """Verify ONE canonical rule correctly maps all payment accounts and variants."""
    # Cash accounts
    for acc in ["Cash Drawer", "CASH", "cash", " Cash ", "counter", "Petty Cash Drawer"]:
        assert lookups.is_cash_account(acc) is True, f"Failed for {acc}"
        assert lookups.get_account_type(acc) == "CASH"

    # Mobile wallets
    for acc in ["EasyPaisa Merchant", "JazzCash Merchant", "easypaisa", "jazzcash", "SadaPay", "NayaPay"]:
        assert lookups.is_cash_account(acc) is False, f"Failed for {acc}"
        assert lookups.get_account_type(acc) == "WALLET"

    # Banks and online
    for acc in ["Meezan Bank", "Raast / Bank Alfalah", "HBL", "Allied Bank", "MCB", "Bank Transfer", "Online", "Card"]:
        assert lookups.is_cash_account(acc) is False, f"Failed for {acc}"
        assert lookups.get_account_type(acc) == "BANK"

def test_day_closing_expenses_calculation():
    """Verify day closing calculates cash vs non-cash expenses and updates drawer cash."""
    test_date = "2026-10-10"
    
    # Clean any preexisting records for test_date
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))
    db.execute("DELETE FROM day_closings WHERE closing_date = ?", (test_date,))

    # Baseline with no expenses
    base_data = accounting.get_day_closing_data(test_date)
    base_expected = base_data["expected_cash"]
    assert base_data["cash_expenses_total"] == 0.0
    assert base_data["non_cash_expenses_total"] == 0.0

    # 1. Add cash drawer expense
    e1 = accounting.record_expense(
        category="Tea / Food",
        amount=2500,
        description="Chai and bakery items",
        payment_method="Cash Drawer",
        expense_date=test_date,
        user_id=1,
        username="admin"
    )
    assert e1["success"] is True

    d1 = accounting.get_day_closing_data(test_date)
    assert d1["cash_expenses_total"] == 2500.0
    assert d1["non_cash_expenses_total"] == 0.0
    assert d1["total_expenses"] == 2500.0
    assert d1["expected_cash"] == base_expected - 2500.0

    # 2. Add bank / wallet expense
    e2 = accounting.record_expense(
        category="Electricity / Generator / Fuel",
        amount=15000,
        description="IESCO electricity bill online",
        payment_method="Meezan Bank",
        expense_date=test_date,
        user_id=1,
        username="admin"
    )
    assert e2["success"] is True

    e3 = accounting.record_expense(
        category="Repair Tools & Supplies",
        amount=3000,
        description="Soldering wire via EasyPaisa",
        payment_method="EasyPaisa Merchant",
        expense_date=test_date,
        user_id=1,
        username="admin"
    )
    assert e3["success"] is True

    # Immediate calculation check
    d2 = accounting.get_day_closing_data(test_date)
    assert d2["cash_expenses_total"] == 2500.0
    assert d2["non_cash_expenses_total"] == 18000.0
    assert d2["total_expenses"] == 20500.0
    # Expected drawer cash ONLY reduced by drawer cash expense (2500)
    assert d2["expected_cash"] == base_expected - 2500.0

    # Category breakdown check
    categories = {c["category"]: c["total"] for c in d2["expenses_by_category"]}
    assert categories["Tea / Food"] == 2500.0
    assert categories["Electricity / Generator / Fuel"] == 15000.0
    assert categories["Repair Tools & Supplies"] == 3000.0

def test_day_closing_record_and_z_report():
    """Verify recording day closing and rendering thermal Z-Report."""
    test_date = "2026-10-10"
    data = accounting.get_day_closing_data(test_date)
    
    # Save official day closing
    rec = accounting.record_day_closing(
        actual_cash=data["expected_cash"] + 500,  # Surplus 500
        opening_cash=data["opening_cash"],
        closing_date=test_date,
        notes="Test closing with surplus",
        user_id=1,
        username="admin"
    )
    assert rec["success"] is True
    assert rec["cash_difference"] == 500.0

    # Render Z-Report
    html = printing.render_day_closing_z_report(test_date)
    assert test_date in html
    assert "DAILY CLOSING Z-REPORT" in html
    assert "Tea / Food" in html
    assert "Electricity / Generator / Fuel" in html
    assert f"Rs. {data['cash_expenses_total']:,.0f}" in html
    assert f"Rs. {data['non_cash_expenses_total']:,.0f}" in html
    assert "SURPLUS" in html

    # Clean up test rows
    db.execute("DELETE FROM expenses WHERE expense_date = ?", (test_date,))
    db.execute("DELETE FROM day_closings WHERE closing_date = ?", (test_date,))
