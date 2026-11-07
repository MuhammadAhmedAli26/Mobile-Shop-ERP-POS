# Script to clean all dummy transactions and stock data for a fresh production launch
import db, sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

CLEAN_TABLES = [
    'products', 'variants', 'units', 'stock_ledger',
    'suppliers', 'supplier_ledger', 'purchases', 'purchase_items',
    'customers', 'sales', 'sale_items', 'returns', 'return_items',
    'trade_ins', 'udhaar_ledger', 'installments', 'installment_schedule',
    'software_jobs', 'repair_jobs', 'repair_parts_used',
    'expenses', 'quick_services', 'day_closings', 'audit_log',
    'sales_daily_by_variant', 'stock_alert_log', 'stock_alert_state', 'idempotency_keys'
]

def purge_dummy_data():
    import auth, datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    h_admin = auth.hash_password("admin123")
    h_staff = auth.hash_password("staff123")
    rec_key = "7A4K-9M2X-8P1Q-3N6R-5V8W-2T9Y"
    h_rec = auth.hash_password(rec_key)
    h_pin = auth.hash_password("9999")

    with db.transaction() as cx:
        for t in CLEAN_TABLES:
            cx.execute(f"DELETE FROM {t};")
        # Reset AUTOINCREMENT sequences
        placeholders = ",".join("?" for _ in CLEAN_TABLES)
        cx.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders});", CLEAN_TABLES)

        # Purge temporary/test users
        cx.execute("DELETE FROM users WHERE username NOT IN ('admin', 'staff')")

        # Upsert admin user
        cx.execute("""
            INSERT INTO users (id, username, password_hash, role, full_name, is_active, permissions, created_at)
            VALUES (1, 'admin', ?, 'ADMIN', 'Master Admin', 1, '{"all": true}', ?)
            ON CONFLICT(id) DO UPDATE SET
                username = 'admin',
                password_hash = excluded.password_hash,
                role = 'ADMIN',
                is_active = 1,
                must_change_password = 0,
                updated_at = excluded.created_at
        """, (h_admin, now))

        # Upsert counter staff user
        cx.execute("""
            INSERT INTO users (id, username, password_hash, role, full_name, is_active, permissions, created_at)
            VALUES (2, 'staff', ?, 'EMPLOYEE', 'Counter Salesman', 1, '{"pos": true, "inventory_view": true, "sales_view": true}', ?)
            ON CONFLICT(id) DO UPDATE SET
                username = 'staff',
                password_hash = excluded.password_hash,
                role = 'EMPLOYEE',
                is_active = 1,
                must_change_password = 0,
                updated_at = excluded.created_at
        """, (h_staff, now))

        # Update recovery key and PIN settings
        settings_to_set = [
            ('admin_recovery_key_hash', h_rec),
            ('admin_override_pin_hash', h_pin),
            ('admin_pin', '9999'),
            ('setup_completed', '1'),
            ('shop_name', 'PAK MOBILE & ACCESSORIES'),
        ]
        for k, v in settings_to_set:
            cx.execute("""
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (k, v, now))

    with db.get_connection() as cx:
        cx.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    
    print("=" * 60)
    print("🧹 DATABASE PURGE COMPLETE: FULL CLEAN FRESH ERP STATE")
    print("=" * 60)
    for t in CLEAN_TABLES:
        c = db.query_one(f"SELECT COUNT(*) as c FROM {t}")["c"]
        print(f"  • {t:<22}: {c} records")
        assert c == 0
    print("\n" + "=" * 60)
    print("🔑 FRESH PRODUCTION CREDENTIALS & KEYS:")
    print("=" * 60)
    print("  • Master Admin Username : admin")
    print("  • Master Admin Password : admin123")
    print("  • Counter Staff Username: staff")
    print("  • Counter Staff Password: staff123")
    print("  • Admin Override PIN    : 9999")
    print(f"  • Master Recovery Key   : {rec_key}")
    print("=" * 60)
    print("✓ System lookups, settings, admin users, and software catalog preserved.")
    print("✓ Ready for fresh shop operation with 0 dummy records.")

if __name__ == "__main__":
    purge_dummy_data()
