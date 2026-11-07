import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import inventory

import time
from datetime import datetime

def test_phone_multiple_variants_and_imeis():
    db.init_db()
    ts = str(int(time.time() * 1000))[-10:]
    imei_a1 = f"35{ts}11"
    imei_a2 = f"35{ts}12"
    imei_b1 = f"35{ts}21"

    payload = {
        "item_type": "PHONE",
        "brand": "Google",
        "name": f"Pixel 8 Pro Test {ts}",
        "category": "Smartphone",
        "variants": [
            {
                "ram": "12GB",
                "storage": "128GB",
                "color": "Obsidian Black",
                "retail_price": "210,000",
                "wholesale_price": "195,000",
                "stock_quantity": 2,
                "imeis": f"{imei_a1}\n{imei_a2}",
                "pta_status": "PTA_APPROVED",
                "condition": "NEW_BOX_PACK",
                "low_stock_level": 2
            },
            {
                "ram": "12GB",
                "storage": "256GB",
                "color": "Bay Blue",
                "retail_price": "235,000",
                "wholesale_price": "218,000",
                "stock_quantity": 1,
                "imeis": imei_b1,
                "pta_status": "NON_PTA",
                "condition": "NEW_BOX_PACK",
                "low_stock_level": 1
            }
        ]
    }

    res = inventory.create_item_unified(payload, user_id=1, username="admin")
    assert res["success"] is True
    assert res["status"] == 201
    assert res["variant_count"] == 2
    assert res["unit_count"] == 3

    pid = res["product_id"]
    # Verify variants in DB
    variants = db.query_all("SELECT * FROM variants WHERE product_id = ?", (pid,))
    assert len(variants) == 2

    # Verify physical units in DB
    units = db.query_all("SELECT u.* FROM units u JOIN variants v ON u.variant_id = v.id WHERE v.product_id = ?", (pid,))
    assert len(units) == 3

    imeis_saved = [u["imei1"] for u in units]
    assert imei_a1 in imeis_saved
    assert imei_a2 in imeis_saved
    assert imei_b1 in imeis_saved


def test_duplicate_imei_rejection():
    db.init_db()
    existing_u = db.query_one("SELECT imei1 FROM units LIMIT 1")
    if existing_u:
        dup_imei = existing_u["imei1"]
        ts2 = str(int(time.time() * 1000))[-8:]
        payload = {
            "item_type": "PHONE",
            "brand": "Samsung",
            "name": f"Galaxy S24 Duplicate Test {ts2}",
            "variants": [
                {
                    "ram": "8GB",
                    "storage": "128GB",
                    "color": "Black",
                    "retail_price": 100000,
                    "wholesale_price": 90000,
                    "imeis": dup_imei
                }
            ]
        }
        res = inventory.create_item_unified(payload, user_id=1, username="admin")
        assert res["success"] is False
        assert res["status"] == 409
        assert "ALREADY REGISTERED" in res["message"]


def test_add_stock_to_existing_variant():
    db.init_db()
    ts3 = str(int(time.time() * 1000))[-8:]
    # Create phone with 1 variant 0 stock
    payload = {
        "item_type": "PHONE",
        "brand": "OnePlus",
        "name": f"OnePlus 12 Test {ts3}",
        "ram": "16GB",
        "storage": "512GB",
        "color": "Emerald Green",
        "retail_price": 180000,
        "wholesale_price": 165000,
        "stock_quantity": 0
    }
    res = inventory.create_item_unified(payload, user_id=1, username="admin")
    assert res["success"] is True
    vid = res["variant_id"]

    new_imei = f"35{ts3}9999"
    stock_res = inventory.add_stock_to_variant(vid, cost_price=165000, imeis=[new_imei], user_id=1, username="admin")
    assert stock_res["success"] is True
    assert stock_res["units_added"] == 1

    v_after = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (vid,))
    assert v_after["stock_quantity"] == 1

    u_after = db.query_one("SELECT * FROM units WHERE imei1 = ?", (new_imei,))
    assert u_after is not None
    assert u_after["status"] == "IN_STOCK"


def test_add_variant_to_existing_product_via_product_id():
    db.init_db()
    ts = str(int(time.time() * 1000))[-8:]
    # 1. Create base phone product
    pid = inventory.create_product("Xiaomi", f"Redmi Note 13 {ts}", category="Smartphone", item_type="PHONE", user_id=1, username="admin")
    assert pid > 0

    # 2. Add variant to existing product via create_item_unified with product_id
    imei_v = f"86{ts}33221"
    payload = {
        "product_id": pid,
        "variants": [
            {
                "ram": "8GB",
                "storage": "256GB",
                "color": "Midnight Black",
                "retail_price": 54000,
                "wholesale_price": 49000,
                "stock_quantity": 1,
                "imeis": imei_v,
                "pta_status": "PTA_APPROVED",
                "condition": "NEW_BOX_PACK"
            }
        ]
    }
    res = inventory.create_item_unified(payload, user_id=1, username="admin")
    assert res["success"] is True
    assert res["product_id"] == pid
    assert res["variant_count"] == 1
    assert res["unit_count"] == 1

    # Verify unit linked to correct variant and product
    unit_row = db.query_one("SELECT u.*, v.product_id FROM units u JOIN variants v ON u.variant_id = v.id WHERE u.imei1 = ?", (imei_v,))
    assert unit_row is not None
    assert unit_row["product_id"] == pid
    assert unit_row["status"] == "IN_STOCK"


def test_matrix_creation_and_variant_stock():
    db.init_db()
    ts = str(int(time.time() * 1000))[-8:]
    pid = inventory.create_product("Realme", f"Realme 12 Pro {ts}", category="Smartphone", item_type="PHONE", user_id=1, username="admin")

    # Fast 1-click matrix generate
    combos = [{"ram": "8GB", "storage": "128GB"}, {"ram": "12GB", "storage": "256GB"}]
    colors = ["Submarine Blue", "Navigator Beige"]
    created_ids = inventory.generate_variant_matrix(pid, combos, colors, default_retail=68000, default_wholesale=62000, user_id=1, username="admin")
    assert len(created_ids) == 4

    # Receive stock and IMEI on one of the matrix variants
    target_vid = created_ids[0]
    test_imei = f"86{ts}8899"
    stock_res = inventory.add_stock_to_variant(target_vid, cost_price=62000, imeis=[test_imei], user_id=1, username="admin")
    assert stock_res["success"] is True
    assert stock_res["units_added"] == 1

    # Check variant stock updated
    v = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (target_vid,))
    assert v["stock_quantity"] == 1

def test_matrix_repeated_run_no_sku_collision():
    db.init_db()
    ts = str(int(time.time() * 1000))[-8:]
    pid = inventory.create_product("Apple", f"iPhone 15 Test {ts}", category="Smartphone", item_type="PHONE", user_id=1, username="admin")
    combos = [{"ram": "6GB", "storage": "128GB"}]
    colors = ["Black"]

    # First run
    ids1 = inventory.generate_variant_matrix(pid, combos, colors, default_retail=200000, default_wholesale=185000, user_id=1, username="admin")
    assert len(ids1) == 1

    # Second run for SAME product and specs (MUST NOT crash with UNIQUE constraint on variants.sku)
    ids2 = inventory.generate_variant_matrix(pid, combos, colors, default_retail=205000, default_wholesale=190000, user_id=1, username="admin")
    assert len(ids2) == 1
    assert ids1[0] == ids2[0]

    # Verify price updated without duplicate row
    v = db.query_one("SELECT * FROM variants WHERE id = ?", (ids1[0],))
    assert v["retail_price"] == 205000
    assert v["wholesale_price"] == 190000

    # Third run for ANOTHER product whose name starts with same letters (test SKU uniqueness)
    pid2 = inventory.create_product("Apple", f"iPhone 15 Pro Test {ts}", category="Smartphone", item_type="PHONE", user_id=1, username="admin")
    ids3 = inventory.generate_variant_matrix(pid2, combos, colors, default_retail=250000, default_wholesale=230000, user_id=1, username="admin")
    assert len(ids3) == 1
    assert ids3[0] != ids1[0]

    v3 = db.query_one("SELECT * FROM variants WHERE id = ?", (ids3[0],))
    assert v3["sku"] != v["sku"]

def test_accessory_stock_creation_and_quick_add():
    db.init_db()
    ts = str(int(time.time() * 1000))[-8:]
    payload = {
        "item_type": "ACCESSORY",
        "brand": "Anker",
        "name": f"30W GaN Charger Test {ts}",
        "category": "Chargers",
        "retail_price": "3,500",
        "wholesale_price": "2,400",
        "stock_quantity": 25,
        "barcode": f"ANK-{ts}"
    }

    res = inventory.create_item_unified(payload, user_id=1, username="admin")
    assert res["success"] is True
    pid = res["product_id"]
    vid = res["variant_id"]

    # 1. Test get_variants_for_product returns units_in_stock == 25 (NOT 0!)
    variants = inventory.get_variants_for_product(pid)
    assert len(variants) == 1
    assert variants[0]["units_in_stock"] == 25
    assert variants[0]["stock_quantity"] == 25

    # 2. Add stock via add_stock_to_variant
    stock_res = inventory.add_stock_to_variant(vid, cost_price=2500, qty=15, user_id=1, username="admin")
    assert stock_res["success"] is True
    assert stock_res["units_added"] == 15

    # Verify updated stock count
    v_after = inventory.get_variants_for_product(pid)[0]
    assert v_after["units_in_stock"] == 40
    assert v_after["stock_quantity"] == 40

    # 3. Update accessory via update_item_unified
    upd_res = inventory.update_item_unified({
        "product_id": pid,
        "variant_id": vid,
        "brand": "Anker",
        "name": f"30W GaN Charger Test {ts}",
        "retail_price": 3800,
        "stock_quantity": 50
    }, user_id=1, username="admin")
    assert upd_res["success"] is True

    v_updated = inventory.get_variants_for_product(pid)[0]
    assert v_updated["retail_price"] == 3800
    assert v_updated["stock_quantity"] == 50
    assert v_updated["units_in_stock"] == 50

