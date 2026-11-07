# MOBILE & ACCESSORIES ERP — Comprehensive Realistic Demo Data Seeder (Pakistan Edition)
import sys, os, time, random
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db, scanner, inventory, pos, purchasing, credit, services, accounting

def seed():
    print("=" * 65)
    print("🚀 SEEDING REALISTIC PAKISTANI MOBILE & ACCESSORIES DATA")
    print("=" * 65)

    db.init_db()

    # 1. Suppliers in major Pakistani wholesale hubs
    suppliers_data = [
        ("Hafeez Center Wholesale Hub", "0321-9876543", "Hall 2, Basement, Hafeez Center, Lahore", "Prime Mobile Distribution"),
        ("Hall Road Spares & Parts Co.", "0300-8451234", "Shop # 18, Hall Road, Lahore", "Al-Madina Parts Ltd"),
        ("Karachi Saddar Mobile Imports", "0333-7654321", "Star City Mall, Saddar, Karachi", "VIP Cellular Traders")
    ]
    sup_ids = []
    for name, phone, addr, comp in suppliers_data:
        existing = db.query_one("SELECT id FROM suppliers WHERE name = ?", (name,))
        if existing:
            sup_ids.append(existing["id"])
        else:
            sid = purchasing.create_supplier(name, phone=phone, address=addr, company=comp, user_id=1, username="admin")
            sup_ids.append(sid)
    print(f"✓ 1. Seeded {len(sup_ids)} Wholesale Suppliers (Hafeez Center, Hall Road, Saddar Karachi).")

    # 2. Phone Models & Variant Matrix
    phone_models = [
        {
            "brand": "Samsung", "name": "Galaxy A15", "cat": "Smartphone",
            "combos": [{"ram": "4GB", "storage": "128GB"}, {"ram": "6GB", "storage": "128GB"}, {"ram": "8GB", "storage": "256GB"}],
            "colors": ["Blue Black", "Light Blue", "Yellow"],
            "retail": 52999, "wholesale": 47500
        },
        {
            "brand": "Samsung", "name": "Galaxy S24 Ultra", "cat": "Flagship",
            "combos": [{"ram": "12GB", "storage": "256GB"}, {"ram": "12GB", "storage": "512GB"}],
            "colors": ["Titanium Gray", "Titanium Black", "Titanium Violet"],
            "retail": 415000, "wholesale": 385000
        },
        {
            "brand": "Apple", "name": "iPhone 13", "cat": "Smartphone",
            "combos": [{"ram": "4GB", "storage": "128GB"}, {"ram": "4GB", "storage": "256GB"}],
            "colors": ["Midnight", "Starlight", "Blue", "Pink"],
            "retail": 172000, "wholesale": 156000
        },
        {
            "brand": "Apple", "name": "iPhone 15 Pro Max", "cat": "Flagship",
            "combos": [{"ram": "8GB", "storage": "256GB"}, {"ram": "8GB", "storage": "512GB"}],
            "colors": ["Natural Titanium", "Blue Titanium", "White Titanium"],
            "retail": 520000, "wholesale": 485000
        },
        {
            "brand": "Xiaomi", "name": "Redmi Note 13", "cat": "Mid-range",
            "combos": [{"ram": "6GB", "storage": "128GB"}, {"ram": "8GB", "storage": "256GB"}],
            "colors": ["Midnight Black", "Mint Green", "Ice Blue"],
            "retail": 54999, "wholesale": 49000
        },
        {
            "brand": "Infinix", "name": "Hot 40 Pro", "cat": "Budget",
            "combos": [{"ram": "8GB", "storage": "128GB"}, {"ram": "8GB", "storage": "256GB"}],
            "colors": ["Palm Blue", "Horizon Gold", "Starlit Black"],
            "retail": 45999, "wholesale": 40500
        },
        {
            "brand": "Tecno", "name": "Spark 20 Pro", "cat": "Budget",
            "combos": [{"ram": "8GB", "storage": "256GB"}],
            "colors": ["Moonlit Black", "Frosty Ivory", "Sunset Blush"],
            "retail": 42999, "wholesale": 38000
        }
    ]

    unit_count = 0
    rand_base = int(time.time()) % 100000
    for m in phone_models:
        pid = inventory.create_product(m["brand"], m["name"], category=m["cat"], item_type="PHONE", user_id=1, username="admin")
        vids = inventory.generate_variant_matrix(pid, m["combos"], m["colors"], m["retail"], m["wholesale"], user_id=1, username="admin")
        
        # Add 2-3 phone units with valid Luhn IMEIs to the first 2 variants
        for vid in vids[:2]:
            for u_idx in range(2):
                stem = f"35{rand_base:05d}{random.randint(1000000, 9999999):07d}"
                d15_1 = scanner.calculate_luhn_digit(stem)
                imei1 = stem + d15_1

                stem2 = f"35{rand_base:05d}{random.randint(1000000, 9999999):07d}"
                d15_2 = scanner.calculate_luhn_digit(stem2)
                imei2 = stem2 + d15_2

                cond = random.choice(["NEW_BOX_PACK", "NEW_BOX_PACK", "OPEN_BOX", "USED"])
                pta = random.choice(["PTA_APPROVED", "PTA_APPROVED", "NON_PTA", "JV"])
                bhealth = random.randint(85, 100) if cond == "USED" else 100

                res = inventory.add_unit(vid, imei1, imei2=imei2, condition=cond, pta_status=pta, cost_price=m["wholesale"], supplier_id=sup_ids[0], purchase_ref="OPENING-STOCK", battery_health=bhealth, user_id=1, username="admin")
                if res["success"]:
                    unit_count += 1

    print(f"✓ 2. Seeded 7 Popular Phone Models with Full Matrix & {unit_count} Verified IMEI Units.")

    # 3. Accessories & Spare Parts
    accessories_data = [
        ("Apple", "20W USB-C Power Adapter", "ACCESSORY", "White", 5500, 3500, 35, "APP-20W-CHG"),
        ("Samsung", "25W Super Fast Travel Adapter", "ACCESSORY", "Black", 4500, 2800, 40, "SAM-25W-CHG"),
        ("Baseus", "Tungsten Gold 65W Fast Cable Type-C", "ACCESSORY", "Black", 1400, 850, 60, "BAS-C-65W"),
        ("Remax", "10000mAh Power Bank Fast Charge", "ACCESSORY", "White", 4200, 2600, 25, "REM-PB-10K"),
        ("Audionic", "Airbud 550 TWS Earbuds", "ACCESSORY", "Black", 4800, 3200, 20, "AUD-AIR-550"),
        ("Ronin", "R-007 Super Bass Handsfree", "ACCESSORY", "White", 850, 420, 80, "RON-HF-007"),
        ("Generic", "9D King Kong Tempered Glass (iPhone 13/14)", "ACCESSORY", "Clear", 450, 120, 150, "GLS-IP13-9D"),
        ("Generic", "Matte Silicon Camera Protection Cover", "ACCESSORY", "Smoke", 650, 200, 120, "COV-SAM-A15"),
        ("GX", "iPhone 13 OLED Screen Assembly", "SPARE_PART", "Black", 18500, 13000, 8, "GX-IP13-LCD"),
        ("Samsung", "A15 Original Battery 5000mAh", "SPARE_PART", "Silver", 3500, 2100, 12, "SAM-A15-BAT"),
        ("Generic", "Universal Type-C Charging Flex Port", "SPARE_PART", "Standard", 1200, 400, 25, "PRT-TYPEC-FLEX")
    ]

    for brand, name, itype, color, rp, wp, qty, code in accessories_data:
        pid = inventory.create_product(brand, name, category=itype, item_type=itype, user_id=1, username="admin")
        inventory.create_variant(pid, color=color, retail_price=rp, wholesale_price=wp, stock_qty=qty, barcode=code, user_id=1, username="admin")

    print(f"✓ 3. Seeded {len(accessories_data)} Fast-Moving Accessories & Hardware Spare Parts.")

    # 4. Customers & Udhaar
    cust_data = [
        ("Chaudhry Nadeem", "0300-4567890", "35201-4567890-1", "DHA Phase 5, Lahore"),
        ("Malik Shahbaz", "0321-1122334", "35202-1122334-3", "Gulberg III, Lahore"),
        ("Sheikh Farhan", "0333-8899001", "35201-8899001-5", "Johar Town, Lahore")
    ]
    cust_ids = []
    for name, phone, cnic, addr in cust_data:
        cid = credit.create_customer(name, phone, cnic=cnic, address=addr, user_id=1, username="admin")
        cust_ids.append(cid)

    # Give one customer an Udhaar balance
    credit.record_udhaar_sale(cust_ids[0], sale_id=0, credit_amount=15000, notes="Unpaid chargers & covers balance", user_id=1, username="admin")
    print(f"✓ 4. Seeded Customer Profiles & Udhaar Ledger.")

    # 5. Hardware Repairs
    rep1 = services.create_repair_job(
        customer_name="Rana Zubair", customer_phone="0301-7788990",
        brand="Apple", model="iPhone 13", complaint="Screen shattered, touch not responding",
        imei="352990184758392", estimate=19500, advance_paid=5000, expected_delivery="Today 7 PM",
        technician_name="Master Ustad", user_id=1, username="admin"
    )
    services.update_repair_status(rep1["repair_id"], "IN_REPAIR", user_id=1, username="admin")

    rep2 = services.create_repair_job(
        customer_name="Adeel Munir", customer_phone="0345-6677889",
        brand="Samsung", model="Galaxy A15", complaint="Battery draining fast, phone overheating",
        imei="358810293847561", estimate=4500, advance_paid=1000, expected_delivery="Tomorrow",
        technician_name="Ali Tech", user_id=1, username="admin"
    )
    services.update_repair_status(rep2["repair_id"], "WAITING_PARTS", user_id=1, username="admin")
    print("✓ 5. Seeded Hardware Repair Workshop Jobs (iPhone 13 Screen, Samsung A15 Battery).")

    # 6. Software Services
    services.create_software_job("Infinix Hot 40", service_id=1, price_charged=1500, tool_server_cost=200, customer_name="Taimoor", customer_phone="0322-9988776", imei="351928374650192", user_id=1, username="admin")
    services.create_software_job("Samsung A15", service_id=2, price_charged=2200, tool_server_cost=500, customer_name="Waqas", customer_phone="0300-3344556", imei="359988776655443", user_id=1, username="admin")
    print("✓ 6. Seeded Software Lab Services (Flashing & FRP Bypass).")

    # 7. Quick Services (EasyPaisa & Load)
    services.record_quick_service("EASYPAISA", amount=35000, fee_commission=210, customer_phone="0345-1234567", notes="Cash out for client", user_id=1, username="admin")
    services.record_quick_service("LOAD", amount=1000, fee_commission=50, network="Jazz", customer_phone="0300-7654321", user_id=1, username="admin")
    print("✓ 7. Seeded Quick Services Earnings (EasyPaisa Cash-Out & Mobile Load).")

    # 8. Business Expenses
    accounting.record_expense("Shop Rent", 50000, "Hafeez Center Shop #15 Rent", payment_method="CASH", user_id=1, username="admin")
    accounting.record_expense("Electricity / Generator / Fuel", 15000, "Diesel for backup generator", payment_method="CASH", user_id=1, username="admin")
    accounting.record_expense("Tea / Food", 2500, "Counter refreshments for clients & staff", payment_method="CASH", user_id=1, username="admin")
    print("✓ 8. Seeded Shop Operating Expenses.")

    print("\n" + "=" * 65)
    print("🏆 DEMO DATA SEEDED 100% SUCCESSFULLY WITH PAKISTANI MARKET ACCURACY!")
    print("=" * 65)

if __name__ == "__main__":
    seed()
