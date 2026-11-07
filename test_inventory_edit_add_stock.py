import pytest, time, uuid
import db, inventory, web_ui, html

def test_accessory_update_and_stock():
    uid_str = uuid.uuid4().hex[:6]
    sku = f"ANK-20K-{uid_str}"
    bc = f"ANK-{uid_str}"
    # Setup accessory product
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("INSERT INTO products (brand, name, category, item_type) VALUES ('Anker', 'PowerCore 20k', 'Charger', 'ACCESSORY')")
        pid = cur.lastrowid
        cur.execute("INSERT INTO variants (product_id, retail_price, wholesale_price, stock_quantity, sku, barcode) VALUES (?, 6000, 4500, 10, ?, ?)", (pid, sku, bc))
        vid = cur.lastrowid

    # 1. Update accessory details & price & clear barcode
    res = inventory.update_item_unified({
        "product_id": pid,
        "variant_id": vid,
        "brand": "Anker Official",
        "name": "PowerCore 20000mAh",
        "category": "Fast Charger",
        "retail_price": "6500",
        "wholesale_price": "4800",
        "stock_quantity": "15",
        "barcode": ""  # should clear barcode to None
    }, user_id=1, username="admin")
    assert res["success"] is True, res
    assert res["item"]["retail_price"] == 6500.0
    assert res["item"]["stock_quantity"] == 15

    v_after = db.query_one("SELECT * FROM variants WHERE id = ?", (vid,))
    assert v_after["barcode"] is None or v_after["barcode"] == ""
    assert v_after["wholesale_price"] == 4800.0

    # 2. Add stock to accessory
    res_stock = inventory.add_stock_to_variant(vid, qty=10, cost_price=4800, user_id=1, username="admin")
    assert res_stock["success"] is True
    assert res_stock["units_added"] == 10

    v_stock = db.query_one("SELECT * FROM variants WHERE id = ?", (vid,))
    assert v_stock["stock_quantity"] == 25

def test_phone_update_and_stock():
    uid_str = uuid.uuid4().hex[:6]
    sku = f"REDMI-N13-{uid_str}"
    # Setup phone product
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("INSERT INTO products (brand, name, category, item_type) VALUES ('Xiaomi', 'Redmi Note 13', 'Smartphone', 'PHONE')")
        pid = cur.lastrowid
        cur.execute("INSERT INTO variants (product_id, ram, storage, color, retail_price, wholesale_price, stock_quantity, sku) VALUES (?, '8GB', '128GB', 'Blue', 45000, 38000, 0, ?)", (pid, sku))
        vid = cur.lastrowid

    # 1. Update phone details & price
    res = inventory.update_item_unified({
        "product_id": pid,
        "variant_id": vid,
        "brand": "Xiaomi Official",
        "name": "Redmi Note 13 4G",
        "category": "Smartphone",
        "retail_price": "47000",
        "wholesale_price": "39000",
        "stock_quantity": "99"  # should be ignored because phone stock is derived from units
    }, user_id=1, username="admin")
    assert res["success"] is True, res
    p_after = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    assert p_after["name"] == "Redmi Note 13 4G"
    v_after = db.query_one("SELECT * FROM variants WHERE id = ?", (vid,))
    assert v_after["retail_price"] == 47000.0
    assert v_after["stock_quantity"] == 0  # no units yet

    # 2. Add phone stock with IMEIs
    imei_test = f"860{time.time_ns() % 1000000000000:012d}"
    res_stock = inventory.add_stock_to_variant(vid, imeis=imei_test, cost_price=39000, user_id=1, username="admin")
    assert res_stock["success"] is True, res_stock
    assert res_stock["units_added"] == 1

    v_after_stock = db.query_one("SELECT * FROM variants WHERE id = ?", (vid,))
    assert v_after_stock["stock_quantity"] == 1

    unit = db.query_one("SELECT * FROM units WHERE imei1 = ?", (imei_test,))
    assert unit is not None
    assert unit["variant_id"] == vid
    assert unit["cost_price"] == 39000.0

def test_duplicate_barcode_prevention():
    uid_str = uuid.uuid4().hex[:6]
    bc1 = f"BC-SONY1-{uid_str}"
    bc2 = f"BC-SONY2-{uid_str}"
    # Setup two variants
    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("INSERT INTO products (brand, name, category, item_type) VALUES ('Sony', 'WH-1000XM4', 'Audio', 'ACCESSORY')")
        pid1 = cur.lastrowid
        cur.execute("INSERT INTO variants (product_id, retail_price, barcode) VALUES (?, 60000, ?)", (pid1, bc1))
        vid1 = cur.lastrowid

        cur.execute("INSERT INTO products (brand, name, category, item_type) VALUES ('Sony', 'WH-1000XM5', 'Audio', 'ACCESSORY')")
        pid2 = cur.lastrowid
        cur.execute("INSERT INTO variants (product_id, retail_price, barcode) VALUES (?, 80000, ?)", (pid2, bc2))
        vid2 = cur.lastrowid

    # Trying to change vid2 barcode to vid1's barcode should fail cleanly with 409
    res = inventory.update_item_unified({
        "product_id": pid2,
        "variant_id": vid2,
        "barcode": bc1
    }, user_id=1, username="admin")
    assert res["success"] is False
    assert res["status"] == 409
    assert "already in use" in res["message"]

    # Updating vid2 with its OWN barcode should succeed (no self-collision)
    res_self = inventory.update_item_unified({
        "product_id": pid2,
        "variant_id": vid2,
        "barcode": bc2
    }, user_id=1, username="admin")
    assert res_self["success"] is True
