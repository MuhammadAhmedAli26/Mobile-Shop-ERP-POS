import re

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# 1) Check what JS fetch calls are being made in web_ui.py
print("=== ALL fetch() calls in web_ui.py ===")
fetch_calls = []
for i, line in enumerate(lines):
    if "fetch(" in line or "fetch('" in line or 'fetch("' in line:
        stripped = line.strip()
        if len(stripped) < 120:
            fetch_calls.append((i+1, stripped))

for ln, code in fetch_calls:
    print(f"  Line {ln}: {code}")

print(f"\nTotal fetch calls: {len(fetch_calls)}")

# 2) Check udhaar payment specifically
print("\n=== Udhaar Pay JS section ===")
for i, line in enumerate(lines):
    if 'pay-udhaar' in line or 'payUdhaar' in line or 'pay_udhaar' in line:
        start = max(0, i-2)
        end = min(len(lines), i+3)
        for j in range(start, end):
            print(f"  Line {j+1}: {lines[j]}")
        print("  ---")

# 3) Check sales history route
print("\n=== Sales History handling ===")
for i, line in enumerate(lines):
    if 'sales_history' in line.lower() or 'sales-history' in line.lower() or "'/sales'" in line or '"/sales"' in line:
        print(f"  Line {i+1}: {line.strip()[:120]}")

# 4) Check POS udhaar save (when customer buys on credit)
print("\n=== POS Udhaar Add in checkout ===")
for i, line in enumerate(lines):
    if 'udhaar' in line.lower() and ('pos' in line.lower() or 'checkout' in line.lower() or 'sale' in line.lower()):
        print(f"  Line {i+1}: {line.strip()[:120]}")

# 5) Check for any undefined variable / missing function issues
print("\n=== Key function definitions ===")
funcs = ['submitMatrixWithStock', 'processReturn', 'submitCheckout', 'addToCart', 'searchReturn']
for fn in funcs:
    found = any(fn in line for line in lines)
    print(f"  {fn}: {'FOUND' if found else 'MISSING'}")
