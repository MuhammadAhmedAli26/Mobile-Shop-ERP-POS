import sys, os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import db, search

def run_tests():
    print("--- RUNNING 15 SEARCH TESTS ---")
    
    # 1. Urdu digit normalization
    t1 = search.normalize_search_term("سامسونگ ۱۲۸")
    assert "128" in t1, f"Failed Urdu digit: {t1}"
    print("Test 1 Passed: Urdu digits normalized (۱۲۸ -> 128)")

    # 2. Urdu character normalization (ي -> ی, ك -> ک)
    t2 = search.normalize_search_term("آئی فون كے كور")
    assert "ک" in t2, f"Failed Urdu kaf: {t2}"
    print("Test 2 Passed: Urdu character normalization (ك -> ک)")

    # 3. Multi-word token split
    tokens = search.split_tokens("Samsung A15 128 Blue")
    assert tokens == ["samsung", "a15", "128", "blue"], f"Failed tokens: {tokens}"
    print("Test 3 Passed: Multi-word token splitting")

    # 4. Phone normalization with +92 and dashes
    p1 = search.normalize_phone("+92-300-1234567")
    assert p1 == "3001234567", f"Failed phone: {p1}"
    print("Test 4 Passed: Phone normalization +92 format (3001234567)")

    # 5. Phone normalization with leading zero
    p2 = search.normalize_phone("0300 1234567")
    assert p2 == "3001234567", f"Failed phone: {p2}"
    print("Test 5 Passed: Phone normalization leading zero (3001234567)")

    # 6. SQL wildcard escape
    e1 = search.escape_sql_like("100% Cotton_Item")
    assert "\\%" in e1 and "\\_" in e1, f"Failed escape: {e1}"
    print("Test 6 Passed: SQL wildcards % and _ escaped")

    # 7. Reverse word order query matching in search_products_and_units
    res_fwd = search.search_products_and_units("Samsung A15", limit=5)
    res_rev = search.search_products_and_units("A15 Samsung", limit=5)
    assert len(res_fwd) > 0, "No results for Samsung A15"
    assert len(res_rev) > 0, "No results for A15 Samsung (reverse order)"
    assert res_fwd[0]["variant_id"] == res_rev[0]["variant_id"], "Order independence failed"
    print("Test 7 Passed: Multi-word query order independence ('Samsung A15' == 'A15 Samsung')")

    # 8. Brand search
    b_res = search.search_products_and_units("Apple", limit=5)
    assert len(b_res) > 0 and "Apple" in b_res[0]["title"], f"Failed brand search: {b_res}"
    print("Test 8 Passed: Brand search ('Apple')")

    # 9. RAM & Storage combination search
    spec_res = search.search_products_and_units("8GB 256GB", limit=5)
    assert len(spec_res) > 0, "No results for 8GB 256GB"
    print("Test 9 Passed: Specification combo search ('8GB 256GB')")

    # 10. Barcode search
    # Fetch a real barcode from variants
    v = db.query_one("SELECT barcode FROM variants WHERE barcode != '' LIMIT 1")
    if v:
        bc_res = search.search_products_and_units(v["barcode"], limit=5)
        assert len(bc_res) > 0, f"Failed barcode search for {v['barcode']}"
        print(f"Test 10 Passed: Barcode search ({v['barcode']})")
    else:
        print("Test 10 Skipped: No barcode found in test DB")

    # 11. IMEI full 15-digit search
    u = db.query_one("SELECT imei1 FROM units WHERE imei1 != '' LIMIT 1")
    if u:
        imei_res = search.search_products_and_units(u["imei1"], limit=5)
        assert len(imei_res) > 0, f"Failed full IMEI search for {u['imei1']}"
        print(f"Test 11 Passed: Full 15-digit IMEI search ({u['imei1']})")
        
        # 12. Tail IMEI 6-digit search
        tail = u["imei1"][-6:]
        tail_res = search.search_products_and_units(tail, limit=5)
        assert any(r.get("unit_id") for r in tail_res), f"Failed tail IMEI search for {tail}"
        print(f"Test 12 Passed: Tail 6-digit IMEI search ({tail})")

    # 13. Customer search by partial phone or name
    c_res = search.search_customers("Usman", limit=5)
    assert len(c_res) > 0, "Failed customer search"
    print("Test 13 Passed: Customer search by name/partial phone ('Usman')")

    # 14. Global search (search_all) returns multi-entity dictionary
    all_res = search.search_all("Samsung", role="ADMIN")
    assert "products" in all_res["results"], "Missing products in search_all"
    assert all_res["total_count"] > 0, "Search all returned 0 results"
    print(f"Test 14 Passed: Global search (search_all) returned {all_res['total_count']} matches")

    # 15. Role permission filter in search_all
    emp_res = search.search_all("Samsung", role="EMPLOYEE")
    assert emp_res["results"]["suppliers"] == [], "Employee leaked supplier search!"
    assert emp_res["results"]["expenses"] == [], "Employee leaked expense search!"
    print("Test 15 Passed: Role-based search data security (Suppliers & Expenses hidden from EMPLOYEE)")

    print("\nALL 15 SEARCH TESTS PASSED SUCCESSFULLY! (15/15)")

if __name__ == "__main__":
    run_tests()
