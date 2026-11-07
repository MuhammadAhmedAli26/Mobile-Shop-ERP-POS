# qa/scripts/server_fixture.py
# Starts the app on port 8099 using a TEMP copy of the project.
# Usage: python qa/scripts/server_fixture.py [fresh|copy] [port]
import os, sys, shutil, subprocess, time, hashlib, sqlite3, tempfile, signal, json, pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REAL_DB = PROJECT_ROOT / "mobile_erp.db"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8099
MODE = sys.argv[1] if len(sys.argv) > 1 else "fresh"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def start_server(mode="fresh", port=8099):
    """Copy project to temp dir, start server, return (proc, temp_dir, url)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="erp_test_"))
    # Copy all source files (exclude large binaries, backups, qa/results)
    for item in PROJECT_ROOT.iterdir():
        name = item.name
        if any(name.startswith(x) for x in ["mobile_edition_BACKUP", "dist", "build", "__pycache__"]):
            continue
        if name.endswith(".exe") or name.endswith(".zip"):
            continue
        if name == "qa":
            continue
        dst = tmp / name
        if item.is_dir():
            shutil.copytree(str(item), str(dst), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        else:
            shutil.copy2(str(item), str(dst))

    if mode == "copy" and REAL_DB.exists():
        # Use a copy of the real DB
        shutil.copy2(str(REAL_DB), str(tmp / "mobile_erp.db"))
    else:
        # Remove any existing DB so the app creates a fresh one
        db_path = tmp / "mobile_erp.db"
        if db_path.exists():
            db_path.unlink()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["ERP_PORT"] = str(port)

    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "main.py"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    url = f"http://127.0.0.1:{port}"
    # Wait for server to be ready
    import urllib.request
    for i in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(f"{url}/health", timeout=2)
            break
        except Exception:
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Server died on startup:\n{out}")
    else:
        proc.kill()
        raise RuntimeError("Server did not start within 30s")

    return proc, tmp, url

def stop_server(proc, tmp):
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/server/shutdown", timeout=2)
    except Exception:
        pass
    time.sleep(1)
    if proc.poll() is None:
        proc.kill()
    # Clean up temp dir
    try:
        shutil.rmtree(str(tmp), ignore_errors=True)
    except Exception:
        pass

if __name__ == "__main__":
    print(f"Starting server mode={MODE} port={PORT}")
    proc, tmp, url = start_server(MODE, PORT)
    print(f"Server running at {url} (tmp={tmp})")
    print(json.dumps({"pid": proc.pid, "tmp": str(tmp), "url": url}))
