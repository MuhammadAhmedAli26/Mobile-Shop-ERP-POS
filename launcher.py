# MOBILE & ACCESSORIES ERP — Production Windows Launcher
# Handles Single Instance Mutex, Port Binding, App-Mode Browser, Role Profiles, Logging & Clean Shutdown

import sys, os, time, socket, threading, subprocess, webbrowser

# 1. Logging and Stdout/Stderr Redirect for Windowed Mode
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

import config

log_file_path = os.path.join(config.LOG_DIR, "app.log")
try:
    log_fp = open(log_file_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = log_fp
    sys.stderr = log_fp
except Exception:
    log_fp = None

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        if log_fp:
            log_fp.write(line)
            log_fp.flush()
    except Exception:
        pass

PORT_FILE = os.path.join(config.DATA_DIR, "active_port.txt")

# 2. Role and Target Profile Parsing
def get_role_info(args=None):
    """
    Parses command-line arguments to determine target role, target path,
    and dedicated browser profile directory (preventing session collisions).
    """
    if args is None:
        args = sys.argv[1:]
    
    role = "admin"
    for arg in args:
        arg_lower = arg.lower().strip()
        if arg_lower.startswith("--role="):
            val = arg_lower.split("=", 1)[1].strip()
            if val in ("employee", "counter", "cashier"):
                role = "employee"
            elif val in ("admin", "owner", "manager"):
                role = "admin"
        elif arg_lower in ("--employee", "--counter", "--cashier"):
            role = "employee"
        elif arg_lower in ("--admin", "--manager"):
            role = "admin"

    if role == "employee":
        target_path = "/pos"
        profile_name = "browser_profile_counter"
    else:
        target_path = "/"
        profile_name = "browser_profile_admin"

    profile_dir = os.path.join(config.DATA_DIR, profile_name)
    return role, target_path, profile_dir

def read_active_port():
    """Reads port of currently running instance from active_port.txt."""
    try:
        if os.path.exists(PORT_FILE):
            with open(PORT_FILE, "r", encoding="utf-8") as f:
                p = int(f.read().strip())
                if 1024 <= p <= 65535:
                    return p
    except Exception:
        pass
    return config.PORT

def save_active_port(port):
    """Saves active port to active_port.txt for secondary shortcut launches."""
    try:
        with open(PORT_FILE, "w", encoding="utf-8") as f:
            f.write(str(port))
    except Exception as e:
        log(f"[LAUNCHER WARNING] Could not save active port: {e}")

def remove_active_port():
    """Removes active_port.txt upon clean shutdown."""
    try:
        if os.path.exists(PORT_FILE):
            os.remove(PORT_FILE)
    except Exception:
        pass

# 3. Clean Profile Stale Locks
def clean_profile_locks(profile_dir):
    """Removes stale Chromium locks from prior abrupt terminations."""
    os.makedirs(profile_dir, exist_ok=True)
    for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_file = os.path.join(profile_dir, lock_name)
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception:
                pass

# 4. Locate App-Mode Browser Executable and Flags
def get_browser_command(url, profile_dir, argv=None):
    if argv is None:
        argv = sys.argv
    clean_profile_locks(profile_dir)

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")

    candidates = [
        # Microsoft Edge (Standard Windows 10/11)
        os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"),
        # Google Chrome
        os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
    ]

    flags = [
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-features=TranslateUI",
        "--autoplay-policy=no-user-gesture-required",
    ]
    if "--safe-mode" in argv:
        flags.append("--disable-gpu")

    for exe in candidates:
        if os.path.exists(exe):
            return [exe] + flags, True

    return None, False

def open_app_window(url, profile_dir, argv=None):
    try:
        cmd, is_app_mode = get_browser_command(url, profile_dir, argv=argv)
        if is_app_mode and cmd:
            log(f"Launching desktop app window ({cmd[0]}): {url}")
            subprocess.Popen(cmd)
            return True
        else:
            log(f"Launching system default browser: {url}")
            webbrowser.open(url)
            return False
    except Exception as e:
        log(f"Browser launch exception: {e}")
        webbrowser.open(url)
        return False

# 5. Windows Mutex for Single Instance Lock
def acquire_single_instance_mutex():
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Local\\MobileShopERP_SingleInstance_Mutex"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            log("[LAUNCHER] Another backend instance is running. Launching window for requested shortcut.")
            active_p = read_active_port()
            role, path, pdir = get_role_info()
            target_url = f"http://127.0.0.1:{active_p}{path}"
            try:
                open_app_window(target_url, pdir)
            except Exception as e:
                log(f"[LAUNCHER ERROR] Secondary launch error: {e}")
                webbrowser.open(target_url)
            sys.exit(0)
        return handle
    except Exception as e:
        log(f"[LAUNCHER WARNING] Mutex error: {e}")
        return None

# 6. Port Availability Check & Fallback
def find_available_port(start_port=8085, max_tries=20):
    for p in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start_port

# 7. Wait for Server Readiness
def wait_for_server(port, timeout=15.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    time.sleep(0.3)
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False

# 8. Main Launcher Entry Point
def launch():
    role, path, pdir = get_role_info()
    log("=" * 60)
    log(f"Starting {config.APP_NAME} v{config.VERSION} (Role: {role})")
    log(f"Data directory: {config.DATA_DIR}")

    mutex_handle = acquire_single_instance_mutex()

    chosen_port = find_available_port(config.PORT)
    config.PORT = chosen_port
    os.environ["PORT"] = str(chosen_port)
    save_active_port(chosen_port)
    log(f"Server binding to 127.0.0.1:{chosen_port}")

    # Initialize Database
    try:
        import db
        db.init_db()
    except Exception as e:
        log(f"[DB ERROR] {e}")
        import traceback
        log(traceback.format_exc())

    # Start multi-threaded WSGI server in background daemon
    import web_ui
    server_errors = []
    def run_server_safely():
        try:
            web_ui.start_server()
        except Exception as ex:
            import traceback
            tb = traceback.format_exc()
            log(f"[SERVER CRITICAL EXCEPTION] {tb}")
            server_errors.append(tb)

    server_thread = threading.Thread(target=run_server_safely, daemon=True)
    server_thread.start()

    # Wait for server ready
    ready = wait_for_server(chosen_port, timeout=15.0)
    if not ready:
        err_detail = "\n".join(server_errors) if server_errors else f"Port {chosen_port} did not accept connections within 15s."
        log(f"[FATAL SERVER STARTUP] {err_detail}")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Server failed to start:\n\n{err_detail}\n\nSee log file: {log_file_path}", "Mobile Shop ERP Startup Error", 0x10)
        except Exception:
            pass
        sys.exit(1)

    target_url = f"http://127.0.0.1:{chosen_port}{path}"
    log(f"Opening desktop app window at: {target_url} with profile {pdir}")
    open_app_window(target_url, pdir)

    # Keep server running permanently
    log(f"Mobile ERP server running actively on http://127.0.0.1:{chosen_port}.")
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        log("Received exit signal. Shutting down...")
    except Exception as e:
        log(f"[LIFECYCLE EXCEPTION] {e}")
    finally:
        remove_active_port()
        try:
            import db
            with db.get_connection() as cx:
                cx.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            log("Database WAL checkpointed cleanly.")
        except Exception:
            pass
        log("Application exited cleanly.")
        os._exit(0)

if __name__ == "__main__":
    try:
        launch()
    except Exception as fatal:
        log(f"[FATAL CRASH] {fatal}")
        import traceback
        tb = traceback.format_exc()
        log(tb)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"An unexpected error occurred:\n\n{fatal}\n\nSee logs at: {log_file_path}", "Mobile Shop ERP Error", 0x10)
        except Exception:
            pass
        sys.exit(1)
