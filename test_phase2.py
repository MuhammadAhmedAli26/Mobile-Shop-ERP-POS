# Phase 2 Verification Test Suite (Selling, POS, Returns, Trade-in)
import sys, os
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, scanner, inventory, pos, printing

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING PHASE 2 TEST SUITE (SELLING, RETURNS & TRADE-IN)")
    print("=" * 60)

    # 1. Setup Product, Variant and Unit
    pid = inventory.create_product("Apple", "iPhone 13", "Smartphone", "PHONE", 12, user_id=1, username="admin")
    vid = inventory.create_variant(pid, ram="4GB", storage="128GB", color="Midnight", retail_price=165000, wholesale_price=150000, user_id=1, username="admin")
    
    import random, time
    rand_prefix = f"35{int(time.time())%1000000:06d}{random.randint(1000, 9999):04d}"
    
    # Calculate valid Luhn IMEI
    d15_1 = scanner.calculate_luhn_digit(rand_prefix + "10")
    imei_1 = rand_prefix + "10" + d15_1
    
    d15_2 = scanner.calculate_luhn_digit(rand_prefix + "20")
    imei_2 = rand_prefix + "20" + d15_2

    u1 = inventory.add_unit(vid, imei_1, condition="NEW_BOX_PACK", cost_price=150000, user_id=1, username="admin")
    u2 = inventory.add_unit(vid, imei_2, condition="NEW_BOX_PACK", cost_price=150000, user_id=1, username="admin")
    assert u1["success"], f"u1 failed: {u1}"
    assert u2["success"], f"u2 failed: {u2}"
    u1_id = u1["unit_id"]
    u2_id = u2["unit_id"]
    print("✓ 1. Test Phones added with valid Luhn IMEIs.")

    # Also add an Accessory (Charger)
    acc_pid = inventory.create_product("Apple", f"20W USB-C Power Adapter {rand_prefix[:4]}", "Accessory", "ACCESSORY", 6, compatible_models="iPhone 13", user_id=1, username="admin")
    acc_vid = inventory.create_variant(acc_pid, color="White", retail_price=5500, wholesale_price=3500, stock_qty=20, barcode=f"APP-CHG-20W-{rand_prefix}", user_id=1, username="admin")
    print(f"✓ 2. Test Accessory added with barcode APP-CHG-20W-{rand_prefix}.")

    # 2. POS Checkout Phone + Accessory
    cart = [
        {"item_type": "PHONE", "variant_id": vid, "unit_id": u1_id, "item_name": "Apple iPhone 13", "unit_price": 165000, "qty": 1},
        {"item_type": "ACCESSORY", "variant_id": acc_vid, "item_name": "Apple 20W Power Adapter", "unit_price": 5500, "qty": 2}
    ]
    sale_res = pos.pos_checkout(cart, customer_name="Ali Khan", customer_phone="03001234567", paid_amount=176000, payment_method="CASH", user_id=1, username="admin")
    assert sale_res["success"], f"Checkout failed: {sale_res}"
    sale_id = sale_res["sale_id"]
    inv_no = sale_res["invoice_no"]
    assert sale_res["grand_total"] == (165000 + 5500 * 2)
    print(f"✓ 3. Mixed POS Checkout passed! Invoice: {inv_no}, Total: Rs. {sale_res['grand_total']:,.0f}")

    # Verify unit status is SOLD and accessory stock decremented
    u1_db = db.query_one("SELECT status FROM units WHERE id = ?", (u1_id,))
    assert u1_db["status"] == "SOLD", "Unit status was not set to SOLD!"
    acc_db = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (acc_vid,))
    assert acc_db["stock_quantity"] == 18, f"Expected 18 accessories, got {acc_db['stock_quantity']}"
    print("✓ 4. Unit status verified SOLD and accessory stock verified deducted.")

    # 3. Double Sale Prevention Test
    scan_guard = scanner.universal_scan_route(imei_1, context="POS")
    assert not scan_guard["success"], "Scanner failed to block already-sold IMEI!"
    assert scan_guard["type"] == "IMEI_ALREADY_SOLD"
    print(f"✓ 5. Guard check passed: Scanner instantly blocked already sold IMEI ({scan_guard['error']}).")

    # 4. Receipt Rendering Test
    rcpt_html = printing.render_sale_receipt(sale_id)
    assert inv_no in rcpt_html
    assert imei_1 in rcpt_html
    print("✓ 6. Thermal 80mm Sale Receipt rendered with IMEI 1 & WhatsApp link.")

    # 5. Return / Exchange Test
    items_in_sale = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
    phone_item = [x for x in items_in_sale if x["item_type"] == "PHONE"][0]
    ret_res = pos.process_return(sale_id, [{"sale_item_id": phone_item["id"], "qty": 1, "action": "RESTOCK"}], refund_type="CASH", reason="Customer changed mind", user_id=1, username="admin")
    assert ret_res["success"], f"Return failed: {ret_res}"
    # Verify unit status is back to IN_STOCK
    u1_ret = db.query_one("SELECT status FROM units WHERE id = ?", (u1_id,))
    assert u1_ret["status"] == "IN_STOCK", "Returned unit was not restored to IN_STOCK!"
    print(f"✓ 7. Return process passed: Unit #{u1_id} returned to IN_STOCK, refund Rs. {ret_res['refund_amount']:,.0f}.")

    # 6. Admin Sale Edit (Swap IMEI)
    # Re-sell u1 first
    resell = pos.pos_checkout([{"item_type": "PHONE", "variant_id": vid, "unit_id": u1_id, "item_name": "Apple iPhone 13", "unit_price": 165000, "qty": 1}], customer_name="Zahid", paid_amount=165000, user_id=1, username="admin")
    new_sale_id = resell["sale_id"]
    
    # Now Admin edits sale to swap IMEI 1 with IMEI 2
    edit_items = [{"item_type": "PHONE", "variant_id": vid, "unit_id": u2_id, "item_name": "Apple iPhone 13", "imei1": imei_2, "unit_price": 165000, "cost_price": 150000, "qty": 1}]
    swap_res = pos.admin_edit_sale(new_sale_id, edit_items, user_id=1, username="admin")
    assert swap_res["success"], f"Sale edit failed: {swap_res}"
    
    u1_chk = db.query_one("SELECT status FROM units WHERE id = ?", (u1_id,))
    u2_chk = db.query_one("SELECT status FROM units WHERE id = ?", (u2_id,))
    assert u1_chk["status"] == "IN_STOCK", "Original IMEI was not restored to IN_STOCK!"
    assert u2_chk["status"] == "SOLD", "Swapped IMEI was not marked SOLD!"
    print("✓ 8. Admin Sale Edit (IMEI Swap) passed: Old IMEI restored to IN_STOCK, new IMEI locked as SOLD.")

    # 7. Trade-in Buy-back Test
    d15_trade = scanner.calculate_luhn_digit(rand_prefix + "99")
    imei_trade = rand_prefix + "99" + d15_trade
    trd_res = pos.record_trade_in("Hamza", "03339876543", "35201-1234567-1", "Samsung", "Galaxy S21", imei_trade, condition="USED", battery_health=82, purchase_price=65000, user_id=1, username="admin")
    assert trd_res["success"], f"Trade-in failed: {trd_res}"
    trade_unit_id = trd_res["unit_id"]
    
    # Check unit entered inventory as USED with cost 65000
    u_trd = db.query_one("SELECT * FROM units WHERE id = ?", (trade_unit_id,))
    assert u_trd["condition"] == "USED" and u_trd["cost_price"] == 65000 and u_trd["status"] == "IN_STOCK"
    trd_slip = printing.render_trade_in_slip(trd_res["trade_in_id"])
    assert "Samsung Galaxy S21" in trd_slip and "65,000" in trd_slip
    print(f"✓ 9. Trade-in Buyback passed: Device entered inventory as USED, cost Rs. 65,000, voucher printed.")

    print("\n" + "=" * 60)
    print("🏆 ALL PHASE 2 TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
