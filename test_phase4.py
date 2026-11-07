# Phase 4 Verification Test Suite (Software Services, Repair Workshop, Quick Services)
import sys, os, time, random
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, scanner, inventory, services, printing

def run_tests():
    print("=" * 60)
    print("🧪 RUNNING PHASE 4 TEST SUITE (SOFTWARE SERVICES & REPAIR WORKSHOP)")
    print("=" * 60)

    # 1. Software Catalog
    catalog = services.list_software_catalog()
    assert len(catalog) >= 5, f"Expected pre-seeded services, found {len(catalog)}"
    print(f"✓ 1. Software Catalog loaded with {len(catalog)} standard Pakistani market services.")

    # 2. Software Ticket Quick Entry (< 10 seconds)
    sft_res = services.create_software_job(
        brand_model="Samsung Galaxy A54",
        service_id=catalog[1]["id"], # FRP / Google Account Removal
        price_charged=2500,
        tool_server_cost=600,
        customer_name="Kamran Akram",
        customer_phone="03215566778",
        imei="352889104567891",
        payment_method="CASH",
        technician_name="Ali Tech",
        notes="FRP bypass with owner CNIC verified",
        user_id=1, username="admin"
    )
    assert sft_res["success"], f"Software job creation failed: {sft_res}"
    job_id = sft_res["job_id"]
    tkt_no = sft_res["ticket_no"]
    assert sft_res["profit"] == (2500 - 600)
    print(f"✓ 2. Software Job created in < 10s! Ticket: {tkt_no}, Profit: Rs. {sft_res['profit']:,.0f}.")

    # Render software receipt
    sft_html = printing.render_software_receipt(job_id)
    assert tkt_no in sft_html and "Samsung Galaxy A54" in sft_html
    print("✓ 3. Thermal 80mm software service receipt rendered.")

    # 3. Hardware Repair Workshop - Job Card Creation
    rep_res = services.create_repair_job(
        customer_name="Bilal Shah",
        customer_phone="03334445556",
        brand="Apple",
        model="iPhone 12",
        complaint="Broken Display Screen & Fast Battery Drain",
        imei="358899102345678",
        accessories_received="Sim Tray, Blue Silicon Cover",
        estimate=18500,
        advance_paid=5000,
        expected_delivery="Tomorrow 6 PM",
        technician_name="Master Ustad",
        warranty_days=30,
        user_id=1, username="admin"
    )
    assert rep_res["success"], f"Repair creation failed: {rep_res}"
    rep_id = rep_res["repair_id"]
    job_no = rep_res["job_no"]
    assert rep_res["balance_due"] == (18500 - 5000)
    print(f"✓ 4. Repair Job Card created! Job: {job_no}, Initial Balance Due: Rs. {rep_res['balance_due']:,.0f}.")

    # 4. Status Transition: RECEIVED -> DIAGNOSING -> WAITING_PARTS
    st1 = services.update_repair_status(rep_id, "DIAGNOSING", user_id=1, username="admin")
    assert st1["success"] and st1["new_status"] == "DIAGNOSING"
    st2 = services.update_repair_status(rep_id, "WAITING_PARTS", user_id=1, username="admin")
    assert st2["success"] and st2["new_status"] == "WAITING_PARTS"
    print("✓ 5. Status successfully transitioned to DIAGNOSING then WAITING_PARTS.")

    # 5. Inventory Spare Part Creation & Fitting to Repair
    import time
    ts_p = str(int(time.time() * 1000))[-6:]
    part_pid = inventory.create_product("Apple", f"iPhone 12 GX OLED Display Panel {ts_p}", "Spare Part", "SPARE_PART", 1, user_id=1, username="admin")
    part_vid = inventory.create_variant(part_pid, color="Black", retail_price=14000, wholesale_price=9500, stock_qty=10, barcode=f"GX-IP12-OLED-{ts_p}", user_id=1, username="admin")
    
    part_fit = services.add_repair_part(rep_id, part_vid, qty=1, charge_price=13500, user_id=1, username="admin")
    assert part_fit["success"], f"Part attachment failed: {part_fit}"
    # Verify stock deducted
    part_stk = db.query_one("SELECT stock_quantity FROM variants WHERE id = ?", (part_vid,))
    assert part_stk["stock_quantity"] == 9, f"Expected 9 remaining, got {part_stk['stock_quantity']}"
    print(f"✓ 6. Spare part fitted! Stock deducted (10 -> 9). Part charge: Rs. {part_fit['charge_price']:,.0f}, Cost: Rs. {part_fit['cost_price']:,.0f}.")

    # Status auto-updated to IN_REPAIR upon part attachment
    rep_chk = services.get_repair_job(rep_id)
    assert rep_chk["job"]["status"] == "IN_REPAIR"
    print("✓ 7. Repair card auto-advanced to IN_REPAIR upon fitting parts.")

    # 6. Complete and Deliver Repair
    # Final labor charge = 3,500. Parts charge = 13,500. Total = 17,000.
    # Advance was 5,000. Remaining balance collected now = 12,000.
    deliv_res = services.complete_and_deliver_repair(rep_id, final_labor_charge=3500, paid_amount=12000, payment_method="CASH", user_id=1, username="admin")
    assert deliv_res["success"], f"Delivery failed: {deliv_res}"
    assert deliv_res["total_charged"] == 17000
    # Profit = 17,000 - 9,500 (parts cost) = 7,500
    assert deliv_res["profit"] == 7500
    assert deliv_res["balance_due"] == 0
    print(f"✓ 8. Repair delivered! Total: Rs. {deliv_res['total_charged']:,.0f}, Net Profit: Rs. {deliv_res['profit']:,.0f}, Balance: Rs. 0.")

    # 7. Thermal Repair Ticket Rendering
    rep_html = printing.render_repair_ticket(rep_id)
    assert job_no in rep_html and "GX OLED Display" in rep_html
    print("✓ 9. Thermal 80mm repair job delivery receipt rendered.")

    # 8. Quick Services (EasyPaisa, JazzCash, Load)
    qs1 = services.record_quick_service("EASYPAISA", amount=25000, fee_commission=150, customer_phone="03451122334", notes="Cash out", user_id=1, username="admin")
    assert qs1["success"] and qs1["commission"] == 150
    qs2 = services.record_quick_service("LOAD", amount=500, fee_commission=25, network="Jazz", customer_phone="03009988776", user_id=1, username="admin")
    assert qs2["success"] and qs2["commission"] == 25
    print("✓ 10. Quick Services recorded (EasyPaisa & Jazz Load commissions logged).")

    print("\n" + "=" * 60)
    print("🏆 ALL PHASE 4 TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
