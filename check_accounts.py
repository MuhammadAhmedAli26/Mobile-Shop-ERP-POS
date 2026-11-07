import db

for tbl in ["expenses", "purchases", "supplier_ledger", "credit_ledger", "customer_ledger", "day_closings"]:
    try:
        cols = db.query_all(f"PRAGMA table_info({tbl})")
        print(f"=== {tbl} ===")
        print([c["name"] for c in cols])
    except Exception as e:
        print(f"=== {tbl} error: {e} ===")
