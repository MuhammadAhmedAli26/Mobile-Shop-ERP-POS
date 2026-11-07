import sqlite3
import os
import sys
import shutil

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import config
import auth

TABLES_TO_TRUNCATE = [
    "products",
    "variants",
    "units",
    "stock_ledger",
    "stock_alert_state",
    "stock_alert_log",
    "sales_daily_by_variant",
    "suppliers",
    "supplier_ledger",
    "purchases",
    "purchase_items",
    "customers",
    "sales",
    "sale_items",
    "returns",
    "return_items",
    "trade_ins",
    "udhaar_ledger",
    "installments",
    "installment_schedule",
    "software_jobs",
    "repair_jobs",
    "repair_parts_used",
    "expenses",
    "quick_services",
    "day_closings",
    "audit_log",
    "idempotency_keys",
]

def clean_database(db_path):
    if not os.path.exists(db_path):
        print(f"[SKIP] DB does not exist: {db_path}")
        return False

    print(f"\n==================================================")
    print(f"Cleaning database: {db_path}")
    print(f"==================================================")

    # Backup prior to wipe
    backup_path = db_path + ".before_fresh_clean.bak"
    shutil.copy2(db_path, backup_path)
    print(f"✓ Backup created at: {backup_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Disable foreign keys temporarily during wipe
    cur.execute("PRAGMA foreign_keys = OFF;")

    # 1. Truncate operational & dummy tables
    for tbl in TABLES_TO_TRUNCATE:
        try:
            cur.execute(f"DELETE FROM {tbl};")
            print(f"✓ Cleared table: {tbl}")
        except sqlite3.OperationalError as e:
            print(f"- Note on {tbl}: {e}")

    # 2. Reset sqlite_sequence for wiped tables
    try:
        for tbl in TABLES_TO_TRUNCATE:
            cur.execute("DELETE FROM sqlite_sequence WHERE name = ?;", (tbl,))
        print("✓ Reset auto-increment sequence counters.")
    except Exception as e:
        print(f"- sqlite_sequence note: {e}")

    # 3. Clean users table: keep only admin and staff with standard credentials
    cur.execute("DELETE FROM users WHERE username NOT IN ('admin', 'staff');")
    now = "2026-10-12 00:00:00"
    admin_pw_hash = auth.hash_password("admin123")
    staff_pw_hash = auth.hash_password("staff123")

    cur.execute("""
        INSERT INTO users (id, username, password_hash, role, full_name, is_active, permissions, created_at)
        VALUES (1, 'admin', ?, 'ADMIN', 'Master Admin', 1, '{"all": true}', ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            role = 'ADMIN',
            full_name = 'Master Admin',
            is_active = 1,
            permissions = '{"all": true}';
    """, (admin_pw_hash, now))

    cur.execute("""
        INSERT INTO users (id, username, password_hash, role, full_name, is_active, permissions, created_at)
        VALUES (2, 'staff', ?, 'EMPLOYEE', 'Counter Salesman', 1, '{"pos": true, "inventory_view": true, "sales_view": true}', ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            role = 'EMPLOYEE',
            full_name = 'Counter Salesman',
            is_active = 1,
            permissions = '{"pos": true, "inventory_view": true, "sales_view": true}';
    """, (staff_pw_hash, now))
    print("✓ Users reset to clean standard 'admin' and 'staff' accounts.")

    # 4. Reset Code Counters
    code_seeds = [("ACC", 100), ("PHN", 100), ("PRT", 100), ("VAR", 100), ("BAR", 100000)]
    for prefix, initial in code_seeds:
        cur.execute("""
            INSERT INTO code_counters (prefix, last_val) VALUES (?, ?)
            ON CONFLICT(prefix) DO UPDATE SET last_val = excluded.last_val;
        """, (prefix, initial))
    print("✓ Reset barcode and code counters to defaults.")

    # 5. Reset change feed versions
    feed_groups = ["items", "stock", "prices", "customers", "lists", "users", "settings", "profile"]
    for g in feed_groups:
        cur.execute("""
            INSERT INTO change_feed_versions (group_name, version, updated_at) VALUES (?, 1, ?)
            ON CONFLICT(group_name) DO UPDATE SET version = 1, updated_at = excluded.updated_at;
        """, (g, now))
    print("✓ Reset change feed versions to 1.")

    # 6. Mark setup_completed = 1 and set recovery credentials
    h_rec = auth.hash_password("7A4K-9M2X-8P1Q-3N6R-5V8W-2T9Y")
    h_pin = auth.hash_password("9999")
    settings_to_set = [
        ('setup_completed', '1'),
        ('admin_recovery_key_hash', h_rec),
        ('admin_override_pin_hash', h_pin),
        ('admin_pin', '9999'),
        ('shop_name', 'PAK MOBILE & ACCESSORIES'),
    ]
    for k, v in settings_to_set:
        cur.execute("""
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
        """, (k, v, now))
    print("✓ Reset shop settings and recovery keys.")

    # Commit all changes and re-enable foreign keys
    conn.commit()
    cur.execute("PRAGMA foreign_keys = ON;")

    # Checkpoint WAL and VACUUM
    try:
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        cur.execute("VACUUM;")
        print("✓ Database vacuumed and WAL truncated.")
    except Exception as e:
        print(f"- Note on vacuum: {e}")

    conn.close()

    # Remove temporary WAL/SHM files
    for ext in ['-wal', '-shm']:
        wp = db_path + ext
        if os.path.exists(wp):
            try:
                os.remove(wp)
            except Exception:
                pass
    return True

def clean_session_data(session_dir):
    if os.path.exists(session_dir):
        try:
            for item in os.listdir(session_dir):
                p = os.path.join(session_dir, item)
                if os.path.isfile(p):
                    os.remove(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            print(f"✓ Cleared session cache in: {session_dir}")
        except Exception as e:
            print(f"- Session clean note: {e}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_db = os.path.join(base_dir, "mobile_erp.db")
    clean_database(workspace_db)

    # Copy clean DB to all package and distribution locations
    target_dbs = [
        os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MobileShopERP", "mobile_erp.db"),
        os.path.join(base_dir, "dist", "MobileShopERP", "_internal", "mobile_erp.db"),
        os.path.join(base_dir, "release", "MobileShopERP", "_internal", "mobile_erp.db"),
        os.path.join(base_dir, "MobileShopERP", "_internal", "mobile_erp.db"),
        os.path.join(base_dir, "MobileShopERP", "MobileShopERP", "_internal", "mobile_erp.db"),
    ]

    for tdb in target_dbs:
        if os.path.exists(os.path.dirname(tdb)):
            try:
                # Backup if exists
                if os.path.exists(tdb):
                    shutil.copy2(tdb, tdb + ".bak")
                shutil.copy2(workspace_db, tdb)
                print(f"✓ Synced clean DB to: {tdb}")
                # Remove wal/shm
                for ext in ['-wal', '-shm']:
                    wp = tdb + ext
                    if os.path.exists(wp):
                        os.remove(wp)
            except Exception as e:
                print(f"- Note syncing {tdb}: {e}")

    # Clean session data in both
    clean_session_data(os.path.join(base_dir, "session_data"))
    clean_session_data(os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MobileShopERP", "session_data"))

    print("\n✅ All databases and session caches are now 100% fresh and clean!")

