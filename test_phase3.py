# Phase 3 Verification Test Suite (Purchasing, Suppliers, Udhaar, Installments)
import sys, os, time, random
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, scanner, inventory, pos, purchasing, credit, printing

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING PHASE 3 TEST SUITE (PURCHASING, SUPPLIERS & CREDIT)")
    print("=" * 60)

    # 1. Supplier Creation
    sid = purchasing.create_supplier("Hafeez Center Wholesale Hub", "03219876543", "Hafeez Center Basement #12, Lahore", company="Prime Telecom Traders", user_id=1, username="admin")
    sup = purchasing.get_supplier(sid)
    assert sup and sup["name"] == "Hafeez Center Wholesale Hub"
    print(f"✓ 1. Supplier created successfully (#{sid}: {sup['name']}).")

    # 2. Setup Phone Variant & Accessory Variant for Purchasing
    pid = inventory.create_product("Xiaomi", "Redmi Note 13", "Smartphone", "PHONE", 12, user_id=1, username="admin")
    vid = inventory.create_variant(pid, ram="8GB", storage="256GB", color="Ice Blue", retail_price=54999, wholesale_price=48000, user_id=1, username="admin")
    
    ts_s = str(int(time.time() * 1000))[-6:]
    acc_pid = inventory.create_product("Baseus", f"Fast Charging Cable Type-C {ts_s}", "Accessory", "ACCESSORY", 6, user_id=1, username="admin")
    acc_vid = inventory.create_variant(acc_pid, color="Black", retail_price=1200, wholesale_price=650, stock_qty=5, barcode=f"BAS-C-1M-{ts_s}", user_id=1, username="admin")

    # Generate 3 valid Luhn IMEIs
    rand_prefix = f"86{int(time.time())%1000000:06d}{random.randint(1000, 9999):04d}"
    imeis_to_receive = []
    for i in range(1, 4):
        stem = f"{rand_prefix}{i:02d}"
        d15 = scanner.calculate_luhn_digit(stem)
        imeis_to_receive.append({"imei1": stem + d15, "condition": "NEW_BOX_PACK", "pta_status": "PTA_APPROVED", "battery_health": 100})

    # 3. Create Purchase (Bulk Receiving 3 Phones + 20 Cables)
    items = [
        {"item_type": "PHONE", "variant_id": vid, "unit_cost": 48000, "imeis": imeis_to_receive},
        {"item_type": "ACCESSORY", "variant_id": acc_vid, "unit_cost": 650, "qty": 20}
    ]
    # Total = (48000 * 3) + (650 * 20) = 144,000 + 13,000 = 157,000
    # Paid = 100,000, Balance due = 57,000
    pur_res = purchasing.create_purchase(sid, items, invoice_no="", paid_amount=100000, payment_method="BANK_TRANSFER", user_id=1, username="admin")
    assert pur_res["success"], f"Purchase failed: {pur_res}"
    pur_id = pur_res["purchase_id"]
    inv_no = pur_res["invoice_no"]
    assert pur_res["total_amount"] == 157000
    assert pur_res["balance_due"] == 57000
    print(f"✓ 2. Purchase receiving passed! Bill: {inv_no}, Total: Rs. {pur_res['total_amount']:,.0f}, Paid: Rs. {pur_res['paid_amount']:,.0f}.")

    # 4. Verify Units & Accessory Stock
    u_count = db.query_one("SELECT COUNT(*) AS c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (vid,))
    assert u_count["c"] == 3, f"Expected 3 units, found {u_count['c']}"
    acc_stk = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (acc_vid,))
    assert acc_stk["stock_quantity"] == 25, f"Expected 25 (5 + 20), found {acc_stk['stock_quantity']}"
    print("✓ 3. Verified 3 Phone units added to stock with IMEIs, and accessory stock incremented to 25.")

    # 5. Duplicate IMEI Guard in Purchase
    dup_res = purchasing.create_purchase(sid, [{"item_type": "PHONE", "variant_id": vid, "unit_cost": 48000, "imeis": [imeis_to_receive[0]]}], user_id=1, username="admin")
    assert not dup_res["success"], "Purchase failed to block duplicate IMEI!"
    print(f"✓ 4. Guard check passed: Duplicate IMEI in receiving blocked: '{dup_res['error']}'.")

    # 6. Supplier Ledger & Payment
    ledg = purchasing.get_supplier_ledger(sid)
    assert len(ledg["transactions"]) >= 2 # Purchase debit + initial payment credit
    assert ledg["supplier"]["balance"] == 57000
    print(f"✓ 5. Supplier ledger verified: Outstanding balance is Rs. {ledg['supplier']['balance']:,.0f}.")

    pay_res = purchasing.record_supplier_payment(sid, 57000, payment_method="CASH", reference="PAY-CLEAR-01", notes="Cleared balance", user_id=1, username="admin")
    assert pay_res["success"] and pay_res["new_balance"] == 0
    print("✓ 6. Supplier balance paid in full (Balance now Rs. 0).")
    sup_rcpt = printing.render_supplier_payment_receipt(pay_res["ledger_id"])
    assert "SUPPLIER PAYMENT VOUCHER" in sup_rcpt and "57,000" in sup_rcpt
    print("✓ 7. Supplier payment voucher HTML generated.")

    # 7. Customer & Udhaar Credit Testing
    test_phone = f"030{random.randint(10000000, 99999999)}"
    cid = credit.create_customer("Muhammad Usman", test_phone, cnic="35202-9876543-1", address="Model Town, Lahore", user_id=1, username="admin")
    cust = credit.get_customer(cid)
    assert cust and cust["name"] == "Muhammad Usman"
    print(f"✓ 8. Customer created (#{cid}: {cust['name']}).")

    # Record credit sale of Rs. 20,000
    cred_res = credit.record_udhaar_sale(cid, sale_id=0, credit_amount=20000, notes="Unpaid accessories balance", user_id=1, username="admin")
    assert cred_res["success"] and cred_res["new_balance"] == 20000
    print("✓ 9. Udhaar credit of Rs. 20,000 charged to customer.")

    # Record partial Udhaar payment of Rs. 8,000
    ud_pay = credit.record_udhaar_payment(cid, 8000, payment_method="EASYPAISA", notes="Online transfer", user_id=1, username="admin")
    assert ud_pay["success"] and ud_pay["new_balance"] == 12000
    print("✓ 10. Customer paid Rs. 8,000 via EasyPaisa (Balance remaining: Rs. 12,000).")

    # 8. Installment Financing Plan Testing
    # Phone price: 60,000, Down payment: 15,000, 3 months, 5% monthly markup
    u_for_inst = db.query_one("SELECT * FROM units WHERE variant_id = ? AND status = 'IN_STOCK' LIMIT 1", (vid,))
    pos_inst = pos.pos_checkout(
        [{"item_type": "PHONE", "variant_id": vid, "unit_id": u_for_inst["id"], "item_name": "Xiaomi Redmi Note 13", "unit_price": 60000, "qty": 1}],
        customer_name="Muhammad Usman", customer_phone=test_phone,
        paid_amount=15000, payment_method="INSTALLMENT", user_id=1, username="admin"
    )
    inst_sale_id = pos_inst["sale_id"]

    g1 = {"name": "Tariq Mehmood", "phone": "03331122334", "cnic": "35201-1122334-1"}
    g2 = {"name": "Naveed Akhtar", "phone": "03454455667", "cnic": "35201-4455667-3"}
    plan_res = credit.create_installment_plan(sale_id=inst_sale_id, customer_id=cid, total_price=60000, down_payment=15000, total_months=3, monthly_markup_percent=5, guarantor1=g1, guarantor2=g2, user_id=1, username="admin")
    assert plan_res["success"], f"Installment plan failed: {plan_res}"
    inst_id = plan_res["installment_id"]
    assert len(plan_res["schedule"]) == 3
    # financed = 45,000. 5% * 3 = 15% markup = 6,750. Total payable = 51,750. Monthly = 17,250.
    assert plan_res["total_payable"] == 51750
    assert plan_res["monthly_due"] == 17250
    print(f"✓ 11. 3-Month Installment Plan created! Monthly due: Rs. {plan_res['monthly_due']:,.0f}, Total Payable: Rs. {plan_res['total_payable']:,.0f}.")

    # Collect 1st installment payment
    first_sch_id = plan_res["schedule"][0]["schedule_id"]
    pay_inst_res = credit.pay_installment(first_sch_id, 17250, payment_method="CASH", user_id=1, username="admin")
    assert pay_inst_res["success"] and pay_inst_res["status"] == "PAID"
    print(f"✓ 12. Month #1 installment paid! Receipt: {pay_inst_res['receipt_no']}.")

    # 9. Verify Print Agreements & Receipts
    contract_html = printing.render_installment_contract(inst_id)
    assert "EASY INSTALLMENT CONTRACT" in contract_html
    assert "Tariq Mehmood" in contract_html and "Naveed Akhtar" in contract_html
    print("✓ 13. Installment financing contract rendered with Pakistani Guarantors.")

    inst_rcpt_html = printing.render_installment_payment_receipt(first_sch_id)
    assert "INSTALLMENT PAYMENT RECEIPT" in inst_rcpt_html
    print("✓ 14. Thermal 80mm installment collection receipt rendered.")

    print("\n" + "=" * 60)
    print("🏆 ALL PHASE 3 TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
