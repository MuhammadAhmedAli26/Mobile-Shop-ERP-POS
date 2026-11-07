# MOBILE & ACCESSORIES ERP — Scanner Engine & Universal Scan Router
import re
import db

def luhn_checksum_valid(imei_str):
    """Verifies 15-digit IMEI using standard Luhn (mod 10) algorithm."""
    imei_str = str(imei_str).strip()
    if not re.match(r"^\d{14,16}$", imei_str):
        return False, "IMEI must be 14-16 digits"
    if len(imei_str) != 15:
        return False, f"Standard IMEI is 15 digits (received {len(imei_str)})"
    
    digits = [int(d) for d in imei_str]
    total = 0
    for i, d in enumerate(digits[:-1]):
        if i % 2 == 1:
            doubled = d * 2
            total += (doubled // 10) + (doubled % 10)
        else:
            total += d
    check_digit = (10 - (total % 10)) % 10
    if check_digit == digits[-1]:
        return True, "Valid Luhn IMEI"
    else:
        return False, f"Checksum mismatch (expected {check_digit}, got {digits[-1]})"

def calculate_luhn_digit(first_14_digits):
    """Calculates the 15th Luhn check digit given the first 14 digits."""
    digits = [int(d) for d in str(first_14_digits).strip()[:14]]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            doubled = d * 2
            total += (doubled // 10) + (doubled % 10)
        else:
            total += d
    return str((10 - (total % 10)) % 10)

def detect_code_type(code):
    """Detects whether raw scan input is an IMEI, Barcode, Invoice, or Service Ticket."""
    code = str(code).strip()
    if not code:
        return "EMPTY"
    
    if code.startswith("INV-"):
        return "INVOICE"
    elif code.startswith("REP-"):
        return "REPAIR_TICKET"
    elif code.startswith("SFT-"):
        return "SOFTWARE_TICKET"
    elif re.match(r"^\d{14,16}$", code):
        return "IMEI"
    else:
        return "BARCODE_OR_SKU"

def universal_scan_route(raw_code, context="POS"):
    """
    Universal scan router: inspects code and returns contextual payload.
    Speed: Executes via SQLite indexes in < 15ms.
    """
    code = str(raw_code).strip()
    code_type = detect_code_type(code)
    
    if code_type == "EMPTY":
        return {"success": False, "type": "EMPTY", "error": "No code provided"}
    
    # 1. IMEI Scan
    if code_type == "IMEI":
        is_luhn, luhn_msg = luhn_checksum_valid(code)
        
        # Look up by IMEI 1 or IMEI 2
        sql = """
            SELECT u.*, u.id AS unit_id,
                   v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price, v.min_selling_price, v.sku,
                   p.id AS product_id, p.brand, p.name AS model_name, p.category, p.item_type, p.default_warranty_months
            FROM units u
            JOIN variants v ON u.variant_id = v.id
            JOIN products p ON v.product_id = p.id
            WHERE u.imei1 = ? OR u.imei2 = ?
            LIMIT 1
        """
        unit = db.query_one(sql, (code, code))
        
        if not unit:
            return {
                "success": False,
                "type": "IMEI_NOT_FOUND",
                "code": code,
                "is_luhn": is_luhn,
                "luhn_msg": luhn_msg,
                "error": f"IMEI {code} is not registered in system."
            }
        
        # Guard checking based on context
        if context == "POS":
            if unit["status"] == "SOLD":
                # Find sale info
                last_sale = db.query_one("""
                    SELECT s.invoice_no, s.customer_name, s.created_at, si.unit_price
                    FROM sale_items si
                    JOIN sales s ON si.sale_id = s.id
                    WHERE si.unit_id = ?
                    ORDER BY si.id DESC LIMIT 1
                """, (unit["id"],))
                inv_text = f" (Invoice #{last_sale['invoice_no']} to {last_sale['customer_name']})" if last_sale else ""
                return {
                    "success": False,
                    "type": "IMEI_ALREADY_SOLD",
                    "unit": unit,
                    "error": f"🚫 Device with IMEI {code} is ALREADY SOLD{inv_text}!"
                }
            elif unit["status"] == "IN_REPAIR":
                return {
                    "success": False,
                    "type": "IMEI_IN_REPAIR",
                    "unit": unit,
                    "error": f"⚠️ Device with IMEI {code} is currently IN REPAIR!"
                }
            elif unit["status"] == "DEFECTIVE":
                return {
                    "success": False,
                    "type": "IMEI_DEFECTIVE",
                    "unit": unit,
                    "error": f"⚠️ Device with IMEI {code} is marked DEFECTIVE!"
                }
            elif unit["status"] == "RETURNED_TO_SUPPLIER":
                return {
                    "success": False,
                    "type": "IMEI_RETURNED_TO_SUPPLIER",
                    "unit": unit,
                    "error": f"⚠️ Device with IMEI {code} has been RETURNED TO SUPPLIER!"
                }
        
        return {
            "success": True,
            "type": "UNIT_FOUND",
            "unit": unit,
            "is_luhn": is_luhn,
            "luhn_msg": luhn_msg
        }

    # 2. Accessory Barcode / SKU Scan
    elif code_type == "BARCODE_OR_SKU":
        sql = """
            SELECT v.*, p.id AS product_id, p.brand, p.name AS model_name, p.category, p.item_type, p.compatible_models
            FROM variants v
            JOIN products p ON v.product_id = p.id
            WHERE (v.barcode = ? OR v.sku = ?) AND v.is_archived = 0
            LIMIT 1
        """
        variant = db.query_one(sql, (code, code))
        if variant:
            if context == "POS" and variant["stock_quantity"] <= 0:
                return {
                    "success": False,
                    "type": "ACCESSORY_OUT_OF_STOCK",
                    "variant": variant,
                    "error": f"⚠️ {variant['brand']} {variant['model_name']} is OUT OF STOCK (Qty: 0)!"
                }
            return {
                "success": True,
                "type": "ACCESSORY_FOUND",
                "variant": variant
            }
        else:
            if context == "POS":
                import search
                search_matches = search.search_products_and_units(code, limit=10)
                if search_matches:
                    first_m = search_matches[0]
                    if first_m.get("item_type") == "ACCESSORY" and first_m.get("in_stock_count", 0) > 0:
                        v_row = db.query_one("""
                            SELECT v.*, p.id AS product_id, p.brand, p.name AS model_name, p.category, p.item_type
                            FROM variants v JOIN products p ON v.product_id = p.id
                            WHERE v.id = ?
                        """, (first_m["variant_id"],))
                        if v_row:
                            return {
                                "success": True,
                                "type": "ACCESSORY_FOUND",
                                "variant": v_row,
                                "matches": search_matches
                            }
                    elif first_m.get("item_type") == "PHONE":
                        in_stock_unit = db.query_one("""
                            SELECT u.*, v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price, v.sku,
                                   p.id AS product_id, p.brand, p.name AS model_name, p.category, p.item_type
                            FROM units u
                            JOIN variants v ON u.variant_id = v.id
                            JOIN products p ON v.product_id = p.id
                            WHERE v.id = ? AND u.status = 'IN_STOCK'
                            ORDER BY u.id ASC LIMIT 1
                        """, (first_m["variant_id"],))
                        if in_stock_unit:
                            return {
                                "success": True,
                                "type": "UNIT_FOUND",
                                "unit": in_stock_unit,
                                "matches": search_matches
                            }
                    return {
                        "success": True,
                        "type": "SEARCH_MATCHES",
                        "items": search_matches,
                        "query": code
                    }

            return {
                "success": False,
                "type": "CODE_NOT_FOUND",
                "code": code,
                "error": f"Barcode/SKU '{code}' not found."
            }

    # 3. Invoice Barcode Scan (e.g. INV-20261011-1001)
    elif code_type == "INVOICE":
        sale = db.query_one("SELECT * FROM sales WHERE invoice_no = ?", (code,))
        if sale:
            items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale["id"],))
            return {
                "success": True,
                "type": "INVOICE_FOUND",
                "sale": sale,
                "items": items
            }
        return {"success": False, "type": "INVOICE_NOT_FOUND", "code": code, "error": f"Invoice {code} not found."}

    # 4. Repair Ticket Scan (e.g. REP-1001)
    elif code_type == "REPAIR_TICKET":
        job = db.query_one("SELECT * FROM repair_jobs WHERE job_no = ?", (code,))
        if job:
            return {"success": True, "type": "REPAIR_FOUND", "job": job}
        return {"success": False, "type": "REPAIR_NOT_FOUND", "code": code, "error": f"Repair ticket {code} not found."}

    # 5. Software Ticket Scan (e.g. SFT-1001)
    elif code_type == "SOFTWARE_TICKET":
        job = db.query_one("SELECT * FROM software_jobs WHERE ticket_no = ?", (code,))
        if job:
            return {"success": True, "type": "SOFTWARE_FOUND", "job": job}
        return {"success": False, "type": "SOFTWARE_NOT_FOUND", "code": code, "error": f"Software ticket {code} not found."}

    return {"success": False, "type": "UNKNOWN", "code": code, "error": f"Unknown barcode format: {code}"}

def get_imei_lifecycle(imei_code):
    imei_clean = str(imei_code).strip()
    tail = imei_clean[-6:] if len(imei_clean) >= 6 else imei_clean
    sql = """
        SELECT u.*, 
               v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price,
               p.brand, p.name AS model_name, p.category,
               sup.name AS supplier_name
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        LEFT JOIN suppliers sup ON u.supplier_id = sup.id
        WHERE u.imei1 = ? OR u.imei2 = ? OR u.imei1_tail = ? OR u.imei2_tail = ?
           OR (length(?) >= 4 AND (u.imei1_tail LIKE ? OR u.imei1 LIKE ?))
        LIMIT 1
    """
    unit = db.query_one(sql, (imei_clean, imei_clean, tail, tail, imei_clean, f"%{imei_clean}", f"%{imei_clean}"))
    if not unit:
        return {"success": False, "error": f"No unit found with IMEI {imei_code}"}

    # Sale info if sold
    sale_item = db.query_one("""
        SELECT si.*, s.customer_name, s.customer_phone, s.invoice_no, s.created_at AS sale_date, s.payment_method
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE si.unit_id = ? OR si.imei1 = ?
        ORDER BY si.id DESC LIMIT 1
    """, (unit["id"], unit["imei1"]))

    # Repairs info if any
    repairs = db.query_all("""
        SELECT id, job_no, complaint, status, total_charged, created_at
        FROM repair_jobs
        WHERE imei = ? OR imei = ?
        ORDER BY id DESC
    """, (unit["imei1"], unit.get("imei2") or ""))

    return {
        "success": True,
        "lifecycle": {
            "unit": unit,
            "sale": sale_item,
            "repairs": repairs
        }
    }
