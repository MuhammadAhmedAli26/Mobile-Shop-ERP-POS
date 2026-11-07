# MOBILE & ACCESSORIES ERP — Fix 3 Automated Test Suite (Date-Wise Daily Sales Screen & Analytics)
import time, pytest
from datetime import datetime
import db, accounting, printing

@pytest.fixture(autouse=True)
def setup_test_db():
    db.init_db()

def test_date_wise_sales_summary_structure():
    """Verify get_date_wise_sales_summary returns exact metrics and totals."""
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = f"{today[:7]}-01"
    
    summary = accounting.get_date_wise_sales_summary(month_start, today, is_admin=True)
    assert "days" in summary
    assert "totals" in summary
    assert summary["is_admin"] is True

    tot = summary["totals"]
    assert "invoices_count" in tot
    assert "phones_sold" in tot
    assert "acc_sold" in tot
    assert "gross_sale" in tot
    assert "net_sale" in tot
    assert "cost" in tot
    assert "profit" in tot
    assert "expenses" in tot
    assert "net_of_day" in tot

def test_employee_privacy_serialization():
    """Verify employee role strips cost, profit, expenses, and net_of_day."""
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = f"{today[:7]}-01"

    emp_summary = accounting.get_date_wise_sales_summary(month_start, today, salesperson_id=2, is_admin=False)
    assert emp_summary["is_admin"] is False
    tot = emp_summary["totals"]
    
    # Financial margins must NOT be present for employee
    assert "cost" not in tot
    assert "profit" not in tot
    assert "expenses" not in tot
    assert "net_of_day" not in tot

    for d in emp_summary["days"]:
        assert "cost" not in d
        assert "profit" not in d
        assert "expenses" not in d
        assert "net_of_day" not in d

def test_daily_sales_printable_report():
    """Verify render_daily_sales_report generates valid A4 document with totals."""
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = f"{today[:7]}-01"

    html = printing.render_daily_sales_report(month_start, today, is_admin=True)
    assert "DATE-WISE DAILY SALES & REVENUE REPORT" in html
    assert "NET SALES VOLUME" in html
    assert "TOTALS" in html
    assert month_start in html

def test_daily_sales_speed_target():
    """Verify full month query runs in under 300 ms."""
    today = datetime.now().strftime("%Y-%m-%d")
    month_start = f"{today[:7]}-01"

    t0 = time.perf_counter()
    summary = accounting.get_date_wise_sales_summary(month_start, today, is_admin=True)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"Daily sales month query took {elapsed_ms:.2f} ms")
    assert elapsed_ms < 300.0, f"Query took {elapsed_ms:.2f} ms, exceeded 300 ms target"
