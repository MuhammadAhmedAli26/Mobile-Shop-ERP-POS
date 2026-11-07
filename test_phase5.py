# Phase 5 Verification Test Suite (Expenses, Earnings Center, Day Closing & Monthly Report)
import sys, os, time, random
from datetime import datetime
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, accounting, printing

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING PHASE 5 TEST SUITE (ACCOUNTING, EARNINGS & CLOSING)")
    print("=" * 60)

    # 1. Record Expenses
    e1 = accounting.record_expense("Shop Rent", 45000, "Monthly shop rent Hafeez Center", payment_method="CASH", user_id=1, username="admin")
    assert e1["success"] and e1["amount"] == 45000
    e2 = accounting.record_expense("Electricity / Generator / Fuel", 12500, "Generator diesel + WAPDA bill", payment_method="CASH", user_id=1, username="admin")
    assert e2["success"]
    e3 = accounting.record_expense("Tea / Food", 1800, "Daily refreshment for staff", payment_method="CASH", user_id=1, username="admin")
    assert e3["success"]
    print("✓ 1. Recorded 3 realistic business expenses (Rent, Generator, Refreshments).")

    # List expenses
    exps = accounting.list_expenses()
    assert len(exps) >= 3
    print(f"✓ 2. Verified expenses listing (Total records: {len(exps)}).")

    # 2. 5-Stream Earnings Center
    earnings = accounting.get_earnings_center()
    assert "stream1_phones" in earnings
    assert "stream2_accessories" in earnings
    assert "stream3_repairs" in earnings
    assert "stream4_software" in earnings
    assert "stream5_quick_services" in earnings
    
    print("✓ 3. 5-Stream Earnings Center calculated successfully:")
    print(f"   • Phone Retail Profit: Rs. {earnings['stream1_phones']['profit']:,.0f}")
    print(f"   • Accessories Profit:  Rs. {earnings['stream2_accessories']['profit']:,.0f}")
    print(f"   • Repair Workshop:     Rs. {earnings['stream3_repairs']['profit']:,.0f}")
    print(f"   • Software Lab:        Rs. {earnings['stream4_software']['profit']:,.0f}")
    print(f"   • Quick Services:      Rs. {earnings['stream5_quick_services']['profit']:,.0f}")
    print(f"   -------------------------------------------------")
    print(f"   • Total Gross Profit:  Rs. {earnings['total_gross_profit']:,.0f}")
    print(f"   • Total Expenses:      Rs. {earnings['total_expenses']:,.0f}")
    print(f"   • NET CLEAR PROFIT:    Rs. {earnings['net_profit']:,.0f}")

    # 3. Day Closing & Drawer Reconciliation
    today = datetime.now().strftime("%Y-%m-%d")
    close_data = accounting.get_day_closing_data(today)
    assert "expected_cash" in close_data
    print(f"✓ 4. Day Closing calculated: Expected Drawer Cash = Rs. {close_data['expected_cash']:,.0f}.")

    # Record actual cash counted (e.g. slight surplus of Rs. 200)
    op_cash = 5000
    exp_with_op = op_cash + close_data["total_cash_in"] - close_data["total_cash_out"]
    act_cash = exp_with_op + 200
    close_res = accounting.record_day_closing(actual_cash=act_cash, opening_cash=op_cash, notes="Cash verified and locked in safe", user_id=1, username="admin")
    assert close_res["success"]
    assert close_res["cash_difference"] == 200
    print(f"✓ 5. Official Day Closing saved! Difference: Rs. {close_res['cash_difference']:+,.0f} (Surplus).")

    # 4. Render Day Closing Z-Report
    z_html = printing.render_day_closing_z_report(today)
    assert "DAILY CLOSING Z-REPORT" in z_html
    assert "EXPECTED CASH" in z_html
    print("✓ 6. Thermal 80mm Z-Report rendered with drawer reconciliation.")

    # 5. Monthly Report
    now = datetime.now()
    m_rep = accounting.get_monthly_report(now.year, now.month)
    assert m_rep["month"] == f"{now.year:04d}-{now.month:02d}"
    print(f"✓ 7. Monthly Performance Report generated for {m_rep['month']}.")

    # 6. Render A4 Monthly Report
    m_html = printing.render_monthly_report(now.year, now.month)
    assert "MONTHLY BUSINESS & PROFIT STATEMENT" in m_html
    assert "NET CLEAR PROFIT" in m_html
    print("✓ 8. A4 Monthly Financial Statement rendered with 5 revenue streams.")

    print("\n" + "=" * 60)
    print("🏆 ALL PHASE 5 ACCOUNTING TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
