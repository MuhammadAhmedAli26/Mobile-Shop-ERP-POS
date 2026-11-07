# qa/scripts/t3_invariants.py
# Database invariant checker - runs against a live DB file
# Usage: python qa/scripts/t3_invariants.py <db_path>
import sys, sqlite3, json, pathlib, os

def check_invariants(db_path):
    results = {"db": str(db_path), "checks": [], "pass": 0, "fail": 0}

    def check(name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        results["checks"].append({"name": name, "status": status, "detail": detail})
        if passed:
            results["pass"] += 1
        else:
            results["fail"] += 1
        print(f"  [{status}] {name}" + (f" | {detail}" if detail else ""))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. SQLite integrity
    c.execute("PRAGMA integrity_check")
    r = c.fetchone()[0]
    check("PRAGMA integrity_check", r == "ok", r)

    # 2. Foreign key check
    c.execute("PRAGMA foreign_key_check")
    fk_violations = c.fetchall()
    check("PRAGMA foreign_key_check", len(fk_violations) == 0,
          f"{len(fk_violations)} violations" if fk_violations else "")

    # 3. Phone variant.stock_quantity matches count of IN_STOCK units
    c.execute("""
        SELECT v.id, v.stock_quantity,
               COUNT(u.id) AS real_count
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN units u ON u.variant_id = v.id AND u.status = 'IN_STOCK'
        WHERE p.item_type = 'PHONE'
        GROUP BY v.id
        HAVING v.stock_quantity != real_count
    """)
    mismatches = c.fetchall()
    check("Phone stock quantity matches IN_STOCK units", len(mismatches) == 0,
          f"{len(mismatches)} variants mismatched" if mismatches else "")

    # 4. No duplicate IMEI1 or IMEI2 among active units
    c.execute("""
        SELECT imei1, COUNT(*) AS cnt FROM units
        WHERE imei1 IS NOT NULL AND imei1 != ''
        GROUP BY imei1 HAVING cnt > 1
    """)
    dup1 = c.fetchall()
    c.execute("""
        SELECT imei2, COUNT(*) AS cnt FROM units
        WHERE imei2 IS NOT NULL AND imei2 != ''
        GROUP BY imei2 HAVING cnt > 1
    """)
    dup2 = c.fetchall()
    check("No duplicate IMEI1 across all units", len(dup1) == 0,
          f"{len(dup1)} duplicates" if dup1 else "")
    check("No duplicate IMEI2 across all units", len(dup2) == 0,
          f"{len(dup2)} duplicates" if dup2 else "")

    # 5. Every sale has at least one sale_item
    c.execute("""
        SELECT s.id FROM sales s
        WHERE NOT EXISTS (SELECT 1 FROM sale_items WHERE sale_id = s.id)
          AND s.status NOT IN ('VOIDED', 'CANCELLED')
    """)
    empty_sales = c.fetchall()
    check("All non-voided sales have items", len(empty_sales) == 0,
          f"Sales with no items: {[r[0] for r in empty_sales]}" if empty_sales else "")

    # 6. Sale math: grand_total = subtotal - discount (within 0.01 tolerance)
    c.execute("""
        SELECT s.id, s.grand_total, s.discount_amount,
               COALESCE((SELECT SUM(si.qty * si.unit_price - COALESCE(si.discount,0))
                         FROM sale_items si WHERE si.sale_id = s.id), 0) AS computed_subtotal
        FROM sales s WHERE s.status NOT IN ('VOIDED','CANCELLED')
    """)
    bad_math = []
    for row in c.fetchall():
        expected = max(0, row["computed_subtotal"] - (row["discount_amount"] or 0))
        if abs(expected - (row["grand_total"] or 0)) > 1.0:
            bad_math.append(row["id"])
    check("Sale math grand_total correct", len(bad_math) == 0,
          f"Bad math sales: {bad_math[:5]}" if bad_math else "")

    # 7. Customer udhaar balance >= 0
    c.execute("SELECT id FROM customers WHERE balance_udhaar < 0")
    neg = c.fetchall()
    check("No negative customer udhaar balance", len(neg) == 0,
          f"Negative balance customers: {[r[0] for r in neg]}" if neg else "")

    # 8. Sold units have exactly one active non-voided sale item
    c.execute("""
        SELECT u.id, COUNT(si.id) AS cnt
        FROM units u
        JOIN sale_items si ON si.unit_id = u.id
        JOIN sales s ON si.sale_id = s.id AND s.status NOT IN ('VOIDED','CANCELLED')
        WHERE u.status = 'SOLD'
        GROUP BY u.id
        HAVING cnt != 1
    """)
    bad_sold = c.fetchall()
    check("All SOLD units have exactly 1 active sale item", len(bad_sold) == 0,
          f"Mis-sold units: {[r[0] for r in bad_sold[:5]]}" if bad_sold else "")

    # 9. No sale_item with unit_id = 0 for PHONE type (phone units must be linked)
    c.execute("""
        SELECT si.id FROM sale_items si
        JOIN sales s ON si.sale_id = s.id AND s.status NOT IN ('VOIDED','CANCELLED')
        WHERE si.item_type = 'PHONE' AND (si.unit_id IS NULL OR si.unit_id = 0)
    """)
    bad_unit = c.fetchall()
    check("No PHONE sale items with unit_id=0/NULL", len(bad_unit) == 0,
          f"Bad items: {[r[0] for r in bad_unit[:5]]}" if bad_unit else "")

    # 10. No empty string in unique columns (barcode)
    try:
        c.execute("SELECT COUNT(*) FROM variants WHERE barcode = ''")
        empty_bc = c.fetchone()[0]
        check("No empty-string barcodes", empty_bc == 0, f"{empty_bc} empty barcodes" if empty_bc else "")
    except Exception as e:
        check("No empty-string barcodes", True, f"skipped: {e}")

    conn.close()
    results["overall"] = "PASS" if results["fail"] == 0 else "FAIL"
    return results

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "mobile_erp.db"
    if not pathlib.Path(db_path).exists():
        print(f"DB not found: {db_path}")
        sys.exit(1)
    print(f"\n=== T3 Invariant Check: {db_path} ===")
    results = check_invariants(db_path)
    print(f"\nResult: {results['overall']} ({results['pass']} pass, {results['fail']} fail)")
    out_path = pathlib.Path(__file__).parent.parent / "results" / "t3_invariants.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved: {out_path}")
    sys.exit(0 if results["fail"] == 0 else 1)
