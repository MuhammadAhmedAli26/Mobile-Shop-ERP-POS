# test_hardening_g4.py
# Verification suite for Gate G4: Accounts and Employee Lock-Down

import unittest
import uuid, time
import db, auth, config

class TestHardeningG4AccountsAndRBAC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            h_admin = auth.hash_password("admin123")
            h_staff = auth.hash_password("staff123")
            db.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (h_admin,))
            db.execute("UPDATE users SET password_hash = ? WHERE username = 'staff'", (h_staff,))
            db.execute("DELETE FROM users WHERE username NOT IN ('admin', 'staff')")
            auth.set_admin_recovery_key("7A4K-9M2X-8P1Q-3N6R-5V8W-2T9Y")
        except Exception:
            pass

    def test_01_bcrypt_hashing_and_verification(self):
        """Verify standard bcrypt password hashing and comparison."""
        plain = "MySecretPass_99!"
        h = auth.hash_password(plain)
        self.assertTrue(h.startswith("$2b$") or h.startswith("$2a$"))
        self.assertTrue(auth.verify_password(plain, h))
        self.assertFalse(auth.verify_password("WrongPassword", h))

    def test_02_legacy_sha256_backward_compatibility_and_upgrade(self):
        """Verify legacy SHA-256 hashes still authenticate and auto-upgrade to bcrypt."""
        test_uname = f"legacy_u_{uuid.uuid4().hex[:6]}"
        plain_pass = "LegacyPass123"
        # Simulate an old SHA-256 hash in database
        import hashlib
        old_hash = hashlib.sha256((plain_pass + config.SESSION_SECRET).encode('utf-8')).hexdigest()
        
        now = "2026-01-01 00:00:00"
        uid = db.execute("""
            INSERT INTO users (username, password_hash, role, full_name, is_active, created_at)
            VALUES (?, ?, 'EMPLOYEE', 'Legacy User', 1, ?)
        """, (test_uname, old_hash, now))

        # Authenticate should succeed
        user = auth.authenticate(test_uname, plain_pass)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], uid)

        # Check that hash in DB was upgraded to bcrypt
        updated = db.query_one("SELECT password_hash FROM users WHERE id = ?", (uid,))
        self.assertTrue(updated["password_hash"].startswith(("$2b$", "$2a$")))
        self.assertTrue(auth.verify_password(plain_pass, updated["password_hash"]))

    def test_03_brute_force_rate_limiting(self):
        """Verify 5 failed attempts trigger rate-limiting lockout."""
        ip = f"192.168.1.{uuid.uuid4().int % 250}"
        test_user = f"victim_{uuid.uuid4().hex[:4]}"

        # 4 consecutive bad attempts should not be locked yet
        for _ in range(4):
            res = auth.authenticate(test_user, "badpass", ip=ip)
            self.assertIsNone(res)

        # 5th bad attempt triggers lockout
        res5 = auth.authenticate(test_user, "badpass", ip=ip)
        self.assertIsNone(res5)

        # 6th attempt should be blocked with RATE_LIMITED
        res6 = auth.authenticate(test_user, "badpass", ip=ip)
        self.assertIsInstance(res6, dict)
        self.assertEqual(res6.get("error"), "RATE_LIMITED")
        self.assertGreaterEqual(res6.get("wait_seconds", 0), 20)

    def test_04_recovery_key_flow(self):
        """Verify 24-character grouped recovery key generation, verification, and password reset."""
        key = auth.generate_recovery_key()
        parts = key.split("-")
        self.assertEqual(len(parts), 6)
        for p in parts:
            self.assertEqual(len(p), 4)

        # Store recovery key hash
        auth.set_admin_recovery_key(key)
        self.assertTrue(auth.verify_admin_recovery_key(key))
        self.assertFalse(auth.verify_admin_recovery_key("0000-0000-0000-0000-0000-0000"))

        # Reset admin password via recovery key
        new_pass = f"NewAdminPass_{uuid.uuid4().hex[:6]}"
        reset_res = auth.reset_admin_password_with_recovery_key(key, new_pass)
        self.assertTrue(reset_res["success"])
        new_recovery_key = reset_res["new_recovery_key"]
        self.assertNotEqual(key, new_recovery_key)

        # Old recovery key should now be invalid
        self.assertFalse(auth.verify_admin_recovery_key(key))
        # New recovery key should be valid
        self.assertTrue(auth.verify_admin_recovery_key(new_recovery_key))

        # Admin can login with new password
        admin_u = reset_res["username"]
        auth_admin = auth.authenticate(admin_u, new_pass)
        self.assertIsNotNone(auth_admin)

        # Restore admin password to standard 'admin123' and default recovery key
        h_admin = auth.hash_password("admin123")
        db.execute("UPDATE users SET password_hash = ? WHERE username = 'admin'", (h_admin,))
        auth.set_admin_recovery_key("7A4K-9M2X-8P1Q-3N6R-5V8W-2T9Y")

    def test_05_employee_management_and_admin_protection(self):
        """Verify admin can create employees, reset their passwords, and cannot disable the last admin."""
        emp_name = f"emp_{uuid.uuid4().hex[:6]}"
        res = auth.create_employee(emp_name, "TempPass123", full_name="Sales Guy")
        self.assertTrue(res["success"])
        emp_id = res["user_id"]

        # Duplicate username rejected
        dup_res = auth.create_employee(emp_name, "AnotherPass123")
        self.assertFalse(dup_res["success"])

        # Reset employee password
        rst = auth.reset_user_password(emp_id, "NewTempPass456")
        self.assertTrue(rst["success"])

        # Disable employee
        dis = auth.toggle_user_status(emp_id, 0)
        self.assertTrue(dis["success"])
        self.assertFalse(dis["is_active"])

        # Disabled employee cannot login
        self.assertIsNone(auth.authenticate(emp_name, "NewTempPass456"))

        # Re-enable employee
        enb = auth.toggle_user_status(emp_id, 1)
        self.assertTrue(enb["success"])
        self.assertTrue(enb["is_active"])
        self.assertIsNotNone(auth.authenticate(emp_name, "NewTempPass456"))

        # Protection: Cannot disable the only active Admin
        admin = db.query_one("SELECT id FROM users WHERE role = 'ADMIN' AND is_active = 1 LIMIT 1")
        if admin:
            # If there's only 1 active admin, disabling it must fail
            active_count = db.query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'ADMIN' AND is_active = 1")["c"]
            if active_count == 1:
                fail_dis = auth.toggle_user_status(admin["id"], 0)
                self.assertFalse(fail_dis["success"])

    def test_06_change_own_password(self):
        """Verify user changing own password requires correct current password."""
        test_u = f"user_pwd_{uuid.uuid4().hex[:6]}"
        create_res = auth.create_employee(test_u, "InitialPass123")
        uid = create_res["user_id"]

        # Wrong current password fails
        bad = auth.change_own_password(uid, "WrongCurrent", "BrandNewPass999")
        self.assertFalse(bad["success"])

        # Correct current password succeeds
        good = auth.change_own_password(uid, "InitialPass123", "BrandNewPass999")
        self.assertTrue(good["success"])
        self.assertIsNotNone(auth.authenticate(test_u, "BrandNewPass999"))

    def test_07_admin_override_pin(self):
        """Verify setting and checking Admin Override PIN."""
        set_res = auth.set_admin_override_pin("8844")
        self.assertTrue(set_res["success"])
        self.assertTrue(auth.verify_admin_override_pin("8844"))
        self.assertFalse(auth.verify_admin_override_pin("1122"))

        # Invalid length PIN fails
        bad_len = auth.set_admin_override_pin("12")
        self.assertFalse(bad_len["success"])

    def test_08_role_data_serializer_strips_cost_and_profit(self):
        """Verify employee serializer strips sensitive cost, wholesale, supplier, and profit info."""
        item = {
            "id": 101,
            "name": "iPhone 15 Pro",
            "retail_price": 380000,
            "wholesale_price": 350000,
            "cost_price": 340000,
            "cost": 340000,
            "supplier_id": 5,
            "supplier_name": "Hafeez Center Tech",
            "margin": 40000,
            "profit": 40000,
            "net_profit": 35000,
            "stock_quantity": 4
        }
        # Admin gets everything
        admin_view = auth.serialize_item_for_role(item, "ADMIN")
        self.assertIn("wholesale_price", admin_view)
        self.assertIn("cost_price", admin_view)
        self.assertIn("profit", admin_view)

        # Employee gets cost and margin stripped
        emp_view = auth.serialize_item_for_role(item, "EMPLOYEE")
        self.assertEqual(emp_view["retail_price"], 380000)
        self.assertEqual(emp_view["stock_quantity"], 4)
        self.assertNotIn("wholesale_price", emp_view)
        self.assertNotIn("cost_price", emp_view)
        self.assertNotIn("cost", emp_view)
        self.assertNotIn("supplier_id", emp_view)
        self.assertNotIn("supplier_name", emp_view)
        self.assertNotIn("margin", emp_view)
        self.assertNotIn("profit", emp_view)
        self.assertNotIn("net_profit", emp_view)

if __name__ == "__main__":
    unittest.main()
