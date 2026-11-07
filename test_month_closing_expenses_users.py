"""
Integration Tests for Monthly Day Closing, Monthly Expenses, CSV Exports, Print Reports,
Safe Employee Deletion, Granular Permissions, and Cross-Month Filter Robustness.
Uses pure Python standard WSGI caller (Zero external dependencies).
"""
import pytest
import sqlite3
import os
import json
import shutil
import tempfile
from io import BytesIO

from datetime import datetime
import config
import db
import auth
import accounting
import printing
import web_ui

def wsgi_request(app, method, path, body=None, content_type=None, session=None):
    body_bytes = b""
    if body is not None:
        if isinstance(body, str):
            body_bytes = body.encode("utf-8")
        elif isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            content_type = "application/json"
        else:
            body_bytes = bytes(body)

    class UniversalIO:
        def __init__(self):
            self.buf = []
        def write(self, s):
            if isinstance(s, bytes):
                s = s.decode("utf-8", errors="replace")
            self.buf.append(s)
        def flush(self):
            pass
        def getvalue(self):
            return "".join(self.buf)

    env = {
        "REQUEST_METHOD": method.upper(),
        "PATH_INFO": path.split("?")[0],
        "QUERY_STRING": path.split("?")[1] if "?" in path else "",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "8085",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(body_bytes),
        "wsgi.errors": UniversalIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    if content_type:
        env["CONTENT_TYPE"] = content_type
    if body_bytes:
        env["CONTENT_LENGTH"] = str(len(body_bytes))
    if session is not None:
        env["beaker.session"] = session
    else:
        env["beaker.session"] = {"uid": 1, "username": "admin", "role": "ADMIN"}

    status_headers = {}
    def start_response(status, headers):
        status_headers["status"] = status
        status_headers["headers"] = dict(headers)

    res_chunks = app(env, start_response)
    resp_body = b"".join(res_chunks).decode("utf-8", errors="replace")
    return status_headers.get("status", "500"), status_headers.get("headers", {}), resp_body

@pytest.fixture(scope="module")
def app_client():
    temp_dir = tempfile.mkdtemp(prefix="test_monthly_")
    temp_db = os.path.join(temp_dir, "test_monthly.db")
    
    orig_db = config.DATABASE_NAME
    config.DATABASE_NAME = temp_db
    if hasattr(db, "DATABASE_NAME"):
        db.DATABASE_NAME = temp_db
    os.environ["ERP_DB_PATH"] = temp_db
    
    db.init_db()
    
    admin_session = {"uid": 1, "username": "admin", "role": "ADMIN"}
    
    yield {"app": web_ui.app, "session": admin_session, "db": temp_db}
    
    config.DATABASE_NAME = orig_db
    if hasattr(db, "DATABASE_NAME"):
        db.DATABASE_NAME = orig_db
    shutil.rmtree(temp_dir, ignore_errors=True)
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_sales_cross_month_and_empty_salesperson(app_client):
    app = app_client["app"]
    session = app_client["session"]
    
    # Test 1: Cross-month date filter with empty salesperson_id (previously threw ValueError/500)
    status, headers, body = wsgi_request(app, "GET", "/sales?start_date=2026-09-01&end_date=2026-10-17&salesperson_id=&view=month", session=session)
    assert status.startswith("200")
    assert ("Daily Sales" in body or "Sales History" in body)
    
    # Test 2: Sales export CSV with empty salesperson_id
    status, headers, body = wsgi_request(app, "GET", "/sales/export.csv?start_date=2026-09-01&end_date=2026-10-17&salesperson_id=", session=session)
    assert status.startswith("200")
    assert "text/csv" in headers.get("Content-Type", "")
    assert "Date,Invoices,Phones Sold" in body
    
    # Test 3: Print daily sales with empty salesperson_id
    status, headers, body = wsgi_request(app, "GET", "/print/daily-sales?start_date=2026-09-01&end_date=2026-10-17&salesperson_id=", session=session)
    assert status.startswith("200")
    assert ("DAILY SALES" in body or "Daily Sales" in body)

def test_expenses_monthly_and_export_and_print(app_client):
    app = app_client["app"]
    session = app_client["session"]
    
    accounting.record_expense("Electricity", 3500, description="Shop meter bill", payment_method="CASH", expense_date="2026-10-05", user_id=1, username="admin")
    accounting.record_expense("Tea & Refreshment", 450, description="Chai for counter", payment_method="Cash Drawer", expense_date="2026-10-10", user_id=1, username="admin")
    accounting.record_expense("Internet Bill", 2000, description="Fiber net", payment_method="Online", expense_date="2026-10-12", user_id=1, username="admin")
    
    # Test 1: Expenses main screen with month filter
    status, headers, body = wsgi_request(app, "GET", "/expenses?month=2026-10", session=session)
    assert status.startswith("200")
    assert "Shop Expenses Management" in body
    assert "Rs. 5,950" in body
    assert "Shop meter bill" in body
    
    # Test 2: Expenses CSV export
    status, headers, body = wsgi_request(app, "GET", "/expenses/export.csv?month=2026-10", session=session)
    assert status.startswith("200")
    assert "text/csv" in headers.get("Content-Type", "")
    assert "Expense ID,Date,Category,Description,Amount (PKR)" in body
    assert "Electricity" in body
    assert "TOTAL EXPENSES,5950.00" in body
    
    # Test 3: Expenses print monthly report
    status, headers, body = wsgi_request(app, "GET", "/print/expenses?month=2026-10", session=session)
    assert status.startswith("200")
    assert ("EXPENSES REPORT" in body or "Expenses-Report" in body)
    assert "Rs. 5,950" in body

def test_day_closing_monthly_and_export_and_print(app_client):
    app = app_client["app"]
    session = app_client["session"]
    
    accounting.record_day_closing(actual_cash=15000, opening_cash=2000, closing_date="2026-10-10", user_id=1, username="admin")
    
    # Test 1: Day closing month view
    status, headers, body = wsgi_request(app, "GET", "/day-closing?view=month&month=2026-10", session=session)
    assert status.startswith("200")
    assert "Monthly Closing History" in body
    assert "2026-10-10" in body
    assert "CLOSED" in body
    
    # Test 2: Day closing CSV export
    status, headers, body = wsgi_request(app, "GET", "/day-closing/export.csv?month=2026-10", session=session)
    assert status.startswith("200")
    assert "text/csv" in headers.get("Content-Type", "")
    assert "Date,Status,Opening Cash,Cash Sales" in body
    assert "2026-10-10,CLOSED" in body
    
    # Test 3: Day closing monthly print report
    status, headers, body = wsgi_request(app, "GET", "/print/day-closing-monthly?month=2026-10", session=session)
    assert status.startswith("200")
    assert ("MONTHLY CLOSING REPORT" in body or "Monthly-Closing-Report" in body)
    assert "2026-10-10" in body

def test_employee_management_delete_and_permissions(app_client):
    app = app_client["app"]
    session = app_client["session"]
    
    # Create employee account
    res_create = auth.create_employee("cashier1", "secret123", full_name="Ali Cashier", current_admin_id=1, current_admin_name="admin")
    assert res_create["success"] is True
    emp_id = res_create["user_id"]
    
    # Verify settings/users renders permissions button and delete button
    status, headers, body = wsgi_request(app, "GET", "/settings/users", session=session)
    assert status.startswith("200")
    assert "Ali Cashier" in body
    assert f"deleteEmployee({emp_id}, 'cashier1')" in body
    assert "openPermsModal" in body
    
    # Update employee permissions
    new_perms = {
        "pos": True,
        "inventory_view": True,
        "sales_view": False,
        "software_jobs": True,
        "repair_jobs": False,
        "can_backdate": True
    }
    status, headers, body = wsgi_request(app, "POST", "/api/users/update-permissions", body={"user_id": emp_id, "permissions": new_perms}, session=session)
    assert status.startswith("200")
    res_perm = json.loads(body)
    assert res_perm["success"] is True
    
    # Verify updated permissions in DB
    emp_row = db.query_one("SELECT permissions, can_backdate FROM users WHERE id = ?", (emp_id,))
    saved_perms = json.loads(emp_row["permissions"])
    assert saved_perms["pos"] is True
    assert saved_perms["sales_view"] is False
    assert emp_row["can_backdate"] == 1
    
    # Delete employee without history -> hard delete
    status, headers, body = wsgi_request(app, "POST", "/api/users/delete", body={"user_id": emp_id}, session=session)
    assert status.startswith("200")
    res_del = json.loads(body)
    assert res_del["success"] is True
    deleted_row = db.query_one("SELECT * FROM users WHERE id = ?", (emp_id,))
    assert deleted_row is None
    
    # Create employee with transaction history
    res_emp2 = auth.create_employee("cashier2", "secret123", full_name="Usman Staff", current_admin_id=1, current_admin_name="admin")
    emp2_id = res_emp2["user_id"]
    
    # Record an expense logged by cashier2 for today
    today_dt = datetime.now().strftime("%Y-%m-%d")
    accounting.record_expense("Tea", 100, description="Staff tea", payment_method="CASH", expense_date=today_dt, user_id=emp2_id, username="cashier2")
    
    # Delete employee WITH history -> soft delete / archive
    status, headers, body = wsgi_request(app, "POST", "/api/users/delete", body={"user_id": emp2_id}, session=session)
    assert status.startswith("200")
    res_del2 = json.loads(body)
    assert res_del2["success"] is True
    assert "deactivated and archived" in res_del2["message"]
    
    archived_row = db.query_one("SELECT is_active, full_name FROM users WHERE id = ?", (emp2_id,))
    assert archived_row["is_active"] == 0
    assert "[Deleted]" in archived_row["full_name"]
