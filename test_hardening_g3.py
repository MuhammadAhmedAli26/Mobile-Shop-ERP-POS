# test_hardening_g3.py
# Verification suite for Gate G3: Unified Item Creation & Mutation Bulletproofing

import unittest
import uuid
import db
import inventory

class TestHardeningG3UnifiedItemCreation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_01_parse_money_variations(self):
        """Verify normalizer handles commas, Rs., PKR, whitespace, and Urdu numerals."""
        self.assertEqual(inventory.parse_money("1,500"), 1500.0)
        self.assertEqual(inventory.parse_money("Rs. 2,500"), 2500.0)
        self.assertEqual(inventory.parse_money("PKR  3,500.75"), 3500.75)
        self.assertEqual(inventory.parse_money("Rs 450"), 450.0)
        # Urdu Eastern Arabic numerals: ۱ (1), ۵ (5), ۰ (0), ۰ (0) -> 1500
        self.assertEqual(inventory.parse_money("۱۵۰۰"), 1500.0)
        self.assertEqual(inventory.parse_money("۲۵۰۰.۵۰"), 2500.5)
        self.assertEqual(inventory.parse_money(None, default=0.0), 0.0)
        self.assertEqual(inventory.parse_money("", default=10.0), 10.0)

    def test_02_create_accessory_unified_auto_codes(self):
        """Verify creating an accessory automatically generates unique SKU/Barcode and adds stock."""
        req_id = str(uuid.uuid4())
        payload = {
            "item_type": "ACCESSORY",
            "brand": "Anker",
            "name": f"PowerPort III Nano {req_id[:6]}",
            "category": "Chargers",
            "retail_price": "Rs. 2,800",
            "wholesale_price": "2,100",
            "min_selling_price": "2,500",
            "stock_quantity": 15,
            "compatible_models": "Universal Type-C",
            "request_id": req_id
        }
        res = inventory.create_item_unified(payload, user_id=1, username="admin")
        self.assertTrue(res["success"], msg=res.get("message"))
        self.assertIn("item_id", res)
        self.assertIn("variant_id", res)
        self.assertTrue(res["sku"].startswith("ACC-"))
        self.assertTrue(res["barcode"].startswith("BAR-ACC-"))
        self.assertEqual(res["retail_price"], 2800.0)
        self.assertEqual(res["stock_quantity"], 15)

        # Verify database record
        v = db.query_one("SELECT * FROM variants WHERE id = ?", (res["variant_id"],))
        self.assertIsNotNone(v)
        self.assertEqual(v["stock_quantity"], 15)
        self.assertEqual(v["retail_price"], 2800.0)

    def test_03_create_spare_part_unified(self):
        """Verify spare part creation with custom prefix and stock tracking."""
        req_id = str(uuid.uuid4())
        payload = {
            "item_type": "SPARE_PART",
            "brand": "OEM",
            "name": f"OLED Screen A54 {req_id[:6]}",
            "category": "LCD Displays",
            "retail_price": "14,500",
            "wholesale_price": "11,000",
            "min_selling_price": "13,500",
            "stock_quantity": 4,
            "compatible_models": "Samsung Galaxy A54 5G",
            "request_id": req_id
        }
        res = inventory.create_item_unified(payload, user_id=1, username="admin")
        self.assertTrue(res["success"])
        self.assertTrue(res["sku"].startswith("PRT-"))
        self.assertTrue(res["barcode"].startswith("BAR-PRT-"))
        self.assertEqual(res["stock_quantity"], 4)

    def test_04_create_phone_unified(self):
        """Verify phone creation with storage/RAM/color variants."""
        req_id = str(uuid.uuid4())
        payload = {
            "item_type": "PHONE",
            "brand": "Xiaomi",
            "name": f"Redmi Note 13 {req_id[:6]}",
            "category": "Smartphone",
            "ram": "8GB",
            "storage": "256GB",
            "color": "Midnight Black",
            "network": "5G Official PTA",
            "retail_price": "54,999",
            "wholesale_price": "49,000",
            "min_selling_price": "52,000",
            "stock_quantity": 0,
            "request_id": req_id
        }
        res = inventory.create_item_unified(payload, user_id=1, username="admin")
        self.assertTrue(res["success"])
        self.assertTrue(res["sku"].startswith("PHN-"))

    def test_05_duplicate_barcode_guard(self):
        """Verify duplicate barcode is rejected with HTTP 409 and clear message."""
        unique_bar = f"BAR-{uuid.uuid4().hex[:10]}"
        payload1 = {
            "item_type": "ACCESSORY",
            "brand": "Remax",
            "name": f"Fast Cable {uuid.uuid4().hex[:4]}",
            "category": "Cables",
            "retail_price": 500,
            "barcode": unique_bar,
            "stock_quantity": 2
        }
        res1 = inventory.create_item_unified(payload1)
        self.assertTrue(res1["success"])

        # Attempt to insert second item with identical barcode
        payload2 = {
            "item_type": "ACCESSORY",
            "brand": "Baseus",
            "name": f"Tough Cable {uuid.uuid4().hex[:4]}",
            "category": "Cables",
            "retail_price": 700,
            "barcode": unique_bar,
            "stock_quantity": 5
        }
        res2 = inventory.create_item_unified(payload2)
        self.assertFalse(res2["success"])
        self.assertEqual(res2["status"], 409)
        self.assertEqual(res2["code"], "DUPLICATE_BARCODE")
        self.assertIn("already in use", res2["message"])

    def test_06_pricing_validation_guard(self):
        """Verify retail_price cannot be lower than min_selling_price."""
        payload = {
            "item_type": "ACCESSORY",
            "brand": "Joyroom",
            "name": "Bluetooth Earphones",
            "retail_price": "2,000",
            "min_selling_price": "2,500",  # min is higher than retail -> invalid
            "stock_quantity": 1
        }
        res = inventory.create_item_unified(payload)
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], 422)
        self.assertEqual(res["code"], "INVALID_PRICING")

    def test_07_idempotency_caching(self):
        """Verify repeated submissions with identical request_id return cached response."""
        req_id = str(uuid.uuid4())
        payload = {
            "item_type": "ACCESSORY",
            "brand": "Ugreen",
            "name": f"OTG Adapter {req_id[:6]}",
            "retail_price": "450",
            "stock_quantity": 10,
            "request_id": req_id
        }
        res1 = inventory.create_item_unified(payload)
        self.assertTrue(res1["success"])
        self.assertFalse(res1.get("cached", False))

        # Re-post identical payload
        res2 = inventory.create_item_unified(payload)
        self.assertTrue(res2["success"])
        self.assertTrue(res2.get("cached", False))
        self.assertEqual(res1["variant_id"], res2["variant_id"])

    def test_08_health_check_diagnostics(self):
        """Verify health check diagnostics runs WAL, table, transaction rollback, and index tests."""
        diag = inventory.health_check_diagnostics()
        self.assertEqual(diag["status"], "HEALTHY")
        checks = {c["name"]: c["status"] for c in diag["checks"]}
        self.assertEqual(checks.get("Database Integrity & WAL"), "PASS")
        self.assertEqual(checks.get("Schema Migrations"), "PASS")
        self.assertEqual(checks.get("ACID Transaction & Rollback"), "PASS")
        self.assertEqual(checks.get("Catalog Indexes"), "PASS")

if __name__ == "__main__":
    unittest.main()
