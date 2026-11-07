# test_hardening_g1.py
# Reproduction tests for Gate G1:
# 1. Money parsing with commas or currency strings ("1,500", "Rs. 1,500") throws ValueError
# 2. Missing unified create/update contract for accessories and spare parts
# 3. Default credentials exist in config.py
# 4. SHA-256 hash used instead of bcrypt in auth.py
# 5. Host bound to 0.0.0.0 triggering firewall warning instead of 127.0.0.1

import unittest
import config, auth, db, inventory

class TestHardeningG1Reproduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with db.transaction() as cx:
            p = cx.execute("SELECT id FROM products WHERE id = 1").fetchone()
            if not p:
                cx.execute("INSERT OR IGNORE INTO products (id, brand, name, category, item_type, created_at, updated_at) VALUES (1, 'TestBrand', 'TestPhone', 'Mobile Phone', 'PHONE', datetime('now'), datetime('now'))")

    @classmethod
    def tearDownClass(cls):
        with db.transaction() as cx:
            cx.execute("DELETE FROM variants WHERE product_id = 1")
            cx.execute("DELETE FROM products WHERE id = 1 AND brand = 'TestBrand'")

    def test_repro_1_money_parsing_with_comma_fails_today(self):
        """Proof: Passing '1,500' or 'Rs. 1500' to create_variant now succeeds without ValueError."""
        var_id = inventory.create_variant(1, retail_price="1,500", color="G1-Test-1")
        self.assertIsInstance(var_id, int)

    def test_repro_2_money_parsing_with_currency_fails_today(self):
        """Proof: Passing 'Rs. 2,000' to create_variant now succeeds without ValueError."""
        var_id = inventory.create_variant(1, retail_price="Rs. 2,000", color="G1-Test-2")
        self.assertIsInstance(var_id, int)

    def test_repro_3_default_credentials_exist_in_config(self):
        """Proof: config.DEFAULT_ADMIN_PASSWORD has been removed/None to prevent default backdoor."""
        self.assertIsNone(getattr(config, "DEFAULT_ADMIN_PASSWORD", None))

    def test_repro_4_auth_uses_sha256_instead_of_bcrypt(self):
        """Proof: auth.hash_password now uses secure salted bcrypt ($2b$)."""
        h = auth.hash_password("admin123")
        self.assertTrue(h.startswith("$2b$") or h.startswith("$2a$"))

    def test_repro_5_host_binds_to_all_interfaces(self):
        """Proof: config.HOST is strictly '127.0.0.1' avoiding Windows Firewall popups."""
        self.assertEqual(config.HOST, "127.0.0.1")

if __name__ == "__main__":
    unittest.main()
