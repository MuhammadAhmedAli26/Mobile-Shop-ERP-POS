# MOBILE & ACCESSORIES ERP v1.0 — Configuration
import os, sys

HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT", 8085))  # Dedicated port for Mobile Edition

APP_NAME = "MOBILE & ACCESSORIES SHOP ERP + POS"
VERSION = "1.0-PRO"
CURRENCY = "Rs."
TIMEZONE = "Asia/Karachi"

# Security Configuration
SESSION_SECRET = "mobile_erp_vip_pk_secret_2026_x99"
SESSION_TIMEOUT = 28800  # 8 hours
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = None
DEFAULT_STAFF_USERNAME = "staff"
DEFAULT_STAFF_PASSWORD = None
SHUTDOWN_TOKEN = os.environ.get("SHUTDOWN_TOKEN", "mobile_erp_shutdown_token_secure_2026")

# Base and Data Directory Resolution
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(EXE_DIR, "portable.flag")):
        DATA_DIR = os.path.join(EXE_DIR, "data")
    elif os.path.exists(os.path.join(EXE_DIR, "mobile_erp.db")):
        DATA_DIR = EXE_DIR
    else:
        DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "MobileShopERP")
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR = BUNDLE_DIR
    DATA_DIR = BUNDLE_DIR

BASE_DIR = BUNDLE_DIR
DATABASE_NAME = os.environ.get("ERP_DB_PATH", os.path.join(DATA_DIR, "mobile_erp.db"))
SESSION_DATA_DIR = os.path.join(DATA_DIR, "session_data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
LOG_DIR = os.path.join(DATA_DIR, "logs")
STATIC_DIR = os.path.join(BUNDLE_DIR, "static")

# Ensure required runtime data directories exist
for d in [DATA_DIR, SESSION_DATA_DIR, BACKUP_DIR, REPORTS_DIR, LOG_DIR]:
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass

# Copy bundled clean database to DATA_DIR on first launch if not present
if not os.path.exists(DATABASE_NAME):
    bundled_db = os.path.join(BUNDLE_DIR, "mobile_erp.db")
    if os.path.exists(bundled_db):
        try:
            import shutil
            shutil.copy2(bundled_db, DATABASE_NAME)
        except Exception:
            pass
