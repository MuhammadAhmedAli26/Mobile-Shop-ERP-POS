import re

with open("web_ui.py", encoding="utf-8") as f:
    content = f.read()

print("Searching for product / variant screens in web_ui.py...")
matches = re.findall(r'def ([a-zA-Z0-9_]+)\([^)]*\):', content)
for fn in matches:
    if any(k in fn.lower() for k in ['variant', 'product', 'unit', 'model', 'inventory']):
        print("  -", fn)
