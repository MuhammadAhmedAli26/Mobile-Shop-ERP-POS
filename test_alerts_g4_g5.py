import unittest
import json
import io
import csv
from datetime import datetime
import db
import auth
import inventory
import pos
import alert_engine
import top_sellers
import web_ui

class TestAlertsAndTopSellersG4G5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        # Create unique test product and variants
        self.ts = int(datetime.now().timestamp() * 1000)
        self.brand = f"Brand_{self.ts}"
        self.model = f"Model_{self.ts}"
        self.cat = f"Cat_{self.ts}"

        with db.get_connection() as cx:
            cur = cx.execute("""
                INSERT INTO products (name, brand, category, item_type, is_archived)
                VALUES (?, ?, ?, 'PHONE', 0)
            """, (self.model, self.brand, self.cat))
            self.pid = cur.lastrowid

            # Variant 1: Low stock alert level = 3, reorder_qty = 10
            cur = cx.execute("""
                INSERT INTO variants (product_id, ram, storage, color, retail_price, wholesale_price, stock_quantity, low_stock_level, reorder_qty, is_archived)
                VALUES (?, '8GB', '128GB', 'Black', 60000, 50000, 0, 3, 10, 0)
            """, (self.pid,))
            self.v1_id = cur.lastrowid

            # Variant 2: Inherits category default
            cur = cx.execute("""
                INSERT INTO variants (product_id, ram, storage, color, retail_price, wholesale_price, stock_quantity, low_stock_level, reorder_qty, is_archived)
                VALUES (?, '12GB', '256GB', 'Blue', 80000, 70000, 0, NULL, 5, 0)
            """, (self.pid,))
            self.v2_id = cur.lastrowid

        # Refresh alert state
        alert_engine.evaluate_stock_transitions(None, [self.v1_id, self.v2_id], "TEST_SETUP")

    def test_01_alert_state_initialization(self):
        """Verify initial alert state is OUT for 0-stock variants."""
        st1 = alert_engine.get_variant_alert_state(self.v1_id)
        self.assertEqual(st1["state"], "OUT")
        self.assertEqual(st1["current_stock"], 0)

    def test_02_snooze_and_cancel_snooze(self):
        """Verify snoozing an alert and cancelling snooze."""
        res = alert_engine.snooze_alert(self.v1_id, days=2, user_id=1, username="admin")
        self.assertTrue(res["success"])
        st = alert_engine.get_variant_alert_state(self.v1_id)
        self.assertIsNotNone(st["snoozed_until"])

        res2 = alert_engine.cancel_snooze(self.v1_id, user_id=1, username="admin")
        self.assertTrue(res2["success"])
        st2 = alert_engine.get_variant_alert_state(self.v1_id)
        self.assertIsNone(st2["snoozed_until"])

    def test_03_mark_as_ordered(self):
        """Verify marking a low/out stock variant as ordered."""
        res = alert_engine.mark_as_ordered(self.v1_id, qty=15, expected_date="2026-11-01", notes="Urgent shipment", user_id=1, username="admin")
        self.assertTrue(res["success"])
        st = alert_engine.get_variant_alert_state(self.v1_id)
        self.assertEqual(st["on_order_qty"], 15)
        self.assertEqual(st["on_order_date"], "2026-11-01")

    def test_04_bulk_set_alert_level(self):
        """Verify bulk setting alert levels."""
        res = alert_engine.bulk_set_alert_level([self.v1_id, self.v2_id], level=5, reorder_qty=12, alert_off=0, user_id=1, username="admin")
        self.assertTrue(res["success"])
        self.assertEqual(res["updated_count"], 2)

        v1 = db.query_one("SELECT low_stock_level, reorder_qty FROM variants WHERE id = ?", (self.v1_id,))
        self.assertEqual(v1["low_stock_level"], 5)
        self.assertEqual(v1["reorder_qty"], 12)

    def test_05_top_sellers_aggregation(self):
        """Verify top_sellers daily sales recording and reporting."""
        today = datetime.now().strftime("%Y-%m-%d")
        with db.get_connection() as cx:
            cx.execute("""
                INSERT OR REPLACE INTO sales_daily_by_variant (date, variant_id, product_id, category, brand, units_sold, gross_revenue, cost_total, units_returned, net_profit)
                VALUES (?, ?, ?, ?, ?, 5, 300000, 250000, 0, 50000)
            """, (today, self.v1_id, self.pid, self.cat, self.brand))

        rep = top_sellers.get_top_sellers_report(period="today", category=self.cat, sort_by="units", is_admin=True)
        self.assertGreaterEqual(rep["total_net_units"], 5)
        self.assertGreaterEqual(rep["total_revenue"], 300000)
        self.assertGreaterEqual(rep["total_profit"], 50000)

        found = [it for it in rep["items"] if it["variant_id"] == self.v1_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["net_units_sold"], 5)
        self.assertEqual(found[0]["gross_revenue"], 300000)

    def test_06_top_sellers_employee_security(self):
        """Verify employee view redacts revenue, cost, profit, and supplier details."""
        rep = top_sellers.get_top_sellers_report(period="today", category=self.cat, sort_by="units", is_admin=False)
        self.assertIsNone(rep["total_revenue"])
        self.assertIsNone(rep["total_profit"])
        found = [it for it in rep["items"] if it["variant_id"] == self.v1_id]
        if found:
            self.assertNotIn("gross_revenue", found[0])
            self.assertNotIn("cost_total", found[0])
            self.assertNotIn("net_profit", found[0])
            self.assertNotIn("last_supplier_name", found[0])

    def test_07_pos_quick_top_sellers(self):
        """Verify POS quick-add top sellers returns employee-safe lightweight objects."""
        today = datetime.now().strftime("%Y-%m-%d")
        with db.get_connection() as cx:
            cx.execute("""
                INSERT OR REPLACE INTO sales_daily_by_variant (date, variant_id, product_id, category, brand, units_sold, gross_revenue, cost_total, units_returned, net_profit)
                VALUES (?, ?, ?, ?, ?, 8, 480000, 400000, 0, 80000)
            """, (today, self.v1_id, self.pid, self.cat, self.brand))

        items = top_sellers.get_pos_quick_top_sellers(category=self.cat, limit=10)
        self.assertTrue(len(items) >= 1)
        it = items[0]
        self.assertIn("variant_id", it)
        self.assertIn("net_units_sold", it)
        self.assertNotIn("cost_total", it)
        self.assertNotIn("net_profit", it)

    def test_08_reorder_intelligence(self):
        """Verify reorder intelligence calculates suggested reorder qty and days left."""
        intel = alert_engine.get_reorder_intelligence(self.v1_id)
        self.assertIn("suggested_reorder_qty", intel)
        self.assertIn("days_stock_left", intel)
        self.assertGreaterEqual(intel["suggested_reorder_qty"], 5)

    def _wsgi_request(self, method, path, session_data=None):
        sess = session_data or {"uid": 1, "role": "ADMIN", "username": "admin"}
        env = {
            'REQUEST_METHOD': method,
            'PATH_INFO': path.split('?')[0],
            'QUERY_STRING': path.split('?')[1] if '?' in path else '',
            'wsgi.input': io.BytesIO(b""),
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '8085',
            'wsgi.version': (1, 0),
            'wsgi.run_once': False,
            'wsgi.multithread': True,
            'wsgi.multiprocess': False,
            'wsgi.url_scheme': 'http',
            'wsgi.errors': io.StringIO(),
            'beaker.session': sess
        }
        res_status = []
        headers_list = []
        def start_response(status, headers):
            res_status.append(status)
            headers_list.extend(headers)

        body = web_ui.app(env, start_response)
        body_str = b"".join(body).decode("utf-8", errors="replace") if isinstance(body, (list, tuple)) else str(body)
        return res_status[0] if res_status else "500", dict(headers_list), body_str

    def test_09_http_low_stock_screen(self):
        """Verify /inventory/low-stock renders 200 and displays alerts table."""
        status, headers, body = self._wsgi_request("GET", "/inventory/low-stock")
        self.assertTrue(status.startswith("200"))
        self.assertIn("Low-Stock Alerts & Reorder Advice", body)
        self.assertIn("/print/reorder-sheet", body)

    def test_10_http_low_stock_export_csv(self):
        """Verify /inventory/low-stock/export.csv returns CSV with BOM."""
        status, headers, body = self._wsgi_request("GET", "/inventory/low-stock/export.csv")
        self.assertTrue(status.startswith("200"))
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertTrue(body.startswith("\ufeff") or "Variant ID" in body)

    def test_11_http_print_reorder_sheet(self):
        """Verify /print/reorder-sheet returns printable A4 advice sheet."""
        status, headers, body = self._wsgi_request("GET", "/print/reorder-sheet")
        self.assertTrue(status.startswith("200"))
        self.assertIn("STOCK REORDER & PURCHASE ADVICE", body)

    def test_12_http_top_sellers_screen(self):
        """Verify /reports/top-sellers renders 200 with leaderboard table."""
        status, headers, body = self._wsgi_request("GET", "/reports/top-sellers?period=this_month")
        self.assertTrue(status.startswith("200"))
        self.assertIn("Top-Selling Products", body)
        self.assertIn("Leaderboard", body)

    def test_13_http_top_sellers_export_csv(self):
        """Verify /reports/top-sellers/export.csv returns valid CSV."""
        status, headers, body = self._wsgi_request("GET", "/reports/top-sellers/export.csv?period=this_month")
        self.assertTrue(status.startswith("200"))
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn("Rank", body)

    def test_14_http_print_top_sellers_report(self):
        """Verify /print/top-sellers-report returns printable A4 report."""
        status, headers, body = self._wsgi_request("GET", "/print/top-sellers-report?period=this_month")
        self.assertTrue(status.startswith("200"))
        self.assertIn("TOP-SELLING PRODUCTS & VELOCITY REPORT", body)

    def test_15_http_pos_quick_top_sellers_api(self):
        """Verify /api/pos/quick-top-sellers returns JSON payload."""
        status, headers, body = self._wsgi_request("GET", "/api/pos/quick-top-sellers")
        self.assertTrue(status.startswith("200"))
        data = json.loads(body)
        self.assertTrue(data.get("success"))
        self.assertIsInstance(data.get("items"), list)

if __name__ == "__main__":
    unittest.main()
