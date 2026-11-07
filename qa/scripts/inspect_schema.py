import sqlite3, json, sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "mobile_erp.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== sale_items columns ===")
c.execute("PRAGMA table_info(sale_items)")
cols = c.fetchall()
for col in cols:
    print(f"  {col['name']} {col['type']}")

print("\n=== sales columns ===")
c.execute("PRAGMA table_info(sales)")
for col in c.fetchall():
    print(f"  {col['name']} {col['type']}")

print("\n=== Stock mismatch details ===")
c.execute("""
    SELECT v.id, v.stock_quantity,
           COUNT(u.id) AS real_count,
           p.brand, p.name, v.ram, v.storage, v.color
    FROM variants v
    JOIN products p ON v.product_id = p.id
    LEFT JOIN units u ON u.variant_id = v.id AND u.status = 'IN_STOCK'
    GROUP BY v.id
    HAVING v.stock_quantity != real_count
    LIMIT 20
""")
for row in c.fetchall():
    print(f"  variant {row['id']}: {row['brand']} {row['name']} {row['ram']}/{row['storage']} {row['color']} => stock_qty={row['stock_quantity']}, actual_in_stock={row['real_count']}")

conn.close()
