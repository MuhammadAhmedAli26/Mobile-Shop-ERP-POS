# End-to-End HTTP Route Verification
import sys, os
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import web_ui, db

class MockSession(dict):
    def save(self): pass
    def delete(self): self.clear()

def verify_routes():
    print("=" * 60)
    print("🌐 VERIFYING ALL WEB UI ROUTES & APIS")
    print("=" * 60)

    # 1. Unauthenticated endpoints
    unauth_endpoints = [
        ("GET", "/login"),
        ("GET", "/api/scan-route?code=352889104567891&context=POS"),
    ]

    for method, path in unauth_endpoints:
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
            'wsgi.url_scheme': 'http'
        }
        res_status = []
        def start_response(status, headers):
            res_status.append(status)

        body = web_ui.app(env, start_response)
        status = res_status[0] if res_status else "Unknown"
        assert "200" in status or "302" in status, f"Route {path} failed with {status}"
        print(f"✓ Route {method} {path} -> {status}")

    # 2. Authenticated endpoints (Admin user)
    auth_endpoints = [
        ("GET", "/"),
        ("GET", "/pos"),
        ("GET", "/inventory"),
        ("GET", "/inventory/matrix-create"),
        ("GET", "/purchasing"),
        ("GET", "/returns"),
        ("GET", "/repairs"),
        ("GET", "/software"),
        ("GET", "/quick-services"),
        ("GET", "/credit"),
        ("GET", "/expenses"),
        ("GET", "/reports"),
        ("GET", "/day-closing"),
        ("GET", "/settings"),
        ("GET", "/settings/lookups"),
        ("GET", "/settings/scanner-test"),
        ("GET", "/print/sale/1"),
        ("GET", "/print/return/1"),
        ("GET", "/print/repair/1"),
        ("GET", "/print/software/1"),
        ("GET", "/print/trade-in/1"),
        ("GET", "/print/barcode-label/1"),
        ("GET", "/print/supplier-payment/1"),
        ("GET", "/print/installment-contract/1"),
        ("GET", "/print/installment-payment/1"),
        ("GET", "/print/day-closing/2026-10-11"),
        ("GET", "/print/monthly-report/2026/10"),
        ("GET", "/api/lookups?key=brand"),
        ("GET", "/api/search?q=iphone"),
        ("GET", "/api/search/products?q=samsung"),
        ("GET", "/api/search/customers?q=ali"),
        ("GET", "/inventory/product/1"),
        ("GET", "/inventory/models/1"),
        ("GET", "/api/items/1")
    ]

    for method, path in auth_endpoints:
        sess = MockSession({"uid": 1})
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
        def start_response(status, headers):
            res_status.append(status)

        body = web_ui.app(env, start_response)
        status = res_status[0] if res_status else "Unknown"
        assert "200" in status or "302" in status, f"Auth route {path} failed with {status}"
        print(f"✓ Auth Route {method} {path} -> {status}")

    print("\n" + "=" * 60)
    print(f"🏆 ALL {len(unauth_endpoints) + len(auth_endpoints)} WEB ROUTES & PRINT ENDPOINTS VERIFIED (100% OK)!")
    print("=" * 60)

if __name__ == "__main__":
    verify_routes()
