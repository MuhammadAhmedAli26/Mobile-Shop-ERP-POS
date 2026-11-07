import re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()
lines = content.split('\n')

# Check the @app.route for /credit/pay-udhaar - what method does it use?
print("=== /credit/pay-udhaar route definition ===")
for i, line in enumerate(lines):
    if '/credit/pay-udhaar' in line or 'pay_udhaar_route' in line:
        for j in range(i, min(i+40, len(lines))):
            print(f"  Line {j+1}: {lines[j][:170]}")
            if j > i+3 and lines[j].startswith('@app.route'):
                break

# Check bottles 'method' param usage - it might be wrong
print("\n=== Bottle method= usage (should be 'methods' not 'method') ===")
bottle_method_wrong = []
for i, line in enumerate(lines):
    if '@app.route' in line and 'method=' in line and 'methods=' not in line:
        bottle_method_wrong.append((i+1, line.strip()))
print(f"Routes using 'method=' (correct for Bottle): {len(bottle_method_wrong)}")
for ln, l in bottle_method_wrong[:15]:
    print(f"  Line {ln}: {l}")

# Check if Bottle or Flask is being used
print("\n=== Framework check ===")
for i, line in enumerate(lines[:30]):
    if 'import' in line or 'from' in line:
        print(f"  Line {i+1}: {line.strip()}")

# Check sales lookup function to see if it handles name search correctly
print("\n=== api_sales_lookup function body ===")
in_fn = False
for i, line in enumerate(lines):
    if 'def api_sales_lookup' in line:
        in_fn = True
    if in_fn:
        print(f"  Line {i+1}: {line[:170]}")
        if in_fn and i > 7575 and line.strip() == '':
            pass
        if in_fn and i > 7575 and line.startswith('@app.route'):
            break

# Check if sales are added to history after udhaar payment
print("\n=== Is udhaar payment visible in sales history? ===")
print("  NOTE: udhaar payments go to udhaar_ledger, NOT sales table")
print("  The /sales page shows SALES only, not udhaar payments separately")
print("  This is expected - udhaar payment receipts are in /credit/customer/<id>")

# Check trade-in route
print("\n=== Trade-in route ===")
for i, line in enumerate(lines):
    if '@app.route("/returns/trade-in"' in line or "trade_in" in line.lower() and i > 7600:
        print(f"  Line {i+1}: {line.strip()[:150]}")
