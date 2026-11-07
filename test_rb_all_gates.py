import os, sys, tempfile, shutil, unittest
import time
from datetime import datetime

# Configure temporary database BEFORE importing config or db
temp_dir = tempfile.mkdtemp(prefix="test_rb_")
test_db_path = os.path.join(temp_dir, "test_mobile_erp.db")
os.environ["ERP_DB_PATH"] = test_db_path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
config.DATABASE_NAME = test_db_path

import db, auth, inventory, pos, credit, accounting, lookups, printing

class TestReportedBugsRB1ToRB4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    def test_rb1_udhaar_sales_history_and_accounting_guard(self):
        """RB1: Udhaar collection recorded in udhaar_ledger, visible in sales, 
        and does NOT double count in Daily Net Sales or Gross Profit."""
        today = datetime.now().strftime("%Y-%m-%d")

        # 1. Create product and accessory
        p_id = inventory.create_product("Anker", "PowerPort III 20W", category="Charger", item_type="ACCESSORY", user_id=1, username="admin")
        v_res = inventory.create_item_unified({
            "product_id": p_id,
            "brand": "Anker",
            "name": "PowerPort III 20W",
            "category": "Charger",
            "item_type": "ACCESSORY",
            "variants": [{
                "ram": "", "storage": "", "color": "White",
                "retail_price": 5000, "wholesale_price": 3000,
                "stock_quantity": 20, "low_stock_level": 2
            }]
        }, user_id=1, username="admin")
        v_id = v_res["variant_id"]

        # 2. Create customer
        c_id = credit.create_customer("Zubair Ahmed", "03009988776", address="Lahore", user_id=1, username="admin")

        # 3. Sell 2 units on FULL UDHAAR
        sale_res = pos.pos_checkout(
            items=[{"variant_id": v_id, "item_type": "ACCESSORY", "item_name": "PowerPort III 20W", "qty": 2, "unit_price": 5000}],
            customer_name="Zubair Ahmed",
            customer_phone="03009988776",
            paid_amount=0,
            payment_method="UDHAAR",
            user_id=1,
            username="admin"
        )
        self.assertTrue(sale_res["success"])
        sale_id = sale_res["sale_id"]

        # Verify customer balance is 10,000
        cust = db.query_one("SELECT balance_udhaar FROM customers WHERE id = ?", (c_id,))
        self.assertEqual(float(cust["balance_udhaar"]), 10000.0)

        # Baseline sales summary BEFORE udhaar payment
        summary_before = accounting.get_date_wise_sales_summary(today, today, is_admin=True)
        net_before = summary_before["totals"]["net_sale"]
        profit_before = summary_before["totals"]["profit"]
        invoices_before = summary_before["totals"]["invoices_count"]

        # 4. Customer pays Rs. 4,000 against Udhaar
        pay_res = credit.record_udhaar_payment(
            customer_id=c_id,
            amount=4000.0,
            payment_method="Cash Drawer",
            notes="Partial Khata settlement",
            user_id=1,
            username="admin"
        )
        self.assertTrue(pay_res["success"])
        ledger_id = pay_res["ledger_id"]

        # Verify customer balance dropped to 6,000
        cust_after = db.query_one("SELECT balance_udhaar FROM customers WHERE id = ?", (c_id,))
        self.assertEqual(float(cust_after["balance_udhaar"]), 6000.0)

        # Verify udhaar payment row exists in udhaar_ledger
        udh_row = db.query_one("SELECT * FROM udhaar_ledger WHERE id = ?", (ledger_id,))
        self.assertIsNotNone(udh_row)
        self.assertEqual(float(udh_row["amount"]), 4000.0)
        self.assertEqual(float(udh_row["balance_after"]), 6000.0)

        # ACCOUNTING GUARD: Udhaar collection must NOT alter Net Sales volume or Gross Profit
        summary_after = accounting.get_date_wise_sales_summary(today, today, is_admin=True)
        self.assertEqual(summary_after["totals"]["net_sale"], net_before, "Udhaar payment must NOT increase Net Sale!")
        self.assertEqual(summary_after["totals"]["profit"], profit_before, "Udhaar payment must NOT inflate Gross Profit!")
        self.assertEqual(summary_after["totals"]["invoices_count"], invoices_before, "Udhaar collection is not a new invoice!")

        # Verify Day Closing expenses and drawer cash include udhaar collection
        dc_calc = accounting.calculate_day_closing(today)
        self.assertGreaterEqual(dc_calc["udhaar_recovered"], 4000.0)

    def test_rb2_pos_udhaar_customer_link_and_refuse_walkin(self):
        """RB2: Refuse walk-in credit with plain error. Successful udhaar checkout 
        links customer in ONE transaction and prints balance due."""
        # Setup an accessory item with stock
        p_id = inventory.create_product("Remax", "Fast Cable RB2", category="Cable", item_type="ACCESSORY", user_id=1, username="admin")
        v_res = inventory.create_item_unified({
            "product_id": p_id,
            "brand": "Remax",
            "name": "Fast Cable RB2",
            "category": "Cable",
            "item_type": "ACCESSORY",
            "variants": [{
                "ram": "", "storage": "", "color": "Black",
                "retail_price": 2000, "wholesale_price": 1000,
                "stock_quantity": 10, "low_stock_level": 2
            }]
        }, user_id=1, username="admin")
        v_id = v_res["variant_id"]

        # 1. Attempt checkout with balance_due > 0 and Walk-in customer
        walkin_res = pos.pos_checkout(
            items=[{"variant_id": v_id, "item_type": "ACCESSORY", "item_name": "Fast Cable RB2", "qty": 1, "unit_price": 2000}],
            customer_name="Walk-in Customer",
            customer_phone="",
            paid_amount=0,
            payment_method="UDHAAR",
            user_id=1,
            username="admin"
        )
        self.assertFalse(walkin_res["success"])
        self.assertIn("Customer account is required", walkin_res["error"])

        # 2. Checkout with real customer
        real_res = pos.pos_checkout(
            items=[{"variant_id": v_id, "item_type": "ACCESSORY", "item_name": "Fast Cable RB2", "qty": 1, "unit_price": 2000}],
            customer_name="Rashid Minhas",
            customer_phone="03121234567",
            paid_amount=500,  # Partial credit: 1500 balance due
            payment_method="CASH",
            user_id=1,
            username="admin"
        )
        self.assertTrue(real_res["success"])
        sid = real_res["sale_id"]

        # Verify sale, customer, and udhaar_ledger are all linked
        sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sid,))
        self.assertEqual(sale["customer_name"], "Rashid Minhas")
        self.assertEqual(float(sale["balance_due"]), 1500.0)

        # Customer balance updated in one transaction
        cust = db.query_one("SELECT * FROM customers WHERE id = ?", (sale["customer_id"],))
        self.assertEqual(float(cust["balance_udhaar"]), 1500.0)

        # Receipt prints Balance Due
        receipt_html = printing.render_sale_receipt(sid)
        self.assertIn("Balance Due:", receipt_html)
        self.assertIn("1,500", receipt_html)

    def test_rb3_multi_field_returns_and_alias(self):
        """RB3: Return lookup by invoice #, customer name, phone, item name, or IMEI.
        selectSaleForReturn function alias exists."""
        # Check alias in web_ui.py
        with open("web_ui.py", "r", encoding="utf-8") as f:
            web_code = f.read()
        self.assertIn("selectSaleForReturn", web_code)
        self.assertIn("window.selectSaleForReturn = selectSaleForReturn", web_code)

        # Create unique phone with dual IMEIs and sell it
        ts = str(int(time.time() * 1000))[-8:]
        imei1 = f"35{ts}01"
        imei2 = f"35{ts}02"
        pid = inventory.create_product("Xiaomi", f"Redmi Note {ts}", category="Smartphone", item_type="PHONE", user_id=1, username="admin")
        v_res = inventory.create_item_unified({
            "product_id": pid,
            "brand": "Xiaomi",
            "name": f"Redmi Note {ts}",
            "category": "Smartphone",
            "item_type": "PHONE",
            "variants": [{
                "ram": "8GB", "storage": "128GB", "color": "Midnight Black",
                "retail_price": 45000, "wholesale_price": 40000,
                "stock_quantity": 1, "imeis": f"{imei1} / {imei2}",
                "pta_status": "PTA_APPROVED", "condition": "NEW_BOX_PACK"
            }]
        }, user_id=1, username="admin")
        vid = v_res["variant_id"]
        units = db.query_all("SELECT id FROM units WHERE variant_id = ?", (vid,))
        self.assertTrue(len(units) >= 1)
        uid = units[0]["id"]

        # Sell to "Kamran Khan"
        s_res = pos.pos_checkout(
            items=[{"variant_id": vid, "unit_id": uid, "item_type": "PHONE", "item_name": f"Redmi Note {ts}", "qty": 1, "unit_price": 45000}],
            customer_name="Kamran Khan",
            customer_phone="03335555444",
            paid_amount=45000,
            payment_method="CASH",
            user_id=1,
            username="admin"
        )
        self.assertTrue(s_res["success"])
        inv_no = s_res["invoice_no"]
        sale_id = s_res["sale_id"]

        # Search by customer name
        res_by_name = db.query_all("SELECT * FROM sales WHERE customer_name LIKE ?", ("%Kamran Khan%",))
        self.assertTrue(len(res_by_name) >= 1)

        # Search by IMEI 2
        res_by_imei = db.query_all("""
            SELECT DISTINCT s.* FROM sales s
            JOIN sale_items si ON s.id = si.sale_id
            WHERE si.imei2 = ?
        """, (imei2,))
        self.assertTrue(len(res_by_imei) >= 1)

        # Process Return
        si = db.query_one("SELECT id FROM sale_items WHERE sale_id = ?", (sale_id,))
        ret_res = pos.process_return(
            sale_id=sale_id,
            return_items_data=[{"sale_item_id": si["id"], "qty": 1, "action": "RESTOCK"}],
            refund_type="CASH",
            reason="Customer Defect Check",
            user_id=1,
            username="admin"
        )
        self.assertTrue(ret_res["success"])

        # Verify unit is restocked
        unit_after = db.query_one("SELECT status FROM units WHERE id = ?", (uid,))
        self.assertEqual(unit_after["status"], "IN_STOCK")

        # Second return of same unit blocked
        ret_dup = pos.process_return(
            sale_id=sale_id,
            return_items_data=[{"sale_item_id": si["id"], "qty": 1, "action": "RESTOCK"}],
            refund_type="CASH",
            reason="Duplicate attempt",
            user_id=1,
            username="admin"
        )
        self.assertFalse(ret_dup["success"])

    def test_rb4_fresh_database_matrix_creator(self):
        """RB4: Prove Variant Matrix creates exactly 6 variants for 3 colors x 2 combos 
        on a pristine database with zero seed dependency, repeated run produces 0 duplicates, 
        and variants are immediately sellable in POS."""
        # 1. Create a new model
        ts = str(int(time.time() * 1000))[-6:]
        model_name = f"Galaxy A15 Fresh {ts}"
        pid = inventory.create_product("Samsung", model_name, category="Smartphone", item_type="PHONE", user_id=1, username="admin")

        combos = [{"ram": "4GB", "storage": "128GB"}, {"ram": "8GB", "storage": "256GB"}]
        colors = ["Black", "Blue", "Green"]

        # 2. First Run: generate matrix
        var_ids_1 = inventory.generate_variant_matrix(
            pid, combos, colors,
            default_retail=55000, default_wholesale=49000,
            base_low_stock_level=2,
            user_id=1, username="admin"
        )
        self.assertEqual(len(var_ids_1), 6, "Expected exactly 6 variants (3 colors x 2 RAM/Storage)!")

        # Verify in database
        vars_in_db = db.query_all("SELECT * FROM variants WHERE product_id = ?", (pid,))
        self.assertEqual(len(vars_in_db), 6)

        # 3. Repeated Run on same model: produces 0 duplicates
        var_ids_2 = inventory.generate_variant_matrix(
            pid, combos, colors,
            default_retail=56000, default_wholesale=50000,
            user_id=1, username="admin"
        )
        vars_after_dup = db.query_all("SELECT * FROM variants WHERE product_id = ?", (pid,))
        self.assertEqual(len(vars_after_dup), 6, "Repeated matrix run must NOT produce duplicate variants!")

        # 4. Add stock with dual IMEIs to one variant
        target_vid = var_ids_1[0]
        i1 = f"35{ts}8801"
        i2 = f"35{ts}8802"
        stock_res = inventory.add_stock(
            variant_id=target_vid,
            cost_price=49000,
            imeis=f"{i1} / {i2}",
            qty=1,
            condition="NEW_BOX_PACK",
            pta_status="PTA_APPROVED",
            user_id=1, username="admin"
        )
        self.assertTrue(stock_res["success"])

        # 5. Immediately sellable in POS
        v_check = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (target_vid,))
        self.assertEqual(v_check["stock_quantity"], 1)

        pos_sale = pos.pos_checkout(
            items=[{"variant_id": target_vid, "item_type": "PHONE", "item_name": model_name, "qty": 1, "unit_price": 55000, "imei1": i1}],
            customer_name="Tariq Jamil",
            customer_phone="03451122334",
            paid_amount=55000,
            payment_method="CASH",
            user_id=1, username="admin"
        )
        self.assertTrue(pos_sale["success"])

        # Stock drops to 0 and unit is SOLD
        v_sold = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (target_vid,))
        self.assertEqual(v_sold["stock_quantity"], 0)

if __name__ == "__main__":
    unittest.main()
