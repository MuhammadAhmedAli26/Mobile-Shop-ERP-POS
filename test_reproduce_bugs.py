# GATE G1 - Reproduction Test Suite for Reported Bugs
import sys, os
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
    sess = MockSession(session_data or {"uid": 1})
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

def run_reproduction_tests():
    print("=" * 65)
    print("🔬 GATE G1 — REPRODUCING EXACT REPORTED SYMPTOMS")
    print("=" * 65)

    # 1. Bug 1 Reproduction: /inventory/models/<id> returns 404 Not Found
    # First find an existing product ID in the database
    prod = db.query_one("SELECT id, brand, name FROM products LIMIT 1")
    pid = prod["id"] if prod else 22
    print(f"\n[Test 1] Testing deep link /inventory/models/{pid}...")
    status, headers, body = request_route("GET", f"/inventory/models/{pid}")
    print(f"   Status returned: {status}")
    if "404" in status and "Sorry, the requested URL" in body:
        print("   ❌ CONFIRMED BUG 1: Bottle raw 404 returned for /inventory/models/<id>")
        print(f"      Body excerpt: {body[:140]}...")
    else:
        print(f"   Response: {status}")

    # 2. Bug 2 Reproduction: POS search does not work for typed text
    print("\n[Test 2] Testing POS scan-route with typed product name 'samsung'...")
    status, headers, body = request_route("GET", "/api/scan-route?code=samsung&context=POS")
    print(f"   Status: {status}, Body: {body.strip()}")
    if '"success": false' in body.lower() or 'not found' in body.lower():
        print("   ❌ CONFIRMED BUG 2: POS barcode scanner rejects typed name query")

    # 3. Bug 3 Reproduction: 1-character search 'a' is blocked / returns 0 results
    print("\n[Test 3] Testing 1-letter search for 'a' via search_all...")
    res = search.search_all("a")
    print(f"   search_all('a') results count: {res.get('total_count', 0)}")
    if res.get('total_count', 0) == 0:
        print("   ❌ CONFIRMED BUG 3: 1-letter query 'a' rejected by search_all (min length < 2)")

    # 4. Bug 4 Reproduction: Raw Bottle 404 on unhandled routes
    print("\n[Test 4] Testing custom 404 on non-existent route /some-invalid-page...")
    status, headers, body = request_route("GET", "/some-invalid-page")
    print(f"   Status: {status}")
    if "Sorry, the requested URL" in body:
        print("   ❌ CONFIRMED BUG 4: Bottle returns unstyled raw error page on 404")

    print("\n" + "=" * 65)
    print("Audit reproduction complete.")
    print("=" * 65)

if __name__ == "__main__":
    run_reproduction_tests()
