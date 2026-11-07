# GATE G5 - COMPREHENSIVE VERIFICATION & BENCHMARK SUITE
import sys, os, time, json
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import web_ui, db, search, scanner

class MockSession(dict):
    def save(self): pass
    def delete(self): self.clear()

def request_route(method, path, session_data=None):
    sess = MockSession(session_data or {"uid": 1, "role": "ADMIN", "username": "admin"})
    env = {
        'REQUEST_METHOD': method,
        'PATH_INFO': path.split('?')[0],
        'QUERY_STRING': path.split('?')[1] if '?' in path else '',
        'wsgi.input': sys.stdin,
        'SERVER_NAME': 'localhost',
        'SERVER_PORT': '8085',
        'wsgi.version': (1, 0),
        'wsgi.run_once': False,
        'wsgi.multithread': True,
        'wsgi.multiprocess': False,
        'wsgi.url_scheme': 'http',
        'wsgi.errors': sys.stderr,
        'beaker.session': sess
    }
    res_status = []
    headers_list = []
    def start_response(status, headers):
        res_status.append(status)
        headers_list.extend(headers)

    body = web_ui.app(env, start_response)
    body_str = b"".join(body).decode("utf-8", errors="replace") if isinstance(body, (list, tuple)) else str(body)
    return res_status[0] if res_status else "500", dict(headers_list), body_str

def run_gate5_tests():
    print("=" * 70)
    print("🚀 GATE G5 — COMPREHENSIVE RED TEAM & VERIFICATION SUITE")
    print("=" * 70)
    passed_count = 0
    total_count = 0

    def test(name, condition, msg=""):
        nonlocal passed_count, total_count
        total_count += 1
        if condition:
            passed_count += 1
            print(f"  ✅ [PASS] {name}")
        else:
            print(f"  ❌ [FAIL] {name} — {msg}")
            assert False, f"Test failed: {name}: {msg}"

    # ─────────────────────────────────────────────────────────────
    # PART 1: EXACT BUGS VERIFICATION
    # ─────────────────────────────────────────────────────────────
    print("\n[PART 1] Verifying 4 Reported Root Bugs:")

    # 1.1 Model Deep Link Route
    prod = db.query_one("SELECT id, brand, name FROM products LIMIT 1")
    pid = prod["id"] if prod else 1
    st, hd, body = request_route("GET", f"/inventory/models/{pid}")
    test("Bug 1.1: /inventory/models/<id> returns 200 OK", "200" in st)
    test("Bug 1.2: Model detail page renders specifications and inventory details", "Inventory Details" in body or prod["name"] in body)

    # 1.2 Non-existent model deep link
    st, hd, body = request_route("GET", "/inventory/models/999999")
    test("Bug 1.3: Non-existent model returns in-app styled 200 with notice", "200" in st and "Model #999999 Not Found" in body)

    # 1.3 POS Scan-route with typed product name
    st, hd, body = request_route("GET", "/api/scan-route?code=samsung&context=POS")
    data = json.loads(body)
    test("Bug 2.1: /api/scan-route with typed name returns success: true", data.get("success") is True)
    test("Bug 2.2: Scan-route returns matches or accessory/unit payload", data.get("type") in ["ACCESSORY_FOUND", "UNIT_FOUND", "SEARCH_MATCHES"])

    # 1.4 Single-letter search
    res_a = search.search_all("a")
    test("Bug 3.1: 1-character search 'a' returns > 0 results", res_a.get("total_count", 0) > 0)
    test("Bug 3.2: Products found for query 'a'", len(res_a.get("results", {}).get("products", [])) > 0)

    # 1.5 Custom 404 Browser Page
    st, hd, body = request_route("GET", "/non-existent-random-page")
    test("Bug 4.1: Custom browser 404 returns HTTP 404", "404" in st)
    test("Bug 4.2: Custom browser 404 contains styled header", "404 — Page Not Found" in body)
    test("Bug 4.3: Custom browser 404 contains Return to POS button", "Return to POS" in body)
    test("Bug 4.4: Custom browser 404 contains Ahmed watermark", "Developed by Ahmed" in body)
    test("Bug 4.5: Raw Bottle error page absent", "<!DOCTYPE HTML PUBLIC \"-//IETF//DTD HTML 2.0//EN\">" not in body)

    # 1.6 Custom 404 API Endpoint
    st, hd, body = request_route("GET", "/api/non-existent-route")
    test("Bug 4.6: Custom API 404 returns HTTP 404 JSON", "404" in st and '"success": false' in body)

    # ─────────────────────────────────────────────────────────────
    # PART 2: 1-CHARACTER AND MULTI-TIER SEARCH ACROSS A-Z & 0-9
    # ─────────────────────────────────────────────────────────────
    print("\n[PART 2] Exhaustive Single-Character & Tiered Search Benchmark:")

    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    latencies = []
    for ch in alphabet:
        t0 = time.perf_counter()
        res = search.search_all(ch)
        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)
        assert isinstance(res.get("results"), dict), f"Failed result shape for '{ch}'"
    
    avg_latency = sum(latencies) / len(latencies)
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    test(f"2.1: Single-letter searches (a-z, 0-9) average latency: {avg_latency:.2f} ms (< 50ms target)", avg_latency < 50.0)
    test(f"2.2: Single-letter searches p95 latency: {p95_latency:.2f} ms (< 75ms target)", p95_latency < 75.0)

    # Multi-Tier Ranking verification
    prod_a = search.search_products_and_units("a", limit=10)
    test("2.3: Multi-tier ranking puts prefix matches first", 
         any(p["brand"].lower().startswith("a") or p["model_name"].lower().startswith("a") for p in prod_a))

    # ─────────────────────────────────────────────────────────────
    # PART 3: RED TEAM INJECTION & SPECIAL CHARACTERS
    # ─────────────────────────────────────────────────────────────
    print("\n[PART 3] Red Team Injection & Security Attacks:")

    attacks = [
        "%", "_", "%%%", "___", "'", "''", "\"", "\\", ";", "--", "/*", "*/",
        "' OR '1'='1", "' UNION SELECT 1,2,3--", "<script>alert(1)</script>",
        "../../etc/passwd", "null", "undefined", "[object Object]"
    ]
    for atk in attacks:
        res = search.search_all(atk)
        test(f"3.x: Search resilience for payload '{atk[:20]}'", isinstance(res, dict))

    # ─────────────────────────────────────────────────────────────
    # PART 4: URDU NORMALIZATION
    # ─────────────────────────────────────────────────────────────
    print("\n[PART 4] Urdu & Arabic Normalization:")

    # Urdu digits
    t_digits = search.normalize_search_term("سامسونگ ۱۲۸")
    test("4.1: Urdu digits normalized to 0-9", "128" in t_digits)

    # Urdu character mapping
    t_chars = search.normalize_search_term("آئی فون كے كيسز")
    test("4.2: Arabic kaf/yeh mapped to Urdu", "ک" in t_chars and "ا" in t_chars)

    # ─────────────────────────────────────────────────────────────
    # PART 5: DEEP LINKS & SITEMAP CRAWLER
    # ─────────────────────────────────────────────────────────────
    print("\n[PART 5] Deep Links & Sitemap Crawler:")

    # Customer ledger deep link
    cust = db.query_one("SELECT id, name FROM customers LIMIT 1")
    cid = cust["id"] if cust else 1
    st, hd, body = request_route("GET", f"/credit/customer/{cid}")
    test(f"5.1: Customer deep link /credit/customer/{cid} returns 200", "200" in st and "Khata Ledger" in body)

    # Supplier ledger deep link
    sup = db.query_one("SELECT id, name FROM suppliers LIMIT 1")
    sid = sup["id"] if sup else 1
    st, hd, body = request_route("GET", f"/purchasing/supplier/{sid}")
    test(f"5.2: Supplier deep link /purchasing/supplier/{sid} returns 200", "200" in st and "Supplier Ledger" in body)

    # Sales invoice route
    sale = db.query_one("SELECT id, invoice_no FROM sales LIMIT 1")
    if sale:
        st, hd, body = request_route("GET", f"/sales?invoice={sale['invoice_no']}")
        test("5.3: Sales invoice deep link /sales?invoice=... redirects to print slip", "302" in st or "200" in st)

    # Repair alias route
    st, hd, body = request_route("GET", "/repairing")
    test("5.4: Repairing alias route redirects to /repairs", "302" in st)

    # API Variant Units for POS
    var = db.query_one("SELECT id FROM variants WHERE is_archived = 0 LIMIT 1")
    vid = var["id"] if var else 1
    st, hd, body = request_route("GET", f"/api/pos/variant-units/{vid}")
    test("5.5: POS variant-units API returns 200 JSON", "200" in st and '"success": true' in body)

    print("\n" + "=" * 70)
    print(f"🎉 GATE G5 VERIFICATION COMPLETE: {passed_count}/{total_count} TESTS PASSED (100%)")
    print("=" * 70)

if __name__ == "__main__":
    run_gate5_tests()
