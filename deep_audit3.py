import re, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('web_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()
lines = content.split('\n')

# 1. Check how returns are submitted
print("=== RETURNS: How form is submitted ===")
in_returns = False
ret_lines = []
for i, line in enumerate(lines):
    if 'returns_screen' in line or 'returns screen' in line.lower() or "'/returns'" in line or '"/returns"' in line:
        in_returns = True
    if in_returns and ('form' in line.lower() or 'onclick' in line.lower() or 'submit' in line.lower() or 'process' in line.lower()):
        ret_lines.append((i+1, line.strip()[:150]))
    if in_returns and i > 0 and 'def ' in line and 'returns' not in line.lower() and len(ret_lines) > 5:
        break
for ln, l in ret_lines[:30]:
    print(f"  Line {ln}: {l}")

# 2. How does POS handle udhaar payment type
print("\n=== POS: Payment type selector in checkout ===")
for i, line in enumerate(lines):
    if 'payment_type' in line.lower() or 'pay_type' in line.lower() or 'udhaar' in line.lower():
        if 2500 < i < 2600:  # around checkout area
            print(f"  Line {i+1}: {line.strip()[:150]}")

# 3. Check if /returns/process properly adds to sales history
print("\n=== Returns process route ===")
in_proc = False
for i, line in enumerate(lines):
    if '@app.route("/returns/process"' in line or "@app.route('/returns/process'" in line:
        in_proc = True
    if in_proc:
        print(f"  Line {i+1}: {line[:150]}")
        if i > 0 and 'def ' in line and 'return' not in line.lower() and in_proc and i > (i+2):
            break
        if in_proc and line.strip() == '' and i > 100:
            in_proc_count = getattr(in_proc, 'count', 0)
        # print 50 lines of this function
        if in_proc and line.startswith('def ') and 'process' not in line:
            break
    if in_proc and i > 8900:
        break

# 4. Check credit.py for udhaar add-to-history
print("\n=== credit.py: Does pay_udhaar update sales history? ===")
with open('credit.py', 'r', encoding='utf-8') as f:
    credit = f.read()
credit_lines = credit.split('\n')
for i, line in enumerate(credit_lines):
    if 'sales' in line.lower() or 'history' in line.lower() or 'udhaar_ledger' in line.lower():
        print(f"  Line {i+1}: {line.strip()[:150]}")

# 5. Check if POS checkout saves to udhaar when payment_type = udhaar
print("\n=== POS checkout: udhaar saving ===")
with open('pos.py', 'r', encoding='utf-8') as f:
    pos = f.read()
pos_lines = pos.split('\n')
for i, line in enumerate(pos_lines):
    if 'udhaar' in line.lower() or 'credit' in line.lower():
        print(f"  Line {i+1}: {line.strip()[:150]}")
