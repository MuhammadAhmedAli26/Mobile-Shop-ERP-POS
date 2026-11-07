import re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()
lines = content.split('\n')

# 1. Find the returns screen HTML and how it submits
print("=== RETURNS SCREEN: Form submission mechanism ===")
in_ret = False
for i, line in enumerate(lines):
    if '@app.route("/returns"' in line or "@app.route('/returns'" in line:
        in_ret = True
        start_i = i
    if in_ret and i > start_i + 2 and 'def ' in line and 'return' not in line.lower():
        break
    if in_ret:
        s = line.strip()
        if any(kw in s.lower() for kw in ['form', 'action=', 'submit', 'onclick', 'lookup', 'search', 'invoice', 'button']):
            print(f"  Line {i+1}: {s[:160]}")

# 2. Check the search bar in returns for how it queries
print("\n=== RETURNS: Search/Lookup JS calls ===")
for i, line in enumerate(lines):
    if 'ret-search' in line.lower() or 'lookup' in line.lower() or 'sales/lookup' in line.lower():
        if 7000 < i < 8000:
            print(f"  Line {i+1}: {line.strip()[:160]}")

# 3. POS: check how udhaar toggle works in checkout
print("\n=== POS: Udhaar toggle in cart ===")
for i, line in enumerate(lines):
    if ('udhaar' in line.lower() or 'partial' in line.lower()) and 2400 < i < 2700:
        print(f"  Line {i+1}: {line.strip()[:160]}")

# 4. Check sales screen
print("\n=== SALES SCREEN: What does /sales show? ===")
for i, line in enumerate(lines):
    if '@app.route("/sales"' in line or "@app.route('/sales'" in line:
        for j in range(i, min(i+50, len(lines))):
            print(f"  Line {j+1}: {lines[j][:160]}")
            if j > i+3 and lines[j].startswith('def ') and 'sales' not in lines[j].lower():
                break

# 5. Check if sales history includes udhaar sales
print("\n=== SALES route: Does it show udhaar/credit sales? ===")
with open('pos.py', 'r', encoding='utf-8') as f:
    pos_c = f.read()
pos_lines = pos_c.split('\n')
for i, line in enumerate(pos_lines):
    if 'get_sales' in line or 'sales_list' in line or 'daily_sales' in line or ('SELECT' in line and 'sales' in line.lower()):
        print(f"  pos.py Line {i+1}: {line.strip()[:160]}")
