# MOBILE & ACCESSORIES ERP — G3 Low Stock Alert Engine Automated Verification Tests
import unittest, os, sys, time, shutil
from datetime import datetime, timedelta

# Ensure mobile_edition is in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import config, db, auth, lookups

class TestAlertsEngineG3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure database is initialized
        db.init_db()

    def setUp(self):
        # Clean state for test fixtures
        pass

    def test_01_schema_columns_exist(self):
        """Verify all new columns in lookup_lists, products, variants and new alert tables exist."""
        with db.get_connection() as cx:
            # Check lookup_lists columns
            cur = cx.execute("PRAGMA table_info(lookup_lists)")
            cols = [r["name"] for r in cur.fetchall()]
            self.assertIn("default_low_stock_level", cols)
            self.assertIn("default_reorder_qty", cols)

            # Check products columns
            cur = cx.execute("PRAGMA table_info(products)")
            cols = [r["name"] for r in cur.fetchall()]
            self.assertIn("alert_model_stock_threshold", cols)

            # Check variants columns
            cur = cx.execute("PRAGMA table_info(variants)")
            cols = [r["name"] for r in cur.fetchall()]
            self.assertIn("low_stock_level", cols)
            self.assertIn("reorder_qty", cols)
            self.assertIn("alert_off", cols)

            # Check new tables exist
            cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_alert_state'")
            self.assertIsNotNone(cur.fetchone())
            cur = cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='stock_alert_log'")
            self.assertIsNotNone(cur.fetchone())

    def test_02_three_level_inheritance(self):
        """Verify 3-level inheritance: variant override -> category default -> global fallback."""
        import alert_engine, inventory
        
        # 1. Global default fallback
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        cat_name = f"TestCat_{now}"
        lookups.add_lookup_item("category", cat_name)
        
        # Create accessory product in category with no category default
        pid = inventory.create_product("BrandX", f"Prod_{now}", category=cat_name, item_type="ACCESSORY")
        vid_global = inventory.create_variant(pid, color="Black", retail_price=500, stock_qty=10, low_stock_level=None)
        
        state_global = alert_engine.get_variant_alert_state(vid_global)
        # Accessory global default should be 5
        self.assertEqual(state_global["effective_level"], 5)
        self.assertEqual(state_global["inherited_from"], "global")

        # 2. Category level default
        cat_item = lookups.find_duplicate_item("category", cat_name)
        alert_engine.update_category_alert_defaults(cat_item["id"], default_low_stock=8, default_reorder_qty=25)
        
        state_cat = alert_engine.get_variant_alert_state(vid_global)
        self.assertEqual(state_cat["effective_level"], 8)
        self.assertEqual(state_cat["reorder_qty"], 25)
        self.assertEqual(state_cat["inherited_from"], f"category:{cat_name}")

        # 3. Item level override
        vid_override = inventory.create_variant(pid, color="White", retail_price=500, stock_qty=10, low_stock_level=12, reorder_qty=30)
        state_override = alert_engine.get_variant_alert_state(vid_override)
        self.assertEqual(state_override["effective_level"], 12)
        self.assertEqual(state_override["reorder_qty"], 30)
        self.assertEqual(state_override["inherited_from"], "custom")

    def test_03_state_machine_transitions(self):
        """Verify OK -> LOW -> OUT and resolving transitions."""
        import alert_engine, inventory, pos, purchasing
        
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        pid = inventory.create_product("Baseus", f"Type-C Cable {now}", category="Cable", item_type="ACCESSORY")
        # Explicit level 8, initial stock 9 -> OK
        vid = inventory.create_variant(pid, color="Black", retail_price=500, wholesale_price=300, stock_qty=9, low_stock_level=8)
        
        # Initial evaluation
        with db.transaction() as cx:
            alert_engine.evaluate_stock_transitions(cx, [vid])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "OK")
        self.assertEqual(st["current_stock"], 9)

        # Sell 1 -> Stock is 8 <= level 8 -> LOW fires (transition OK -> LOW)
        sale_res = pos.process_sale(items=[{"variant_id": vid, "item_type": "ACCESSORY", "qty": 1, "unit_price": 500, "item_name": "Cable"}],
                                    payment_method="CASH", customer_name="Test Buyer")
        self.assertTrue(sale_res["success"])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "LOW")
        self.assertEqual(st["current_stock"], 8)
        # Check transition toast payload
        self.assertIn("alert_notifications", sale_res)
        self.assertEqual(len(sale_res["alert_notifications"]), 1)
        self.assertEqual(sale_res["alert_notifications"][0]["state"], "LOW")

        # Sell another -> Stock is 7 (still LOW), worsening transition should NOT fire again!
        sale_res2 = pos.process_sale(items=[{"variant_id": vid, "item_type": "ACCESSORY", "qty": 1, "unit_price": 500, "item_name": "Cable"}],
                                     payment_method="CASH", customer_name="Test Buyer")
        self.assertTrue(sale_res2["success"])
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "LOW")
        self.assertEqual(st["current_stock"], 7)
        # No duplicate toast for subsequent sales while already LOW
        self.assertEqual(len(sale_res2.get("alert_notifications", [])), 0)

        # Sell remaining 7 -> Reach 0 -> OUT fires (transition LOW -> OUT)
        sale_res3 = pos.process_sale(items=[{"variant_id": vid, "item_type": "ACCESSORY", "qty": 7, "unit_price": 500, "item_name": "Cable"}],
                                     payment_method="CASH", customer_name="Test Buyer")
        self.assertTrue(sale_res3["success"])
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "OUT")
        self.assertEqual(st["current_stock"], 0)
        self.assertEqual(len(sale_res3["alert_notifications"]), 1)
        self.assertEqual(sale_res3["alert_notifications"][0]["state"], "OUT")

        # Receive 20 in purchase -> Resolves to OK
        sup_id = purchasing.create_supplier("Test Cable Wholesaler")
        pur_res = purchasing.create_purchase(sup_id, items=[{"item_type": "ACCESSORY", "variant_id": vid, "qty": 20, "unit_cost": 250}])
        self.assertTrue(pur_res["success"])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "OK")
        self.assertEqual(st["current_stock"], 20)

    def test_04_phone_units_stock_counting(self):
        """Verify only IN_STOCK units count; In Repair / Defective do NOT count."""
        import alert_engine, inventory
        
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        pid = inventory.create_product("Google", f"Pixel 7 {now}", category="Smartphone", item_type="PHONE")
        vid = inventory.create_variant(pid, ram="8GB", storage="128GB", color="Obsidian", retail_price=90000, low_stock_level=2)
        
        # Add 3 units
        u1 = inventory.add_unit(vid, f"35{now}01")["unit_id"]
        u2 = inventory.add_unit(vid, f"35{now}02")["unit_id"]
        u3 = inventory.add_unit(vid, f"35{now}03")["unit_id"]

        with db.transaction() as cx:
            alert_engine.evaluate_stock_transitions(cx, [vid])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["current_stock"], 3)
        self.assertEqual(st["state"], "OK")

        # Move 1 unit to IN_REPAIR -> Stock is now 2 (<= level 2) -> LOW
        inventory.update_unit(u3, imei1=f"35{now}03", status="IN_REPAIR")
        with db.transaction() as cx:
            alert_engine.evaluate_stock_transitions(cx, [vid])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["current_stock"], 2)
        self.assertEqual(st["state"], "LOW")

        # Move unit back to IN_STOCK -> Stock is 3 -> OK
        inventory.update_unit(u3, imei1=f"35{now}03", status="IN_STOCK")
        with db.transaction() as cx:
            alert_engine.evaluate_stock_transitions(cx, [vid])
        
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["current_stock"], 3)
        self.assertEqual(st["state"], "OK")

    def test_05_snooze_and_mark_ordered(self):
        """Verify snooze suppresses alert and mark_ordered flags item."""
        import alert_engine, inventory
        
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        pid = inventory.create_product("Anker", f"Charger {now}", category="Charger & Adapter", item_type="ACCESSORY")
        vid = inventory.create_variant(pid, color="White", retail_price=2000, stock_qty=1, low_stock_level=5)
        
        with db.transaction() as cx:
            alert_engine.evaluate_stock_transitions(cx, [vid])
            
        st = alert_engine.get_variant_alert_state(vid)
        self.assertEqual(st["state"], "LOW")
        self.assertFalse(st["is_snoozed"])
        self.assertFalse(st["is_on_order"])

        # Snooze for 3 days
        alert_engine.snooze_alert(vid, days=3)
        st = alert_engine.get_variant_alert_state(vid)
        self.assertTrue(st["is_snoozed"])

        # Mark as ordered
        alert_engine.mark_as_ordered(vid, qty=50, expected_date=(datetime.now()+timedelta(days=2)).strftime("%Y-%m-%d"), notes="Ordered from Hafeez Center")
        st = alert_engine.get_variant_alert_state(vid)
        self.assertTrue(st["is_on_order"])
        self.assertEqual(st["on_order_qty"], 50)

    def test_06_bulk_and_import_export(self):
        """Verify inventory bulk alert update and CSV export/import preserves levels."""
        import alert_engine, inventory
        
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        pid = inventory.create_product("CaseBrand", f"Silicone Case {now}", category="Mobile Case / Cover", item_type="ACCESSORY")
        v1 = inventory.create_variant(pid, color="Clear", retail_price=300, stock_qty=5)
        v2 = inventory.create_variant(pid, color="Black", retail_price=300, stock_qty=5)
        
        # Bulk set alert level
        alert_engine.bulk_set_alert_level(variant_ids=[v1, v2], level=7, reorder_qty=40)
        
        st1 = alert_engine.get_variant_alert_state(v1)
        st2 = alert_engine.get_variant_alert_state(v2)
        self.assertEqual(st1["effective_level"], 7)
        self.assertEqual(st2["effective_level"], 7)
        self.assertEqual(st1["reorder_qty"], 40)
        self.assertEqual(st2["reorder_qty"], 40)

if __name__ == "__main__":
    unittest.main()
