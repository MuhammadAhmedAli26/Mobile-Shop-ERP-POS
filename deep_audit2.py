import re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# 1) Check udhaar payment JS
print("=== Udhaar Pay JS section ===")
for i, line in enumerate(lines):
    if 'pay-udhaar' in line or 'payUdhaar' in line or 'pay_udhaar' in line:
        start = max(0, i-2)
        end = min(len(lines), i+3)
        for j in range(start, end):
            print(f"  Line {j+1}: {lines[j][:150]}")
        print("  ---")

# 2) Check sales history route/page
print("\n=== Sales History page ===")
for i, line in enumerate(lines):
    if ('/sales' in line or 'sales_screen' in line.lower() or 'salesScreen' in line) and i < 200:
        print(f"  Line {i+1}: {line.strip()[:150]}")

# 3) Check POS -> udhaar linkage
print("\n=== POS Udhaar/Credit linkage ===")
for i, line in enumerate(lines):
    if 'udhaar' in line.lower() and 'checkout' in lines[max(0,i-20):i+1].__str__().lower():
        print(f"  Line {i+1}: {line.strip()[:150]}")

# 4) Check returns page JS
print("\n=== Returns page JS functions ===")
for i, line in enumerate(lines):
    if 'searchReturn' in line or 'processReturn' in line or 'selectSaleForReturn' in line:
        print(f"  Line {i+1}: {line.strip()[:150]}")

# 5) Check for missing routes that JS calls
print("\n=== Routes called by JS but NOT defined as Flask routes ===")
with open('web_ui.py', 'r', encoding='utf-8') as f:
    content2 = f.read()

flask_routes = set(re.findall(r"@app\.route\([\"'](.*?)[\"']", content2))
# simplify parameterized
simplified = set()
for r in flask_routes:
    simplified.add(re.sub(r'<[^>]+>', '*', r))

js_fetches = re.findall(r"fetch\(['\"]([^'\"]+)['\"]", content2)
print("JS fetch targets not matching any Flask route:")
for jf in js_fetches:
    clean = re.sub(r'\?.*', '', jf)  # remove query string
    matched = False
    for sr in simplified:
        pattern = sr.replace('*', '[^/]+').replace('/', '\\/')
        if re.fullmatch(pattern, clean):
            matched = True
            break
    if clean in flask_routes or clean in simplified:
        matched = True
    if not matched:
        print(f"  MISSING ROUTE: {jf}")

# 6) Key function definitions check
print("\n=== Key JS function definitions ===")
funcs = ['submitMatrixWithStock', 'processReturn', 'submitCheckout', 'addToCart', 
         'searchReturn', 'selectSaleForReturn', 'payUdhaar', 'submitPayUdhaar']
for fn in funcs:
    found = fn in content2
    print(f"  {'OK' if found else 'MISSING'}: {fn}()")
