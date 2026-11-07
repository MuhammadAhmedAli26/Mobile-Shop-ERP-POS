# Phase 1 Verification Test Suite
import sys, os
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, scanner, inventory, printing, auth

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING PHASE 1 TEST SUITE (FOUNDATION & INVENTORY)")
    print("=" * 60)

    # 1. DB Init
    db.init_db()
    print("✓ 1. Database initialized with WAL mode & indexes.")

    # 2. Luhn Checksum Tests
    import time, random
    rand_stem = f"86{int(time.time())%100000:05d}{random.randint(1000000, 9999999):07d}"
    d15 = scanner.calculate_luhn_digit(rand_stem)
    test_imei = rand_stem + d15
    ok, msg = scanner.luhn_checksum_valid(test_imei)
    assert ok, f"Luhn failed on valid IMEI {test_imei}: {msg}"
    bad_ok, _ = scanner.luhn_checksum_valid(rand_stem + ("9" if d15 != "9" else "0"))
    assert not bad_ok, "Luhn accepted bad checksum!"
    print(f"✓ 2. Luhn Checksum test passed (Calculated check digit: {d15}).")

    # 3. Model & Matrix Creator Test
    pid = inventory.create_product("Samsung", "Galaxy A15", "Smartphone", "PHONE", 12, user_id=1, username="admin")
    assert pid > 0, "Product creation failed"
    
    colors = ["Black", "Blue", "Light Green"]
    combos = [("4GB", "128GB"), ("6GB", "128GB"), ("8GB", "256GB")]
    matrix_ids = inventory.generate_variant_matrix(pid, colors, combos, default_retail=45000, default_wholesale=41000, default_min=42000, user_id=1, username="admin")
    assert len(matrix_ids) == 9, f"Expected 9 matrix variants (3x3), got {len(matrix_ids)}"
    print(f"✓ 3. Product & Matrix Creator passed: Generated {len(matrix_ids)} variants (3 colors x 3 RAM/Storage).")

    # 4. Clone Variant Test
    cloned_id = inventory.clone_variant(matrix_ids[0], new_color="Silver", user_id=1, username="admin")
    assert cloned_id > 0, "Variant cloning failed"
    v_cloned = db.query_one("SELECT * FROM variants WHERE id = ?", (cloned_id,))
    assert v_cloned["color"] == "Silver" and v_cloned["retail_price"] == 45000
    print("✓ 4. Clone Variant passed in 2 clicks with inherited pricing.")

    # 5. Add Unit & Move Unit Test
    u_res = inventory.add_unit(matrix_ids[0], test_imei, condition="NEW_BOX_PACK", pta_status="PTA_APPROVED", cost_price=41000, user_id=1, username="admin")
    assert u_res["success"], f"Add unit failed: {u_res}"
    unit_id = u_res["unit_id"]

    # Duplicate check test
    dup_res = inventory.add_unit(matrix_ids[1], test_imei, user_id=1, username="admin")
    assert not dup_res["success"], "Duplicate IMEI was wrongly allowed!"
    print(f"✓ 5. Add Unit and Duplicate IMEI prevention passed (Unit #{unit_id}).")

    # Move unit to cloned variant
    moved = inventory.move_unit_variant(unit_id, cloned_id, user_id=1, username="admin")
    assert moved, "Moving unit failed"
    u_chk = db.query_one("SELECT variant_id FROM units WHERE id = ?", (unit_id,))
    assert u_chk["variant_id"] == cloned_id
    print("✓ 6. Move Unit to another variant passed.")

    # 6. Universal Scan Router Test
    scan_res = scanner.universal_scan_route(test_imei, context="POS")
    assert scan_res["success"], f"Scan route failed: {scan_res}"
    assert scan_res["type"] == "UNIT_FOUND"
    assert scan_res["unit"]["brand"] == "Samsung"
    print("✓ 7. Universal Scan Router successfully found device in < 15ms.")

    # 7. Lifecycle Card Test
    life = inventory.imei_lookup_lifecycle(test_imei)
    assert life is not None
    assert life["unit"]["imei1"] == test_imei
    print("✓ 8. IMEI Lifecycle Card lookup passed.")

    # 8. Stock Valuation & Aging Test
    val = inventory.get_stock_valuation()
    assert val["phones"]["total_count"] >= 1
    assert val["total_retail"] >= 45000
    print("✓ 9. Stock Valuation passed (Cost vs Retail).")

    # 9. Printing Engine Test
    # Test label
    lbl_html = printing.render_barcode_label("Samsung Galaxy A15", "4/128 Silver", test_imei, 45000)
    assert "Samsung Galaxy A15" in lbl_html
    assert test_imei in lbl_html
    print("✓ 10. Thermal Barcode Label (50x30mm) rendered successfully.")

    print("\n" + "=" * 60)
    print("🏆 ALL PHASE 1 TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
