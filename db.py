# MOBILE & ACCESSORIES ERP — High Performance SQLite Layer (WAL + Indexing)
import sqlite3, os, hashlib, json
from datetime import datetime
from contextlib import contextmanager
import config

def get_connection():
    cx = sqlite3.connect(config.DATABASE_NAME, check_same_thread=False, timeout=30.0)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL")
    cx.execute("PRAGMA synchronous=NORMAL")
    cx.execute("PRAGMA busy_timeout=5000")
    cx.execute("PRAGMA foreign_keys=ON")
    cx.execute("PRAGMA cache_size=-64000")
    cx.execute("PRAGMA temp_store=MEMORY")
    cx.execute("PRAGMA mmap_size=134217728")
    return cx

@contextmanager
def transaction(max_retries=3):
    import time
    last_err = None
    for attempt in range(max_retries):
        cx = get_connection()
        try:
            yield cx
            cx.commit()
            return
        except sqlite3.OperationalError as oe:
            cx.rollback()
            last_err = oe
            if "locked" in str(oe).lower() or "busy" in str(oe).lower():
                time.sleep(0.05 * (2 ** attempt))
                continue
            raise
        except Exception:
            cx.rollback()
            raise
        finally:
            cx.close()
    if last_err:
        raise last_err

def query_one(sql, params=()):
    with get_connection() as cx:
        cur = cx.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

def query_all(sql, params=()):
    with get_connection() as cx:
        cur = cx.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

def execute(sql, params=()):
    with get_connection() as cx:
        cur = cx.execute(sql, params)
        cx.commit()
        return cur.lastrowid

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'EMPLOYEE',
        full_name TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        permissions TEXT DEFAULT '{}',
        created_at TEXT,
        last_login TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 0,
        username TEXT DEFAULT '',
        action TEXT NOT NULL,
        entity TEXT DEFAULT '',
        entity_id TEXT DEFAULT '',
        old_value TEXT DEFAULT '',
        new_value TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        timestamp TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT NOT NULL,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'Smartphone',
        item_type TEXT NOT NULL DEFAULT 'PHONE', -- PHONE, SERIAL, ACCESSORY, SPARE_PART
        image_url TEXT DEFAULT '',
        default_warranty_months INTEGER DEFAULT 12,
        compatible_models TEXT DEFAULT '', -- E.g. for accessories: 'iPhone 13, iPhone 14'
        notes TEXT DEFAULT '',
        is_archived INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS variants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        ram TEXT DEFAULT '',
        storage TEXT DEFAULT '',
        color TEXT DEFAULT '',
        network TEXT DEFAULT '', -- 4G, 5G
        sku TEXT DEFAULT '',
        barcode TEXT DEFAULT '',
        retail_price REAL DEFAULT 0,
        wholesale_price REAL DEFAULT 0,
        min_selling_price REAL DEFAULT 0,
        stock_quantity INTEGER DEFAULT 0, -- Used directly for ACCESSORY & SPARE_PART
        reorder_level INTEGER DEFAULT 5,
        is_archived INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id INTEGER NOT NULL,
        imei1 TEXT UNIQUE,
        imei2 TEXT UNIQUE,
        serial_no TEXT UNIQUE,
        condition TEXT DEFAULT 'NEW_BOX_PACK', -- NEW_BOX_PACK, OPEN_BOX, USED, REFURBISHED
        pta_status TEXT DEFAULT 'PTA_APPROVED', -- PTA_APPROVED, NON_PTA, JV, OFFICIAL, FACTORY_UNLOCKED
        cost_price REAL DEFAULT 0,
        supplier_id INTEGER DEFAULT 0,
        purchase_ref TEXT DEFAULT '',
        purchase_id INTEGER DEFAULT 0,
        date_in TEXT,
        battery_health INTEGER DEFAULT 100,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'IN_STOCK', -- IN_STOCK, SOLD, IN_REPAIR, DEFECTIVE, RETURNED_TO_SUPPLIER
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(variant_id) REFERENCES variants(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS stock_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER DEFAULT 0,
        variant_id INTEGER DEFAULT 0,
        unit_id INTEGER DEFAULT 0,
        imei TEXT DEFAULT '',
        item_type TEXT DEFAULT '',
        change_qty INTEGER NOT NULL,
        balance_qty INTEGER DEFAULT 0,
        action_type TEXT NOT NULL, -- PURCHASE, SALE, RETURN, EDIT, ADJUST, TRADE_IN, REPAIR_USE
        reference TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        email TEXT DEFAULT '',
        company TEXT DEFAULT '',
        total_purchased REAL DEFAULT 0,
        total_paid REAL DEFAULT 0,
        balance REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        is_archived INTEGER DEFAULT 0,
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS supplier_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        transaction_type TEXT NOT NULL, -- PURCHASE, PAYMENT, RETURN
        amount REAL NOT NULL,
        balance_after REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'CASH',
        reference TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        supplier_id INTEGER NOT NULL,
        supplier_name TEXT DEFAULT '',
        total_amount REAL DEFAULT 0,
        paid_amount REAL DEFAULT 0,
        balance_amount REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'CASH',
        status TEXT DEFAULT 'RECEIVED',
        purchase_date TEXT NOT NULL,
        notes TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL,
        variant_id INTEGER NOT NULL,
        item_type TEXT DEFAULT 'PHONE',
        qty INTEGER NOT NULL,
        unit_cost REAL DEFAULT 0,
        total_cost REAL DEFAULT 0,
        imeis_json TEXT DEFAULT '[]',
        created_at TEXT,
        FOREIGN KEY(purchase_id) REFERENCES purchases(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        cnic TEXT DEFAULT '',
        address TEXT DEFAULT '',
        total_purchases REAL DEFAULT 0,
        total_paid REAL DEFAULT 0,
        balance_udhaar REAL DEFAULT 0,
        notes TEXT DEFAULT '',
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        customer_id INTEGER DEFAULT 0,
        customer_name TEXT DEFAULT 'Walk-in Customer',
        customer_phone TEXT DEFAULT '',
        subtotal REAL DEFAULT 0,
        discount_amount REAL DEFAULT 0,
        discount_percent REAL DEFAULT 0,
        tax_amount REAL DEFAULT 0,
        tax_percent REAL DEFAULT 0,
        grand_total REAL DEFAULT 0,
        paid_amount REAL DEFAULT 0,
        change_amount REAL DEFAULT 0,
        balance_due REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'CASH', -- CASH, CARD, ONLINE, SPLIT, CREDIT, INSTALLMENT, TRADE_IN
        split_details TEXT DEFAULT '',
        trade_in_id INTEGER DEFAULT 0,
        salesperson_id INTEGER DEFAULT 0,
        salesperson_name TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'COMPLETED', -- COMPLETED, EDITED, CANCELLED, RETURNED
        created_at TEXT,
        updated_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        variant_id INTEGER NOT NULL,
        unit_id INTEGER DEFAULT 0,
        item_type TEXT DEFAULT 'PHONE',
        item_name TEXT NOT NULL,
        variant_details TEXT DEFAULT '',
        imei1 TEXT DEFAULT '',
        imei2 TEXT DEFAULT '',
        qty INTEGER DEFAULT 1,
        unit_price REAL DEFAULT 0,
        cost_price REAL DEFAULT 0,
        discount REAL DEFAULT 0,
        line_total REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        warranty_till TEXT DEFAULT '',
        is_returned INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS returns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        return_no TEXT UNIQUE NOT NULL,
        sale_id INTEGER NOT NULL,
        invoice_no TEXT NOT NULL,
        customer_id INTEGER DEFAULT 0,
        customer_name TEXT DEFAULT '',
        refund_amount REAL DEFAULT 0,
        refund_type TEXT DEFAULT 'CASH', -- CASH, CREDIT_NOTE, EXCHANGE
        reason TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        return_date TEXT NOT NULL,
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS return_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        return_id INTEGER NOT NULL,
        sale_item_id INTEGER NOT NULL,
        variant_id INTEGER NOT NULL,
        unit_id INTEGER DEFAULT 0,
        imei TEXT DEFAULT '',
        qty INTEGER DEFAULT 1,
        refund_amount REAL DEFAULT 0,
        return_action TEXT DEFAULT 'RESTOCK', -- RESTOCK, DEFECTIVE, REPAIR
        created_at TEXT,
        FOREIGN KEY(return_id) REFERENCES returns(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS trade_ins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_in_no TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT DEFAULT '',
        customer_cnic TEXT DEFAULT '',
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        imei1 TEXT UNIQUE NOT NULL,
        condition TEXT DEFAULT 'USED',
        battery_health INTEGER DEFAULT 80,
        purchase_price REAL DEFAULT 0,
        unit_id INTEGER DEFAULT 0,
        linked_sale_id INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS udhaar_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        sale_id INTEGER DEFAULT 0,
        transaction_type TEXT NOT NULL, -- SALE_CREDIT, PAYMENT, ADJUSTMENT
        amount REAL NOT NULL,
        balance_after REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'CASH',
        notes TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS installments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        total_price REAL NOT NULL,
        down_payment REAL NOT NULL,
        financed_amount REAL NOT NULL,
        total_months INTEGER NOT NULL,
        monthly_due REAL NOT NULL,
        start_date TEXT NOT NULL,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'ACTIVE', -- ACTIVE, COMPLETED, DEFAULTED
        created_at TEXT,
        FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS installment_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        installment_id INTEGER NOT NULL,
        installment_no INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        due_amount REAL NOT NULL,
        paid_amount REAL DEFAULT 0,
        paid_date TEXT DEFAULT '',
        status TEXT DEFAULT 'PENDING', -- PENDING, PAID, OVERDUE
        receipt_no TEXT DEFAULT '',
        FOREIGN KEY(installment_id) REFERENCES installments(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS software_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        default_price REAL DEFAULT 0,
        default_cost REAL DEFAULT 0,
        is_active INTEGER DEFAULT 1
    );""",

    """CREATE TABLE IF NOT EXISTS software_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_no TEXT UNIQUE NOT NULL,
        customer_name TEXT DEFAULT '',
        customer_phone TEXT DEFAULT '',
        customer_cnic TEXT DEFAULT '',
        brand_model TEXT NOT NULL,
        imei TEXT DEFAULT '',
        service_id INTEGER DEFAULT 0,
        service_name TEXT NOT NULL,
        price_charged REAL DEFAULT 0,
        tool_server_cost REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'CASH',
        technician_id INTEGER DEFAULT 0,
        technician_name TEXT DEFAULT '',
        owner_confirmed INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'COMPLETED', -- COMPLETED, CANCELLED
        created_at TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS repair_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_no TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        imei TEXT DEFAULT '',
        accessories_received TEXT DEFAULT '',
        complaint TEXT NOT NULL,
        estimate REAL DEFAULT 0,
        advance_paid REAL DEFAULT 0,
        balance_due REAL DEFAULT 0,
        technician_id INTEGER DEFAULT 0,
        technician_name TEXT DEFAULT '',
        outsourced_cost REAL DEFAULT 0,
        labor_charge REAL DEFAULT 0,
        parts_cost REAL DEFAULT 0,
        total_charged REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        warranty_days INTEGER DEFAULT 30,
        expected_delivery TEXT DEFAULT '',
        status TEXT DEFAULT 'RECEIVED', -- RECEIVED, DIAGNOSING, WAITING_PARTS, IN_REPAIR, READY, DELIVERED, RETURNED_UNREPAIRED, CANCELLED
        delivered_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS repair_parts_used (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repair_id INTEGER NOT NULL,
        spare_variant_id INTEGER DEFAULT 0,
        part_name TEXT NOT NULL,
        qty INTEGER DEFAULT 1,
        cost_price REAL DEFAULT 0,
        charge_price REAL DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(repair_id) REFERENCES repair_jobs(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        description TEXT DEFAULT '',
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'CASH',
        reference TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        expense_date TEXT NOT NULL,
        is_recurring INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS quick_services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_type TEXT NOT NULL, -- LOAD, JAZZCASH, EASYPAISA, SIM
        network TEXT DEFAULT '',
        customer_phone TEXT DEFAULT '',
        amount REAL NOT NULL,
        fee_commission REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        agent_id INTEGER DEFAULT 0,
        notes TEXT DEFAULT '',
        timestamp TEXT NOT NULL,
        action_type TEXT DEFAULT 'SEND', -- SEND (Cash-in), RECEIVE (Cash-out), LOAD, BILL, SIM
        payment_method TEXT DEFAULT 'CASH'
    );""",

    """CREATE TABLE IF NOT EXISTS day_closings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        closing_date TEXT UNIQUE NOT NULL,
        opened_at TEXT,
        closed_at TEXT,
        opening_cash REAL DEFAULT 0,
        cash_sales REAL DEFAULT 0,
        card_sales REAL DEFAULT 0,
        online_sales REAL DEFAULT 0,
        udhaar_sales REAL DEFAULT 0,
        udhaar_received REAL DEFAULT 0,
        repair_income REAL DEFAULT 0,
        software_income REAL DEFAULT 0,
        quick_service_income REAL DEFAULT 0,
        expenses_total REAL DEFAULT 0,
        supplier_payments REAL DEFAULT 0,
        expected_cash REAL DEFAULT 0,
        actual_cash REAL DEFAULT 0,
        cash_difference REAL DEFAULT 0,
        closed_by_id INTEGER DEFAULT 0,
        closed_by_name TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS lookup_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_key TEXT NOT NULL,
        label TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        is_system INTEGER DEFAULT 0,
        default_low_stock_level INTEGER DEFAULT NULL,
        default_reorder_qty INTEGER DEFAULT NULL,
        created_by INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS stock_alert_state (
        variant_id INTEGER PRIMARY KEY,
        product_id INTEGER NOT NULL,
        current_stock INTEGER NOT NULL DEFAULT 0,
        effective_level INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'OK', -- 'OK', 'LOW', 'OUT', 'OFF'
        snoozed_until TEXT DEFAULT NULL,
        on_order_qty INTEGER DEFAULT 0,
        on_order_date TEXT DEFAULT NULL,
        on_order_notes TEXT DEFAULT '',
        last_transition_at TEXT,
        last_notified_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(variant_id) REFERENCES variants(id) ON DELETE CASCADE
    );""",

    """CREATE TABLE IF NOT EXISTS stock_alert_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        from_state TEXT NOT NULL,
        to_state TEXT NOT NULL,
        stock_at_transition INTEGER NOT NULL,
        effective_level INTEGER NOT NULL,
        action_trigger TEXT NOT NULL, -- 'SALE', 'RETURN', 'ADJUSTMENT', 'PURCHASE', 'MANUAL_LEVEL_CHANGE'
        reference TEXT DEFAULT '',
        user_id INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS sales_daily_by_variant (
        date TEXT NOT NULL,
        variant_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        brand TEXT NOT NULL,
        units_sold INTEGER NOT NULL DEFAULT 0,
        gross_revenue REAL NOT NULL DEFAULT 0.0,
        cost_total REAL NOT NULL DEFAULT 0.0,
        units_returned INTEGER NOT NULL DEFAULT 0,
        net_profit REAL NOT NULL DEFAULT 0.0,
        PRIMARY KEY (date, variant_id)
    );""",

    """CREATE TABLE IF NOT EXISTS code_counters (
        prefix TEXT PRIMARY KEY,
        last_val INTEGER NOT NULL DEFAULT 0
    );""",

    """CREATE TABLE IF NOT EXISTS idempotency_keys (
        request_id TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS shop_profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        shop_name TEXT NOT NULL DEFAULT 'PAK MOBILE & ACCESSORIES',
        tagline TEXT DEFAULT 'Smartphones, Accessories & Repairs',
        address TEXT DEFAULT 'Shop # 15, Ground Floor, Hafeez Center, Main Boulevard, Gulberg III, Lahore',
        city TEXT DEFAULT 'Lahore',
        phone1 TEXT DEFAULT '+92 300 1234567',
        phone2 TEXT DEFAULT '',
        whatsapp TEXT DEFAULT '+92 300 1234567',
        email TEXT DEFAULT '',
        ntn_tax_no TEXT DEFAULT '',
        receipt_footer TEXT DEFAULT 'Thank you for your visit!',
        warranty_terms TEXT DEFAULT '1 Year Brand Warranty for Official Phones. 7 Days Checking Warranty for Used Phones.',
        return_policy TEXT DEFAULT '7 Days checking return policy with original receipt.',
        has_logo INTEGER DEFAULT 0,
        logo_mime TEXT DEFAULT '',
        logo_data BLOB,
        logo_thermal_80 BLOB,
        logo_thermal_58 BLOB,
        profile_version INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS change_feed_versions (
        group_name TEXT PRIMARY KEY,
        version INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT
    );"""
]

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_units_imei1 ON units(imei1);",
    "CREATE INDEX IF NOT EXISTS idx_units_imei2 ON units(imei2);",
    "CREATE INDEX IF NOT EXISTS idx_units_status ON units(status);",
    "CREATE INDEX IF NOT EXISTS idx_units_variant ON units(variant_id);",
    "CREATE INDEX IF NOT EXISTS idx_units_imei1_tail ON units(imei1_tail);",
    "CREATE INDEX IF NOT EXISTS idx_units_imei2_tail ON units(imei2_tail);",
    "CREATE INDEX IF NOT EXISTS idx_variants_sku ON variants(sku);",
    "CREATE INDEX IF NOT EXISTS idx_variants_barcode ON variants(barcode);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_variants_barcode_uniq ON variants(barcode) WHERE barcode IS NOT NULL AND barcode != '';",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_variants_sku_uniq ON variants(sku) WHERE sku IS NOT NULL AND sku != '';",
    "CREATE INDEX IF NOT EXISTS idx_variants_prod ON variants(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);",
    "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);",
    "CREATE INDEX IF NOT EXISTS idx_products_type ON products(item_type);",
    "CREATE INDEX IF NOT EXISTS idx_sales_inv ON sales(invoice_no);",
    "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sales_phone ON sales(customer_phone);",
    "CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(sale_id);",
    "CREATE INDEX IF NOT EXISTS idx_sale_items_imei ON sale_items(imei1);",
    "CREATE INDEX IF NOT EXISTS idx_repair_jobno ON repair_jobs(job_no);",
    "CREATE INDEX IF NOT EXISTS idx_repair_imei ON repair_jobs(imei);",
    "CREATE INDEX IF NOT EXISTS idx_repair_status ON repair_jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_software_ticket ON software_jobs(ticket_no);",
    "CREATE INDEX IF NOT EXISTS idx_software_imei ON software_jobs(imei);",
    "CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);",
    "CREATE INDEX IF NOT EXISTS idx_suppliers_phone ON suppliers(phone);",
    "CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON stock_ledger(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_lookup_key_active ON lookup_lists(list_key, is_active);",
    "CREATE INDEX IF NOT EXISTS idx_lookup_key_label ON lookup_lists(list_key, label);",
    "CREATE INDEX IF NOT EXISTS idx_stock_alert_state_state ON stock_alert_state(state);",
    "CREATE INDEX IF NOT EXISTS idx_stock_alert_state_prod ON stock_alert_state(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_alert_log_variant ON stock_alert_log(variant_id);",
    "CREATE INDEX IF NOT EXISTS idx_alert_log_time ON stock_alert_log(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_sales_daily_cat ON sales_daily_by_variant(category, date);",
    "CREATE INDEX IF NOT EXISTS idx_sales_daily_brand ON sales_daily_by_variant(brand, date);",
    "CREATE INDEX IF NOT EXISTS idx_sales_daily_prod ON sales_daily_by_variant(product_id, date);",
    "CREATE INDEX IF NOT EXISTS idx_sales_trans_date ON sales(transaction_date);",
    "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);",
    "CREATE INDEX IF NOT EXISTS idx_returns_date ON returns(return_date);"
]

def backup_database(label="auto"):
    try:
        if os.path.exists(config.DATABASE_NAME):
            os.makedirs(config.BACKUP_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(config.BACKUP_DIR, f"mobile_erp_{label}_{ts}.db")
            import shutil
            shutil.copy2(config.DATABASE_NAME, backup_path)
            return backup_path
    except Exception as e:
        print(f"[DB WARNING] Auto-backup failed: {e}")
    return None

def init_db():
    backup_database("migration")
    with transaction() as cx:
        cur = cx.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)

        # Ensure dynamic columns exist before creating indexes
        for col in ["imei1_tail", "imei2_tail"]:
            try:
                cur.execute(f"ALTER TABLE units ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass

        try:
            cur.execute("ALTER TABLE sales ADD COLUMN trade_in_id INTEGER DEFAULT 0")
        except Exception:
            pass

        for col in ["guarantor1_name", "guarantor1_phone", "guarantor1_cnic", "guarantor2_name", "guarantor2_phone", "guarantor2_cnic"]:
            try:
                cur.execute(f"ALTER TABLE installments ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass

        # Low Stock Alert & Reorder Dynamic Columns
        for tbl, col_def in [
            ("lookup_lists", "default_low_stock_level INTEGER DEFAULT NULL"),
            ("lookup_lists", "default_reorder_qty INTEGER DEFAULT NULL"),
            ("lookup_lists", "account_type TEXT DEFAULT 'CASH'"),
            ("day_closings", "modified_after_closing INTEGER DEFAULT 0"),
            ("day_closings", "refunds REAL DEFAULT 0.0"),
            ("day_closings", "cash_expenses_total REAL DEFAULT 0.0"),
            ("day_closings", "non_cash_expenses_total REAL DEFAULT 0.0"),
            ("sales", "transaction_date TEXT DEFAULT ''"),
            ("purchases", "transaction_date TEXT DEFAULT ''"),
            ("expenses", "transaction_date TEXT DEFAULT ''"),
            ("stock_ledger", "transaction_date TEXT DEFAULT ''"),
            ("sales", "recorded_at TEXT DEFAULT ''"),
            ("purchases", "recorded_at TEXT DEFAULT ''"),
            ("expenses", "recorded_at TEXT DEFAULT ''"),
            ("stock_ledger", "recorded_at TEXT DEFAULT ''"),
            ("sales", "backdate_reason TEXT DEFAULT ''"),
            ("purchases", "backdate_reason TEXT DEFAULT ''"),
            ("expenses", "backdate_reason TEXT DEFAULT ''"),
            ("supplier_ledger", "transaction_date TEXT DEFAULT ''"),
            ("supplier_ledger", "recorded_at TEXT DEFAULT ''"),
            ("supplier_ledger", "backdate_reason TEXT DEFAULT ''"),
            ("udhaar_ledger", "transaction_date TEXT DEFAULT ''"),
            ("udhaar_ledger", "recorded_at TEXT DEFAULT ''"),
            ("udhaar_ledger", "backdate_reason TEXT DEFAULT ''"),
            ("returns", "transaction_date TEXT DEFAULT ''"),
            ("returns", "recorded_at TEXT DEFAULT ''"),
            ("returns", "backdate_reason TEXT DEFAULT ''"),
            ("repair_jobs", "transaction_date TEXT DEFAULT ''"),
            ("repair_jobs", "recorded_at TEXT DEFAULT ''"),
            ("repair_jobs", "backdate_reason TEXT DEFAULT ''"),
            ("software_jobs", "transaction_date TEXT DEFAULT ''"),
            ("software_jobs", "recorded_at TEXT DEFAULT ''"),
            ("software_jobs", "backdate_reason TEXT DEFAULT ''"),
            ("users", "can_backdate INTEGER DEFAULT 0"),
            ("products", "alert_model_stock_threshold INTEGER DEFAULT NULL"),
            ("variants", "low_stock_level INTEGER DEFAULT NULL"),
            ("variants", "reorder_qty INTEGER DEFAULT NULL"),
            ("variants", "alert_off INTEGER DEFAULT 0"),
            ("users", "recovery_key_hash TEXT DEFAULT ''"),
            ("users", "admin_pin_hash TEXT DEFAULT ''"),
            ("users", "must_change_password INTEGER DEFAULT 0"),
            ("users", "updated_at TEXT DEFAULT ''"),
            ("customers", "is_archived INTEGER DEFAULT 0"),
            ("expenses", "is_void INTEGER DEFAULT 0"),
            ("quick_services", "is_void INTEGER DEFAULT 0"),
            ("quick_services", "action_type TEXT DEFAULT 'SEND'"),
            ("quick_services", "payment_method TEXT DEFAULT 'CASH'"),
            ("sales", "returned_amount REAL DEFAULT 0"),
        ]:
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_def}")
            except Exception:
                pass

        for idx in INDEX_STATEMENTS:
            try:
                cur.execute(idx)
            except Exception:
                pass

        # Tail columns for units (IMEI tail index for fast O(1) last 4/6 digit search)
        for col in ["imei1_tail", "imei2_tail"]:
            try:
                cur.execute(f"ALTER TABLE units ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass
        
        # SQLite Triggers for auto-populating tail
        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_units_tail_insert AFTER INSERT ON units
        BEGIN
            UPDATE units SET 
                imei1_tail = CASE WHEN NEW.imei1 IS NOT NULL AND length(NEW.imei1) >= 4 THEN substr(NEW.imei1, -6) ELSE NEW.imei1 END,
                imei2_tail = CASE WHEN NEW.imei2 IS NOT NULL AND length(NEW.imei2) >= 4 THEN substr(NEW.imei2, -6) ELSE NEW.imei2 END
            WHERE id = NEW.id;
        END;
        """)

        cur.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_units_tail_update AFTER UPDATE OF imei1, imei2 ON units
        BEGIN
            UPDATE units SET 
                imei1_tail = CASE WHEN NEW.imei1 IS NOT NULL AND length(NEW.imei1) >= 4 THEN substr(NEW.imei1, -6) ELSE NEW.imei1 END,
                imei2_tail = CASE WHEN NEW.imei2 IS NOT NULL AND length(NEW.imei2) >= 4 THEN substr(NEW.imei2, -6) ELSE NEW.imei2 END
            WHERE id = NEW.id;
        END;
        """)

        try:
            cur.execute("UPDATE units SET imei1_tail = substr(imei1, -6) WHERE (imei1_tail IS NULL OR imei1_tail = '') AND imei1 IS NOT NULL AND length(imei1) >= 4")
            cur.execute("UPDATE units SET imei2_tail = substr(imei2, -6) WHERE (imei2_tail IS NULL OR imei2_tail = '') AND imei2 IS NOT NULL AND length(imei2) >= 4")
        except Exception:
            pass
        
        # Seed Settings
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        defaults = [
            ("shop_name", "PAK MOBILE & ACCESSORIES"),
            ("tagline", "Smartphones, Accessories & Professional Repair Center"),
            ("phone", "+92 300 1234567"),
            ("whatsapp", "+92 300 1234567"),
            ("address", "Shop # 15, Ground Floor, Hafeez Center, Main Boulevard, Gulberg III, Lahore"),
            ("warranty_terms", "1 Year Brand Warranty for Official Phones. 7 Days Checking Warranty for Used Phones. No warranty on water damage or LCD break."),
            ("return_window_days", "7"),
            ("footer_note", "Thank you for shopping with us! Developed by Ahmed"),
            ("currency", "Rs."),
            ("receipt_printer_width", "80"), # 80mm or 58mm
            ("receipt_auto_print", "1"),
            ("cash_drawer_pulse", "1"),
            ("scanner_min_length", "8"),
            ("scanner_max_interval_ms", "50"),
            ("scanner_sound_enabled", "1"),
            ("admin_pin_required", "0"),
            ("admin_pin", "9999"),
            ("global_default_phone_low_stock", "2"),
            ("global_default_accessory_low_stock", "5"),
            ("global_default_spare_part_low_stock", "3"),
            ("global_default_phone_reorder_qty", "5"),
            ("global_default_accessory_reorder_qty", "20"),
            ("global_default_spare_part_reorder_qty", "10"),
            ("reorder_sales_window_days", "30"),
            ("reorder_target_cover_days", "14")
        ]
        for k, v in defaults:
            cur.execute("INSERT OR IGNORE INTO settings(key, value, updated_at) VALUES(?, ?, ?)", (k, v, now))
        
        # Seed default low stock and reorder qty for standard categories if not already set
        cur.execute("""
            UPDATE lookup_lists SET default_low_stock_level = 2, default_reorder_qty = 5 
            WHERE list_key = 'category' AND default_low_stock_level IS NULL 
              AND label IN ('Smartphone', 'Feature Phone', 'Tablet')
        """)
        cur.execute("""
            UPDATE lookup_lists SET default_low_stock_level = 5, default_reorder_qty = 20 
            WHERE list_key = 'category' AND default_low_stock_level IS NULL 
              AND label IN ('Charger & Adapter', 'Cable', 'Handsfree & Earbuds', 'Power Bank', 'Mobile Case / Cover', 'Tempered Glass / Protector', 'Memory Card & USB', 'Bluetooth Speaker', 'Smartwatch', 'Other')
        """)
        cur.execute("""
            UPDATE lookup_lists SET default_low_stock_level = 3, default_reorder_qty = 10 
            WHERE list_key = 'category' AND default_low_stock_level IS NULL 
              AND label LIKE 'Spare Part%'
        """)

        # Clean empty strings to NULL in unique columns to prevent collision
        try:
            cur.execute("UPDATE variants SET barcode = NULL WHERE barcode IS NOT NULL AND trim(barcode) = ''")
            cur.execute("UPDATE variants SET sku = NULL WHERE sku IS NOT NULL AND trim(sku) = ''")
            cur.execute("UPDATE units SET serial_no = NULL WHERE serial_no IS NOT NULL AND trim(serial_no) = ''")
            cur.execute("UPDATE units SET imei2 = NULL WHERE imei2 IS NOT NULL AND trim(imei2) = ''")
        except Exception:
            pass

        # Seed Code Counters
        code_seeds = [("ACC", 100), ("PHN", 100), ("PRT", 100), ("VAR", 100), ("BAR", 100000)]
        for prefix, initial in code_seeds:
            cur.execute("INSERT OR IGNORE INTO code_counters (prefix, last_val) VALUES (?, ?)", (prefix, initial))

        # Seed Change Feed Versions
        feed_groups = ["items", "stock", "prices", "customers", "lists", "users", "settings", "profile"]
        for g in feed_groups:
            cur.execute("INSERT OR IGNORE INTO change_feed_versions (group_name, version, updated_at) VALUES (?, 1, ?)", (g, now))

        # Seed Shop Profile singleton
        try:
            cur.execute("SELECT COUNT(*) AS c FROM shop_profile WHERE id = 1")
            if cur.fetchone()["c"] == 0:
                cur.execute("""
                    INSERT INTO shop_profile (id, shop_name, tagline, address, city, phone1, whatsapp, profile_version, updated_at)
                    VALUES (1, 'PAK MOBILE & ACCESSORIES', 'Smartphones, Accessories & Repairs', 'Shop # 15, Ground Floor, Hafeez Center, Main Boulevard, Gulberg III, Lahore', 'Lahore', '+92 300 1234567', '+92 300 1234567', 1, ?)
                """, (now,))
        except Exception:
            pass
        
        # Seed Admin & Staff Users with fail-safe defaults
        cur.execute("SELECT COUNT(*) AS c FROM users")
        if cur.fetchone()["c"] == 0:
            import auth
            pw_admin = auth.hash_password(getattr(config, "DEFAULT_ADMIN_PASSWORD", None) or "admin123")
            cur.execute("""INSERT INTO users (username, password_hash, role, full_name, is_active, permissions, created_at)
                           VALUES (?, ?, 'ADMIN', 'Master Admin', 1, '{\"all\": true}', ?)""",
                        (getattr(config, "DEFAULT_ADMIN_USERNAME", "admin"), pw_admin, now))
            pw_staff = auth.hash_password(getattr(config, "DEFAULT_STAFF_PASSWORD", None) or "staff123")
            cur.execute("""INSERT INTO users (username, password_hash, role, full_name, is_active, permissions, created_at)
                           VALUES (?, ?, 'EMPLOYEE', 'Counter Salesman', 1, '{\"pos\": true, \"inventory_view\": true, \"sales_view\": true}', ?)""",
                        (getattr(config, "DEFAULT_STAFF_USERNAME", "staff"), pw_staff, now))

        # Seed Software Catalog
        cur.execute("SELECT COUNT(*) AS c FROM software_catalog")
        if cur.fetchone()["c"] == 0:
            services = [
                ("Flashing & Official Firmware Update", "Complete OS reinstall & stock rom flash", 1200, 200),
                ("FRP / Google Account Removal", "Google lock removal on official verification", 2000, 500),
                ("Pattern / PIN / Password Unlock", "Screen lock removal with client ownership check", 1500, 300),
                ("Country Unlock / Network JV Unlock", "Carrier and network unlocking service", 3500, 1000),
                ("Data Backup & Phone-to-Phone Transfer", "Complete contacts, photos, WhatsApp migration", 1000, 0),
                ("Apple ID / iCloud Setup & Fix", "Account setup, configuration & cloud sync", 1500, 200),
                ("Virus & Bloatware Clean / Speedup", "Deep optimization and malware cleanup", 800, 0),
                ("Bootloop / Restart Hanging Solution", "Software fix for phones stuck on logo", 1800, 400)
            ]
            for sname, sdesc, sprice, scost in services:
                cur.execute("INSERT INTO software_catalog(name, description, default_price, default_cost, is_active) VALUES(?,?,?,?,1)",
                            (sname, sdesc, sprice, scost))

        # Seed Lookup Lists (Generic Lookup System)
        cur.execute("SELECT COUNT(*) AS c FROM lookup_lists")
        if cur.fetchone()["c"] == 0:
            DEFAULT_LOOKUPS = {
                "brand": ["Apple", "Samsung", "Xiaomi", "Vivo", "Oppo", "Infinix", "Tecno", "Realme", "OnePlus", "Google Pixel", "Huawei", "Motorola", "Nokia", "Honor"],
                "category": ["Smartphone", "Feature Phone", "Tablet", "Smartwatch", "Charger & Adapter", "Cable", "Handsfree & Earbuds", "Power Bank", "Mobile Case / Cover", "Tempered Glass / Protector", "Memory Card & USB", "Bluetooth Speaker", "Spare Part - LCD", "Spare Part - Battery", "Spare Part - Charging Port", "Other"],
                "color": ["Black", "White", "Silver", "Gray", "Blue", "Midnight Blue", "Deep Purple", "Gold", "Rose Gold", "Green", "Red", "Yellow", "Titanium Natural", "Titanium Desert", "Titanium Black"],
                "ram": ["2GB", "3GB", "4GB", "6GB", "8GB", "12GB", "16GB", "24GB"],
                "storage": ["32GB", "64GB", "128GB", "256GB", "512GB", "1TB"],
                "network": ["4G", "5G", "4G / 5G", "Wi-Fi Only"],
                "condition": ["New Box Pack", "Open Box", "Used (Clean 10/10)", "Used (Minor Scratches 9/10)", "Refurbished", "Defective / As-is"],
                "pta_status": ["PTA Approved (Official)", "Non-PTA", "JV (Sim Lock)", "Factory Unlocked", "Dual Physical SIM Approved", "eSIM Approved"],
                "expense_category": ["Shop Rent", "Electricity / Bijli Bill", "Staff Salary / Advance", "Refreshment / Chai & Lunch", "Internet & Telephone", "Generator / Fuel", "Tool & Software License", "Packaging & Bags", "Maintenance & Repair", "Marketing / Flex / Ads", "Miscellaneous / Other"],
                "payment_account": ["Cash Drawer", "EasyPaisa Merchant", "JazzCash Merchant", "Raast / Bank Alfalah", "Meezan Bank", "HBL", "Allied Bank", "MCB"],
                "customer_type": ["Walk-in / Retail", "Regular Customer", "Wholesale / Dealer", "Corporate"],
                "city_area": ["Hafeez Center", "Hall Road", "Gulberg", "Model Town", "Johar Town", "DHA Lahore", "Iqbal Town", "Shadman", "Faisal Town", "Cantt", "Other City"],
                "return_reason": ["Customer Mind Change (Within Policy)", "Defective / Faulty Unit", "PTA Issue / Sim Lock", "Wrong Item Delivered", "Better Price Elsewhere"],
                "trade_in_condition": ["10/10 Like New (Box Available)", "9/10 Normal Wear", "8/10 Scratches / Dents", "Screen Replaced / Serviced", "Camera / FaceID Issue"],
                "repair_complaint": ["LCD Broken / Touch Not Working", "Battery Draining / Swollen", "Not Charging / Loose Port", "Water Damaged", "No Display / Black Screen", "Mic / Speaker Problem", "Network / No SIM", "Camera Fault", "Overheating", "Stuck on Logo / Restarting"],
                "technician": ["Master Ustad (In-house)", "Chip-level Expert (In-house)", "Outsourced Lab (Hall Road)", "Outsourced Screen Specialist"],
                "accessory_type": ["Charger", "Cable", "Earphones", "Case", "Protector", "Powerbank", "Speaker", "Converter"],
                "spare_part_type": ["LCD / Display Screen", "Battery", "Charging Flex Board", "Back Glass", "Camera Glass", "Speaker / Ringer", "Housing / Frame"],
                "warranty_type": ["1 Year Brand Warranty", "7 Days Checking Warranty", "30 Days Shop Warranty", "No Warranty"],
                "quick_service_provider": ["Jazz / Warid", "Zong", "Telenor", "Ufone", "SCOM", "JazzCash", "EasyPaisa", "1Link"],
                "supplier_category": ["Official Brand Distributor", "Hall Road Wholesaler", "Hafeez Center Importer", "Accessories Wholesaler", "Spare Parts Dealer"]
            }
            for list_key, items in DEFAULT_LOOKUPS.items():
                for idx, lbl in enumerate(items):
                    cur.execute("""INSERT INTO lookup_lists (list_key, label, sort_order, is_active, is_system, created_at)
                                   VALUES (?, ?, ?, 1, 0, ?)""", (list_key, lbl, idx * 10, now))

    print("[DB] Initialized Mobile ERP Database with WAL mode & indexes successfully.")

def bump_change_version(group_name="items"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaction() as cx:
        cx.execute("""
            INSERT INTO change_feed_versions (group_name, version, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(group_name) DO UPDATE SET version = version + 1, updated_at = excluded.updated_at
        """, (group_name, now))
        row = cx.execute("SELECT version FROM change_feed_versions WHERE group_name = ?", (group_name,)).fetchone()
        return row[0] if row else 1

def get_change_feed_state():
    try:
        rows = query_all("SELECT group_name, version FROM change_feed_versions")
        groups = {r["group_name"]: r["version"] for r in rows}
        total_ver = sum(groups.values()) if groups else 1
        prof = query_one("SELECT profile_version FROM shop_profile WHERE id = 1")
        prof_ver = prof["profile_version"] if prof else 1
        groups["profile"] = prof_ver
        return {
            "version": total_ver + prof_ver,
            "profile_version": prof_ver,
            "groups": groups
        }
    except Exception:
        return {"version": 1, "profile_version": 1, "groups": {}}

init_db()

if __name__ == "__main__":
    pass
