# MOBILE & ACCESSORIES ERP v1.0 PRO — Main Application Entry Point
import threading, time, sys, os, webbrowser

if sys.stdout is None:
    try: sys.stdout = open(os.devnull, 'w')
    except Exception: pass
if sys.stderr is None:
    try: sys.stderr = open(os.devnull, 'w')
    except Exception: pass

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import config, db

def start_web():
    try:
        import web_ui
        web_ui.start_server()
    except SystemExit:
        pass
    except Exception as e:
        print(f"[SERVER ERROR] {e}")
        import traceback; traceback.print_exc()

def open_browser():
    time.sleep(1.0)
    try:
        webbrowser.open(f"http://127.0.0.1:{config.PORT}")
    except Exception:
        pass

def main():
    os.makedirs(config.SESSION_DATA_DIR, exist_ok=True)
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    os.makedirs(config.LOG_DIR, exist_ok=True)
    os.makedirs(config.STATIC_DIR, exist_ok=True)

    db.init_db()

    print("=" * 65)
    print(f"  📱 {config.APP_NAME} v{config.VERSION}")
    print(f"  🌐 URL: http://127.0.0.1:{config.PORT}")
    print(f"  👤 Master Admin: {config.DEFAULT_ADMIN_USERNAME} / {config.DEFAULT_ADMIN_PASSWORD}")
    print(f"  👤 Counter Staff: {config.DEFAULT_STAFF_USERNAME} / {config.DEFAULT_STAFF_PASSWORD}")
    print("  💻 Offline Desktop Architecture &bull; Developed by Ahmed")
    print("=" * 65)

    server_thread = threading.Thread(target=start_web, daemon=True)
    server_thread.start()

    # Only launch browser automatically on local desktop, not in cloud environments
    if not os.environ.get("PORT") and not os.environ.get("RENDER"):
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down Mobile ERP Server...")
        sys.exit(0)

if __name__ == "__main__":
    main()
