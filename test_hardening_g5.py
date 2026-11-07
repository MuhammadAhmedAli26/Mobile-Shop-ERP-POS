# test_hardening_g5.py
# Verification suite for Gate G5: Shop Profile, Logo Processing Engine, Live Change-Feed, & Forbidden Literals

import unittest
import os, io, json
from PIL import Image
import db, printing, logo_engine

class TestHardeningG5ShopProfileAndSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_01_central_shop_profile_store(self):
        """Verify reading and updating shop profile centrally increments version and updates printing info."""
        old_info = printing.get_shop_info()
        old_ver = old_info.get("profile_version", 1)

        test_shop_name = "AL-MADINA MOBILES & ACCESSORIES"
        test_tagline = "Premium Phones & Instant Repairing"
        test_address = "Hall Road, Lahore, Pakistan"

        # Update profile
        with db.transaction() as cx:
            cx.execute("""
                UPDATE shop_profile SET
                    shop_name = ?,
                    tagline = ?,
                    address = ?,
                    profile_version = profile_version + 1,
                    updated_at = datetime('now')
                WHERE id = 1
            """, (test_shop_name, test_tagline, test_address))

        db.bump_change_version("profile")

        new_info = printing.get_shop_info()
        self.assertEqual(new_info["name"], test_shop_name)
        self.assertEqual(new_info["tagline"], test_tagline)
        self.assertEqual(new_info["address"], test_address)
        self.assertGreater(new_info["profile_version"], old_ver)

    def test_02_logo_processing_and_thermal_bitmaps(self):
        """Verify Pillow processes image into UI PNG and 1-bit ESC-POS 80mm/58mm monochrome rasters."""
        # Create a synthetic 200x100 RGB image with a black circle on white
        img = Image.new("RGB", (200, 100), color="white")
        for x in range(50, 150):
            for y in range(25, 75):
                img.putpixel((x, y), (0, 0, 0))
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Process and store logo
        res = logo_engine.process_and_store_logo(png_bytes)
        self.assertTrue(res["success"])
        self.assertGreater(res["ui_size"], 0)
        self.assertGreater(res["thermal_80_bytes"], 0)
        self.assertGreater(res["thermal_58_bytes"], 0)

        # Verify logo in database
        logo_bytes, mime = logo_engine.get_logo_data()
        self.assertIsNotNone(logo_bytes)
        self.assertEqual(mime, "image/png")

        # Verify thermal logo bytes for 80mm and 58mm
        esc_80 = printing.get_thermal_logo_bytes("80")
        self.assertTrue(len(esc_80) > 8)
        self.assertEqual(esc_80[:4], b'\x1dv0\x00')  # ESC-POS GS v 0 raster header

        esc_58 = printing.get_thermal_logo_bytes("58")
        self.assertTrue(len(esc_58) > 8)
        self.assertEqual(esc_58[:4], b'\x1dv0\x00')

        # Verify remove logo
        rem = logo_engine.remove_logo()
        self.assertTrue(rem["success"])
        no_logo, _ = logo_engine.get_logo_data()
        self.assertIsNone(no_logo)

    def test_03_change_feed_state_and_versioning(self):
        """Verify change-feed state tracks global version, profile version, and groups."""
        state = db.get_change_feed_state()
        self.assertIn("version", state)
        self.assertIn("profile_version", state)
        self.assertIn("groups", state)
        
        prev_ver = state["version"]
        db.bump_change_version("items")
        state_after = db.get_change_feed_state()
        self.assertGreater(state_after["version"], prev_ver)

    def test_04_zero_forbidden_garments_literals(self):
        """Automated Build Test: Zero hardcoded legacy garments/ATFAAL literals in core python files."""
        import glob
        forbidden_words = ["ATFAAL", "GARMENTS", "KIDS WEAR", "BABA SUIT", "FROCK"]
        files_to_check = [
            "config.py", "auth.py", "inventory.py", "pos.py", 
            "purchasing.py", "printing.py", "services.py", "accounting.py"
        ]
        
        violations = []
        base_dir = os.path.dirname(__file__)
        for fn in files_to_check:
            try:
                full_path = os.path.join(base_dir, fn)
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().upper()
                    for word in forbidden_words:
                        if word in content:
                            violations.append(f"{fn} contains forbidden word: {word}")
            except FileNotFoundError:
                pass

        self.assertEqual(violations, [], msg=f"Forbidden legacy literals detected: {violations}")

if __name__ == "__main__":
    unittest.main()
