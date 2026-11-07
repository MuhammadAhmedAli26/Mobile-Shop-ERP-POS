import glob, re

patterns = [
    r"payment_method",
    r"payment_account",
    r"paid_from_account",
    r"LIKE '%CASH%'",
    r"= 'CASH'",
    r"== 'CASH'",
    r"in \('CASH'",
]

for py_file in glob.glob("*.py"):
    with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    found = []
    for i, line in enumerate(lines):
        if any(re.search(p, line, re.IGNORECASE) for p in patterns):
            found.append((i + 1, line.strip()))
    if found:
        print(f"=== {py_file} ({len(found)} matches) ===")
        for line_no, text in found[:15]:
            print(f"  L{line_no}: {text}")
