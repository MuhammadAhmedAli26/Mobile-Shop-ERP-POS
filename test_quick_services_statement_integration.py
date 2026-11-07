# test_quick_services_statement_integration.py
# Verification suite for Quick Services (EasyPaisa / JazzCash / Load / Bills)
# and Net Profit calculation in daily/monthly statements and reports.
import pytest
from datetime import datetime
import db
import services
import accounting
import printing

def test_quick_services_recording_send_and_receive():
    """Verify recording of both SEND (Cash-in) and RECEIVE (Cash-out) transactions."""
    test_phone = "03009988776"
    test_note_send = "TEST_EP_SEND_001"
    test_note_recv = "TEST_EP_RECV_001"

    # Clean existing test records if any
    db.execute("DELETE FROM quick_services WHERE notes IN (?, ?)", (test_note_send, test_note_recv))

    # 1. Record SEND transaction (Customer gave cash, shop sent Rs. 5,000, profit Rs. 50)
    res_send = services.record_quick_service(
        service_type="EASYPAISA",
        amount=5000,
        fee_commission=50,
        customer_phone=test_phone,
        network="Telenor",
        notes=test_note_send,
        user_id=1,
        username="admin",
        action_type="SEND"
    )
    assert res_send["success"] is True
    assert res_send["action_type"] == "SEND"
    assert res_send["commission"] == 50

    # 2. Record RECEIVE transaction (Customer sent Rs. 3,000, shop gave cash, profit Rs. 30)
    res_recv = services.record_quick_service(
        service_type="JAZZCASH",
        amount=3000,
        fee_commission=30,
        customer_phone=test_phone,
        network="Jazz",
        notes=test_note_recv,
        user_id=1,
        username="admin",
        action_type="RECEIVE"
    )
    assert res_recv["success"] is True
    assert res_recv["action_type"] == "RECEIVE"
    assert res_recv["commission"] == 30

    # Verify rows in DB
    row_send = db.query_one("SELECT * FROM quick_services WHERE id = ?", (res_send["quick_service_id"],))
    assert row_send["amount"] == 5000
    assert row_send["profit"] == 50

    row_recv = db.query_one("SELECT * FROM quick_services WHERE id = ?", (res_recv["quick_service_id"],))
    assert row_recv["amount"] == 3000
    assert row_recv["profit"] == 30

    # Clean up test records
    db.execute("DELETE FROM quick_services WHERE notes IN (?, ?)", (test_note_send, test_note_recv))

def test_quick_services_in_detailed_sales_report():
    """Verify get_detailed_sales_report_data includes quick services, commissions, and net profit."""
    today = datetime.now().strftime("%Y-%m-%d")
    test_note = "TEST_DETAILED_QS_999"

    # Insert test quick service
    res = services.record_quick_service(
        service_type="EASYPAISA",
        amount=8000,
        fee_commission=80,
        customer_phone="03123456789",
        network="Telenor",
        notes=test_note,
        user_id=1,
        username="admin",
        action_type="SEND"
    )

    det = accounting.get_detailed_sales_report_data(today, today, is_admin=True)

    assert "quick_services" in det
    assert "qs_totals" in det
    assert det["qs_totals"]["profit"] >= 80

    # Check that profit in totals includes Quick Services commission
    tot = det["totals"]
    assert "qs_profit" in tot
    assert tot["qs_profit"] >= 80
    assert "total_gross_income" in tot
    assert tot["total_gross_income"] >= tot["sales_profit"] + tot["qs_profit"]

    # Verify net_of_period math
    expected_net = tot["total_gross_income"] - tot["expenses_total"]
    assert tot["net_of_period"] == expected_net

    # Clean up
    db.execute("DELETE FROM quick_services WHERE notes = ?", (test_note,))

def test_quick_services_in_date_wise_summary():
    """Verify get_date_wise_sales_summary adds quick services into daily gross and net profit."""
    today = datetime.now().strftime("%Y-%m-%d")
    test_note = "TEST_DATEWISE_QS_888"

    res = services.record_quick_service(
        service_type="JAZZCASH",
        amount=10000,
        fee_commission=100,
        customer_phone="03011223344",
        network="Jazz",
        notes=test_note,
        user_id=1,
        username="admin",
        action_type="RECEIVE"
    )

    summary = accounting.get_date_wise_sales_summary(today, today, is_admin=True)
    tot = summary["totals"]

    assert "qs_profit" in tot
    assert tot["qs_profit"] >= 100
    assert tot["profit"] >= tot["sales_profit"] + tot["qs_profit"]

    # Clean up
    db.execute("DELETE FROM quick_services WHERE notes = ?", (test_note,))

def test_daily_sales_print_rendering():
    """Verify render_daily_sales_report contains Section 5 for Quick Services and 5 KPI cards."""
    today = datetime.now().strftime("%Y-%m-%d")
    html = printing.render_daily_sales_report(today, today, is_admin=True)

    assert "QUICK SERVICES &amp; DIGITAL WALLETS" in html or "QUICK SERVICES & DIGITAL WALLETS" in html
    assert "GROSS EARNINGS" in html
    assert "NET PROFIT" in html or "OPERATING DEFICIT" in html

def test_monthly_closing_print_rendering():
    """Verify render_monthly_closing_report includes Monthly Quick Services Summary."""
    cur_month = datetime.now().strftime("%Y-%m")
    html = printing.render_monthly_closing_report(cur_month, is_admin=True)

    assert "MONTHLY QUICK SERVICES" in html
    assert "Total Commission / Profit" in html
