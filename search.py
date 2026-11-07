# MOBILE & ACCESSORIES ERP — Universal Multi-Word & Normalized Search Engine
import re
import db

URDU_ARABIC_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
URDU_CHAR_MAP = str.maketrans({
    "ي": "ی",
    "ك": "ک",
    "ة": "ہ",
    "ھ": "ہ",
    "ؤ": "و",
    "إ": "ا",
    "أ": "ا",
    "آ": "ا"
})

def normalize_search_term(term):
    if not term:
        return ""
    text = str(term).strip()
    # Normalize digits
    text = text.translate(URDU_ARABIC_DIGIT_MAP)
    # Normalize Urdu/Arabic characters
    text = text.translate(URDU_CHAR_MAP)
    # Collapse multiple whitespaces
    text = re.sub(r'\s+', ' ', text)
    return text.lower()

def normalize_phone(phone_str):
    if not phone_str:
        return ""
    digits = re.sub(r'\D', '', str(phone_str).translate(URDU_ARABIC_DIGIT_MAP))
    if digits.startswith("92") and len(digits) > 10:
        digits = "0" + digits[2:]
    elif digits.startswith("0") and len(digits) > 10:
        pass
    # Return last 10 digits for matching
    return digits[-10:] if len(digits) >= 10 else digits

def escape_sql_like(value):
    # Escape SQL wildcards %, _
    return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def split_tokens(query_str):
    normalized = normalize_search_term(query_str)
    tokens = [t for t in normalized.split(' ') if t]
    return tokens

def search_products_and_units(query_str, limit=20, role="ADMIN"):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    
    tokens = split_tokens(query_str)
    if not tokens:
        return []
    
    raw_digits = re.sub(r'\D', '', query_str)
    results = []
    
    # 1. Direct IMEI Search (if query looks like full or partial IMEI)
    if len(raw_digits) >= 4:
        tail = raw_digits[-6:] if len(raw_digits) >= 6 else raw_digits
        imei_sql = """
            SELECT u.id as unit_id, u.imei1, u.imei2, u.condition, u.pta_status, u.cost_price, u.status as unit_status,
                   v.id as variant_id, v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price, v.barcode,
                   p.id as product_id, p.brand, p.name as product_name, p.category, p.item_type
            FROM units u
            JOIN variants v ON u.variant_id = v.id
            JOIN products p ON v.product_id = p.id
            WHERE (u.imei1 = ? OR u.imei2 = ? 
                   OR u.imei1_tail = ? OR u.imei2_tail = ?
                   OR u.imei1 LIKE ? OR u.imei2 LIKE ?)
            ORDER BY 
                CASE 
                    WHEN u.imei1 = ? OR u.imei2 = ? THEN 1
                    WHEN u.imei1_tail = ? OR u.imei2_tail = ? THEN 2
                    ELSE 3
                END ASC, u.id DESC
            LIMIT ?
        """
        like_tail = f"%{escape_sql_like(raw_digits)}"
        imei_rows = db.query_all(imei_sql, (
            raw_digits, raw_digits, tail, tail, like_tail, like_tail,
            raw_digits, raw_digits, tail, tail, limit
        ))
        for r in imei_rows:
            matched_imei = r["imei1"] if raw_digits in (r["imei1"] or "") else (r["imei2"] or r["imei1"])
            item = {
                "type": "unit",
                "entity": "phone_unit",
                "id": r["unit_id"],
                "unit_id": r["unit_id"],
                "variant_id": r["variant_id"],
                "product_id": r["product_id"],
                "brand": r["brand"],
                "model_name": r["product_name"],
                "product_name": r["product_name"],
                "variant_desc": f"{r['ram']}/{r['storage']} {r['color']}".strip(),
                "title": f"{r['brand']} {r['product_name']} ({r['ram']}/{r['storage']} {r['color']})",
                "subtitle": f"IMEI: {matched_imei} | {r['pta_status']} | {r['condition']} | Status: {r['unit_status']}",
                "price": r["retail_price"],
                "cost_price": r["cost_price"] if role == "ADMIN" else None,
                "url": f"/inventory/models/{r['product_id']}?unit={r['unit_id']}",
                "status": r["unit_status"],
                "in_stock_count": 1 if r["unit_status"] == "IN_STOCK" else 0,
                "imei": matched_imei,
                "item_type": r["item_type"]
            }
            results.append(item)
    
    # 2. Multi-word AND Search across Product and Variant with Multi-Tier Ranking
    # Tier 1: exact barcode/sku match
    # Tier 2: brand starts with prefix or name starts with prefix
    # Tier 3: any word in brand or name starts with prefix
    # Tier 4: substring contains
    conditions = []
    params = []
    for token in tokens:
        token_like = f"%{escape_sql_like(token)}%"
        conditions.append("""(
            p.brand LIKE ? ESCAPE '\\' OR 
            p.name LIKE ? ESCAPE '\\' OR 
            p.category LIKE ? ESCAPE '\\' OR
            v.ram LIKE ? ESCAPE '\\' OR 
            v.storage LIKE ? ESCAPE '\\' OR 
            v.color LIKE ? ESCAPE '\\' OR 
            v.barcode LIKE ? ESCAPE '\\' OR
            v.sku LIKE ? ESCAPE '\\'
        )""")
        params.extend([token_like] * 8)
    
    where_clause = " AND ".join(conditions)
    prefix_like = f"{escape_sql_like(clean_q)}%"
    word_prefix_like = f"% {escape_sql_like(clean_q)}%"

    pv_sql = f"""
        SELECT v.id as variant_id, v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price,
               v.barcode, v.sku, v.stock_quantity,
               p.id as product_id, p.brand, p.name as product_name, p.category, p.item_type
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE p.is_archived = 0 AND v.is_archived = 0 AND {where_clause}
        ORDER BY 
            CASE 
                WHEN v.barcode = ? OR v.sku = ? THEN 1
                WHEN p.brand LIKE ? ESCAPE '\\' THEN 2
                WHEN p.name LIKE ? ESCAPE '\\' THEN 3
                WHEN p.brand LIKE ? ESCAPE '\\' OR p.name LIKE ? ESCAPE '\\' THEN 4
                WHEN v.ram LIKE ? ESCAPE '\\' OR v.storage LIKE ? ESCAPE '\\' OR v.color LIKE ? ESCAPE '\\' THEN 5
                ELSE 6
            END ASC,
            p.brand ASC, p.name ASC
        LIMIT ?
    """
    ranking_params = [
        clean_q, clean_q,
        prefix_like,
        prefix_like,
        word_prefix_like, word_prefix_like,
        prefix_like, prefix_like, prefix_like
    ]
    query_params = params + ranking_params + [limit]
    pv_rows = db.query_all(pv_sql, query_params)

    for r in pv_rows:
        # Check available unit count or quantity
        if r["item_type"] == "PHONE":
            avail = db.query_one("SELECT count(*) c FROM units WHERE variant_id = ? AND status = 'IN_STOCK'", (r["variant_id"],))
            in_stock = avail["c"] if avail else 0
            stock_str = f"Stock: {in_stock} phones" if in_stock > 0 else "0 in stock"
        else:
            in_stock = r["stock_quantity"] or 0
            stock_str = f"Stock: {in_stock} pcs" if in_stock > 0 else "0 in stock"

        variant_desc = f"{r['ram']}/{r['storage']} {r['color']}".strip()
        results.append({
            "type": "variant",
            "entity": "inventory_item",
            "id": r["variant_id"],
            "variant_id": r["variant_id"],
            "product_id": r["product_id"],
            "brand": r["brand"],
            "model_name": r["product_name"],
            "product_name": r["product_name"],
            "variant_desc": variant_desc,
            "title": f"{r['brand']} {r['product_name']}" + (f" ({variant_desc})" if variant_desc else ""),
            "subtitle": f"{r['category']} | {stock_str} | Barcode: {r['barcode'] or 'N/A'}",
            "price": r["retail_price"],
            "in_stock_count": in_stock,
            "url": f"/inventory/models/{r['product_id']}",
            "item_type": r["item_type"],
            "barcode": r["barcode"],
            "sku": r["sku"]
        })

    return results[:limit]

def search_customers(query_str, limit=10):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    tokens = split_tokens(query_str)
    if not tokens:
        return []
    
    phone_norm = normalize_phone(query_str)
    conditions = []
    params = []
    for token in tokens:
        token_like = f"%{escape_sql_like(token)}%"
        conditions.append("(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' OR cnic LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\')")
        params.extend([token_like] * 4)
    
    if phone_norm and len(phone_norm) >= 2:
        conditions.append("(phone LIKE ? ESCAPE '\\')")
        params.append(f"%{escape_sql_like(phone_norm)}%")

    where_clause = " OR ".join(conditions)
    prefix_like = f"{escape_sql_like(clean_q)}%"

    sql = f"""
        SELECT id, name, phone, cnic, address, balance_udhaar
        FROM customers
        WHERE {where_clause}
        ORDER BY 
            CASE 
                WHEN name LIKE ? ESCAPE '\\' THEN 1
                WHEN phone LIKE ? ESCAPE '\\' THEN 2
                ELSE 3
            END ASC,
            name ASC
        LIMIT ?
    """
    ranking_params = [prefix_like, prefix_like]
    rows = db.query_all(sql, params + ranking_params + [limit])
    results = []
    for r in rows:
        results.append({
            "type": "customer",
            "entity": "customer",
            "id": r["id"],
            "title": r["name"],
            "subtitle": f"Phone: {r['phone']} | Udhaar: Rs. {int(r['balance_udhaar']):,} | CNIC: {r['cnic'] or 'N/A'}",
            "balance_udhaar": r["balance_udhaar"],
            "phone": r["phone"],
            "url": f"/credit/customer/{r['id']}"
        })
    return results

def search_suppliers(query_str, limit=10):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    tokens = split_tokens(query_str)
    if not tokens:
        return []
    
    phone_norm = normalize_phone(query_str)
    conditions = []
    params = []
    for token in tokens:
        token_like = f"%{escape_sql_like(token)}%"
        conditions.append("(name LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\')")
        params.extend([token_like] * 4)
    
    if phone_norm and len(phone_norm) >= 2:
        conditions.append("(phone LIKE ? ESCAPE '\\')")
        params.append(f"%{escape_sql_like(phone_norm)}%")

    where_clause = " OR ".join(conditions)
    prefix_like = f"{escape_sql_like(clean_q)}%"

    sql = f"""
        SELECT id, name, phone, company, balance
        FROM suppliers
        WHERE is_archived = 0 AND ({where_clause})
        ORDER BY 
            CASE 
                WHEN name LIKE ? ESCAPE '\\' THEN 1
                WHEN company LIKE ? ESCAPE '\\' THEN 2
                ELSE 3
            END ASC,
            name ASC
        LIMIT ?
    """
    ranking_params = [prefix_like, prefix_like]
    rows = db.query_all(sql, params + ranking_params + [limit])
    results = []
    for r in rows:
        results.append({
            "type": "supplier",
            "entity": "supplier",
            "id": r["id"],
            "title": r["name"] + (f" ({r['company']})" if r["company"] else ""),
            "subtitle": f"Phone: {r['phone']} | Payable: Rs. {int(r['balance']):,}",
            "balance": r["balance"],
            "phone": r["phone"],
            "url": f"/purchasing/supplier/{r['id']}"
        })
    return results

def search_sales(query_str, limit=10):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    
    like_q = f"%{escape_sql_like(clean_q)}%"
    prefix_q = f"{escape_sql_like(clean_q)}%"
    sql = """
        SELECT id, invoice_no, customer_name, customer_phone, grand_total, payment_method, created_at, status
        FROM sales
        WHERE invoice_no LIKE ? ESCAPE '\\' 
           OR customer_name LIKE ? ESCAPE '\\'
           OR customer_phone LIKE ? ESCAPE '\\'
        ORDER BY 
            CASE 
                WHEN invoice_no LIKE ? ESCAPE '\\' THEN 1
                WHEN customer_name LIKE ? ESCAPE '\\' THEN 2
                ELSE 3
            END ASC,
            id DESC
        LIMIT ?
    """
    rows = db.query_all(sql, (like_q, like_q, like_q, prefix_q, prefix_q, limit))
    results = []
    for r in rows:
        results.append({
            "type": "sale",
            "entity": "sale",
            "id": r["id"],
            "invoice_no": r["invoice_no"],
            "title": f"Invoice #{r['invoice_no']} — {r['customer_name']}",
            "subtitle": f"Amount: Rs. {int(r['grand_total']):,} | Date: {r['created_at'][:10]} | Paid via {r['payment_method']}",
            "grand_total": r["grand_total"],
            "url": f"/sales?invoice={r['invoice_no']}"
        })
    return results

def search_repairs(query_str, limit=10):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    
    like_q = f"%{escape_sql_like(clean_q)}%"
    prefix_q = f"{escape_sql_like(clean_q)}%"
    sql = """
        SELECT id, job_no, customer_name, customer_phone, brand, model, imei, complaint, status, total_charged
        FROM repair_jobs
        WHERE job_no LIKE ? ESCAPE '\\'
           OR customer_name LIKE ? ESCAPE '\\'
           OR customer_phone LIKE ? ESCAPE '\\'
           OR imei LIKE ? ESCAPE '\\'
           OR brand LIKE ? ESCAPE '\\'
           OR model LIKE ? ESCAPE '\\'
           OR complaint LIKE ? ESCAPE '\\'
        ORDER BY 
            CASE 
                WHEN job_no LIKE ? ESCAPE '\\' THEN 1
                WHEN customer_name LIKE ? ESCAPE '\\' THEN 2
                WHEN brand LIKE ? ESCAPE '\\' OR model LIKE ? ESCAPE '\\' THEN 3
                ELSE 4
            END ASC,
            id DESC
        LIMIT ?
    """
    rows = db.query_all(sql, (like_q, like_q, like_q, like_q, like_q, like_q, like_q, prefix_q, prefix_q, prefix_q, prefix_q, limit))
    results = []
    for r in rows:
        results.append({
            "type": "repair",
            "entity": "repair_job",
            "id": r["id"],
            "job_no": r["job_no"],
            "title": f"Repair #{r['job_no']} — {r['brand']} {r['model']}",
            "subtitle": f"Client: {r['customer_name']} ({r['customer_phone']}) | Complaint: {r['complaint']} | Status: {r['status']}",
            "url": f"/repairs?job={r['job_no']}"
        })
    return results

def search_software_jobs(query_str, limit=10):
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    
    like_q = f"%{escape_sql_like(clean_q)}%"
    prefix_q = f"{escape_sql_like(clean_q)}%"
    sql = """
        SELECT id, ticket_no, customer_name, brand_model, imei, service_name, price_charged, status
        FROM software_jobs
        WHERE ticket_no LIKE ? ESCAPE '\\'
           OR customer_name LIKE ? ESCAPE '\\'
           OR imei LIKE ? ESCAPE '\\'
           OR brand_model LIKE ? ESCAPE '\\'
           OR service_name LIKE ? ESCAPE '\\'
        ORDER BY 
            CASE 
                WHEN ticket_no LIKE ? ESCAPE '\\' THEN 1
                WHEN customer_name LIKE ? ESCAPE '\\' THEN 2
                WHEN brand_model LIKE ? ESCAPE '\\' THEN 3
                ELSE 4
            END ASC,
            id DESC
        LIMIT ?
    """
    rows = db.query_all(sql, (like_q, like_q, like_q, like_q, like_q, prefix_q, prefix_q, prefix_q, limit))
    results = []
    for r in rows:
        results.append({
            "type": "software",
            "entity": "software_job",
            "id": r["id"],
            "ticket_no": r["ticket_no"],
            "title": f"Software #{r['ticket_no']} — {r['service_name']}",
            "subtitle": f"Phone: {r['brand_model']} | Client: {r['customer_name']} | Charged: Rs. {int(r['price_charged']):,}",
            "url": f"/software?ticket={r['ticket_no']}"
        })
    return results

def search_expenses(query_str, limit=10, role="ADMIN"):
    if role != "ADMIN":
        return []
    clean_q = normalize_search_term(query_str)
    if not clean_q:
        return []
    
    like_q = f"%{escape_sql_like(clean_q)}%"
    prefix_q = f"{escape_sql_like(clean_q)}%"
    sql = """
        SELECT id, category, description, amount, payment_method, expense_date
        FROM expenses
        WHERE category LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR reference LIKE ? ESCAPE '\\'
        ORDER BY 
            CASE 
                WHEN category LIKE ? ESCAPE '\\' THEN 1
                ELSE 2
            END ASC,
            id DESC
        LIMIT ?
    """
    rows = db.query_all(sql, (like_q, like_q, like_q, prefix_q, limit))
    results = []
    for r in rows:
        results.append({
            "type": "expense",
            "entity": "expense",
            "id": r["id"],
            "title": f"Expense: {r['category']} — Rs. {int(r['amount']):,}",
            "subtitle": f"{r['description'] or 'No description'} | Date: {r['expense_date']} | {r['payment_method']}",
            "url": f"/expenses"
        })
    return results

def search_all(query_str, role="ADMIN", max_per_type=6):
    q = normalize_search_term(query_str)
    if not q:
        return {"query": query_str, "total_count": 0, "results": {}}
    
    results = {
        "products": search_products_and_units(query_str, limit=max_per_type, role=role),
        "customers": search_customers(query_str, limit=max_per_type),
        "suppliers": search_suppliers(query_str, limit=max_per_type) if role == "ADMIN" else [],
        "sales": search_sales(query_str, limit=max_per_type),
        "repairs": search_repairs(query_str, limit=max_per_type),
        "software": search_software_jobs(query_str, limit=max_per_type),
        "expenses": search_expenses(query_str, limit=max_per_type, role=role)
    }

    total_count = sum(len(items) for items in results.values())
    return {
        "query": query_str,
        "total_count": total_count,
        "results": results
    }
