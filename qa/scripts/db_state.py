import sqlite3, json, sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "mobile_erp.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== Row counts in all tables ===")
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
for t in tables:
    try:
        c.execute(f"SELECT COUNT(*) FROM [{t}]")
        cnt = c.fetchone()[0]
        if cnt > 0:
            print(f"  {t}: {cnt} rows")
    except Exception as e:
        print(f"  {t}: ERROR {e}")

print("\n=== PHONE variants with unit mismatches ===")
c.execute("""
    SELECT v.id, v.stock_quantity,
           COUNT(u.id) AS real_count,
           p.item_type
    FROM variants v
    JOIN products p ON v.product_id = p.id
    LEFT JOIN units u ON u.variant_id = v.id AND u.status = 'IN_STOCK'
    WHERE p.item_type = 'PHONE'
    GROUP BY v.id
    HAVING v.stock_quantity != real_count
""")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  PHONE variant {r['id']}: stock_qty={r['stock_quantity']}, real_count={r['real_count']}")
else:
    print("  None (all PHONE variants match)")

print("\n=== Accessories WITH units (should be 0) ===")
c.execute("""
    SELECT COUNT(*) FROM variants v
    JOIN products p ON v.product_id = p.id
    JOIN units u ON u.variant_id = v.id
    WHERE p.item_type != 'PHONE'
""")
print(f"  Accessory units: {c.fetchone()[0]}")

conn.close()
