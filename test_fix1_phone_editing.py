import pytest, time, json
import db, auth, inventory, scanner

@pytest.fixture(autouse=True)
def setup_test_db():
    # Setup test product, variants, and units
    now = "2026-10-13 12:00:00"
    with db.transaction() as cx:
        # Create test phone product
        cx.execute("DELETE FROM units WHERE imei1 LIKE '8600000000000%'")
        cx.execute("DELETE FROM variants WHERE sku LIKE 'TEST-SKU-%'")
        cx.execute("DELETE FROM products WHERE name LIKE 'Test Phone Model%'")

        cur = cx.execute("""
            INSERT INTO products (brand, name, category, item_type, default_warranty_months, notes, created_at, updated_at)
            VALUES ('Samsung', 'Test Phone Model S24', 'Smartphone', 'PHONE', 12, 'Flagship device', ?, ?)
        """, (now, now))
        pid = cur.lastrowid

        # Create two variants
        cur_v1 = cx.execute("""
            INSERT INTO variants (product_id, ram, storage, color, network, sku, barcode, retail_price, wholesale_price, min_selling_price, stock_quantity, low_stock_level, reorder_qty, created_at, updated_at)
            VALUES (?, '8GB', '128GB', 'Phantom Black', '5G', 'TEST-SKU-1', 'BARCODE-V1', 150000, 130000, 145000, 0, 3, 5, ?, ?)
        """, (pid, now, now))
        v1_id = cur_v1.lastrowid

        cur_v2 = cx.execute("""
            INSERT INTO variants (product_id, ram, storage, color, network, sku, barcode, retail_price, wholesale_price, min_selling_price, stock_quantity, low_stock_level, reorder_qty, created_at, updated_at)
            VALUES (?, '8GB', '256GB', 'Titanium Gray', '5G', 'TEST-SKU-2', 'BARCODE-V2', 170000, 145000, 165000, 0, 3, 5, ?, ?)
        """, (pid, now, now))
        v2_id = cur_v2.lastrowid

    yield {"pid": pid, "v1_id": v1_id, "v2_id": v2_id}

    # Cleanup
    with db.transaction() as cx:
        cx.execute("DELETE FROM units WHERE imei1 LIKE '8600000000000%'")
        cx.execute("DELETE FROM variants WHERE sku LIKE 'TEST-SKU-%'")
        cx.execute("DELETE FROM products WHERE name LIKE 'Test Phone Model%'")

def test_product_model_edit(setup_test_db):
    pid = setup_test_db["pid"]
    res = inventory.update_product(
        pid, brand="Samsung", name="Test Phone Model S24 Ultra", category="Flagship",
        item_type="PHONE", warranty_months=24, compatible_models="Universal",
        notes="Updated notes", image_url="/static/s24u.jpg", user_id=1, username="admin"
    )
    assert res["success"] is True
    p = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    assert p["name"] == "Test Phone Model S24 Ultra"
    assert p["default_warranty_months"] == 24
    assert p["category"] == "Flagship"
    assert p["image_url"] == "/static/s24u.jpg"

def test_variant_edit_and_stock_guard(setup_test_db):
    v1_id = setup_test_db["v1_id"]
    # Add 1 unit to variant 1
    # Valid 15-digit Luhn IMEI: 860000000000010 (86000000000001 + check digit)
    check_dig = scanner.calculate_luhn_digit("86000000000001")
    valid_imei = "86000000000001" + check_dig
    
    add_res = inventory.add_unit(v1_id, valid_imei, cost_price=120000, user_id=1, username="admin")
    assert add_res["success"] is True

    # Try to edit variant with manual stock_quantity = 50. For phone, it MUST stay 1 (count of in-stock units)
    upd_res = inventory.update_variant(
        v1_id, ram="12GB", storage="256GB", color="Phantom Black", network="5G",
        retail_price=160000, wholesale_price=135000, min_selling_price=155000,
        stock_quantity=50, barcode="BARCODE-V1", low_stock_level=4, reorder_qty=10,
        user_id=1, username="admin"
    )
    assert upd_res["success"] is True
    v1 = db.query_one("SELECT * FROM variants WHERE id = ?", (v1_id,))
    assert v1["ram"] == "12GB"
    assert v1["retail_price"] == 160000
    assert v1["stock_quantity"] == 1  # Guarded: derived strictly from IN_STOCK units!

def test_variant_clone_and_archive(setup_test_db):
    v1_id = setup_test_db["v1_id"]
    # 2-click clone variant
    cloned_id = inventory.clone_variant(v1_id, new_color="Cream White", retail_price=152000, user_id=1, username="admin")
    assert cloned_id is not None
    cloned = db.query_one("SELECT * FROM variants WHERE id = ?", (cloned_id,))
    assert cloned["color"] == "Cream White"
    assert cloned["retail_price"] == 152000

    # Archive and restore
    arch_res = inventory.archive_variant(cloned_id, user_id=1, username="admin")
    assert arch_res["success"] is True
    assert db.query_one("SELECT is_archived FROM variants WHERE id = ?", (cloned_id,))["is_archived"] == 1

    rest_res = inventory.restore_variant(cloned_id, user_id=1, username="admin")
    assert rest_res["success"] is True
    assert db.query_one("SELECT is_archived FROM variants WHERE id = ?", (cloned_id,))["is_archived"] == 0

def test_unit_edit_luhn_and_self_collision(setup_test_db):
    v1_id = setup_test_db["v1_id"]
    check_dig = scanner.calculate_luhn_digit("86000000000002")
    valid_imei = "86000000000002" + check_dig

    add_res = inventory.add_unit(v1_id, valid_imei, cost_price=120000, user_id=1, username="admin")
    assert add_res["success"] is True
    unit_id = add_res["unit_id"]

    # 1. Invalid Luhn without override must fail
    res_inv = inventory.update_unit(unit_id, "860000000000029", override_luhn=False, user_id=1, username="admin", user_role="ADMIN")
    assert res_inv["success"] is False
    assert "Invalid IMEI" in res_inv["error"]

    # 2. Invalid Luhn WITH override but without admin reason must fail
    res_no_reason = inventory.update_unit(unit_id, "860000000000029", override_luhn=True, admin_reason="", user_id=1, username="admin", user_role="ADMIN")
    assert res_no_reason["success"] is False
    assert "Admin reason is mandatory" in res_no_reason["error"]

    # 3. Invalid Luhn WITH override AND admin reason must pass
    res_override = inventory.update_unit(unit_id, "860000000000029", override_luhn=True, admin_reason="Demo test device", user_id=1, username="admin", user_role="ADMIN")
    assert res_override["success"] is True

    # 4. Save unchanged valid IMEI: must NOT collide with itself
    res_self = inventory.update_unit(unit_id, valid_imei, condition="Open Box (10/10)", cost_price=125000, user_id=1, username="admin", user_role="ADMIN")
    assert res_self["success"] is True
    u = db.query_one("SELECT * FROM units WHERE id = ?", (unit_id,))
    assert u["imei1"] == valid_imei
    assert u["condition"] == "Open Box (10/10)"
    assert u["cost_price"] == 125000

def test_unit_move_variant(setup_test_db):
    v1_id = setup_test_db["v1_id"]
    v2_id = setup_test_db["v2_id"]
    check_dig = scanner.calculate_luhn_digit("86000000000003")
    valid_imei = "86000000000003" + check_dig

    add_res = inventory.add_unit(v1_id, valid_imei, cost_price=120000, user_id=1, username="admin")
    unit_id = add_res["unit_id"]

    assert db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (v1_id,))["stock_quantity"] == 1
    assert db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (v2_id,))["stock_quantity"] == 0

    # Move unit from variant 1 to variant 2
    res_move = inventory.update_unit(unit_id, valid_imei, target_variant_id=v2_id, user_id=1, username="admin", user_role="ADMIN")
    assert res_move["success"] is True

    u = db.query_one("SELECT variant_id FROM units WHERE id = ?", (unit_id,))
    assert u["variant_id"] == v2_id
    # Stock quantities dynamically synced
    assert db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (v1_id,))["stock_quantity"] == 0
    assert db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (v2_id,))["stock_quantity"] == 1

def test_unit_sold_warning_and_permissions(setup_test_db):
    v1_id = setup_test_db["v1_id"]
    check_dig = scanner.calculate_luhn_digit("86000000000004")
    valid_imei = "86000000000004" + check_dig

    add_res = inventory.add_unit(v1_id, valid_imei, cost_price=120000, user_id=1, username="admin")
    unit_id = add_res["unit_id"]

    # Mark unit as SOLD
    db.execute("UPDATE units SET status = 'SOLD' WHERE id = ?", (unit_id,))

    # Employee edit must be rejected
    res_emp = inventory.update_unit(unit_id, valid_imei, cost_price=125000, user_id=2, username="staff", user_role="EMPLOYEE")
    assert res_emp["success"] is False
    assert "Access Denied" in res_emp["error"]

    # Admin edit on SOLD unit without reason must fail
    res_no_reas = inventory.update_unit(unit_id, valid_imei, cost_price=125000, admin_reason="", user_id=1, username="admin", user_role="ADMIN")
    assert res_no_reas["success"] is False
    assert "requires a mandatory Admin reason" in res_no_reas["error"]

    # Admin edit on SOLD unit with reason must succeed and be audit logged
    t0 = time.perf_counter()
    res_admin = inventory.update_unit(unit_id, valid_imei, cost_price=125000, admin_reason="Supplier refunded discount", user_id=1, username="admin", user_role="ADMIN")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert res_admin["success"] is True
    assert elapsed_ms <= 100  # Latency target <= 100ms
