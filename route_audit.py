import re

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

routes = re.findall(r"@app\.route\([\"'](.*?)[\"']", content)
print(f"Total routes: {len(routes)}")

print("\n--- UDHAAR/KHATA routes ---")
for r in routes:
    if 'udh' in r.lower() or 'khata' in r.lower() or 'credit' in r.lower():
        print(" ", r)

print("\n--- PAYMENT routes ---")
for r in routes:
    if 'pay' in r.lower():
        print(" ", r)

print("\n--- RETURN routes ---")
for r in routes:
    if 'return' in r.lower():
        print(" ", r)

print("\n--- POS routes ---")
for r in routes:
    if 'pos' in r.lower() or 'sale' in r.lower() or 'checkout' in r.lower() or 'cart' in r.lower():
        print(" ", r)

print("\n--- INVENTORY routes ---")
for r in routes:
    if 'inventory' in r.lower() or 'product' in r.lower() or 'stock' in r.lower() or 'variant' in r.lower():
        print(" ", r)

print("\n--- REPORT routes ---")
for r in routes:
    if 'report' in r.lower() or 'profit' in r.lower() or 'expense' in r.lower() or 'closing' in r.lower():
        print(" ", r)

print("\n--- SUPPLIER/PURCHASE routes ---")
for r in routes:
    if 'supplier' in r.lower() or 'purchas' in r.lower() or 'vendor' in r.lower():
        print(" ", r)

print("\n--- AUTH/STAFF routes ---")
for r in routes:
    if 'login' in r.lower() or 'staff' in r.lower() or 'user' in r.lower() or 'pass' in r.lower():
        print(" ", r)

# Check JS issues
print("\n--- Checking JS in web_ui.py for known patterns ---")
# Check if udhaar payment endpoint exists in JS
if "api/udhaar/pay" in content or "udhaar/pay" in content:
    print("  JS calls udhaar/pay: YES")
else:
    print("  JS calls udhaar/pay: NOT FOUND (potential bug)")

if "api/sales/lookup" in content:
    print("  JS calls api/sales/lookup for returns: YES")
else:
    print("  JS calls api/sales/lookup: NOT FOUND")

if "sales/history" in content:
    print("  Sales history route: YES")
else:
    print("  Sales history route: NOT FOUND")

if "udhaar_ledger" in content:
    print("  udhaar_ledger table referenced: YES")
else:
    print("  udhaar_ledger table: NOT FOUND")
