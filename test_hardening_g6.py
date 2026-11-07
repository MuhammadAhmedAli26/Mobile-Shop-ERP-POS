import os
import sys
import tempfile
import pytest

# Ensure mobile_edition is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import launcher
import config

def test_launcher_role_parsing():
    """Verify command-line arguments route cleanly to admin vs employee profiles and URLs."""
    # Test Admin default
    role, path, pdir = launcher.get_role_info([])
    assert role == "admin"
    assert path == "/"
    assert "browser_profile_admin" in pdir

    # Test explicit Admin
    role, path, pdir = launcher.get_role_info(["--role=admin"])
    assert role == "admin"
    assert path == "/"
    assert "browser_profile_admin" in pdir

    role, path, pdir = launcher.get_role_info(["--admin"])
    assert role == "admin"
    assert path == "/"
    assert "browser_profile_admin" in pdir

    # Test Employee / Counter / Cashier
    role, path, pdir = launcher.get_role_info(["--role=employee"])
    assert role == "employee"
    assert path == "/pos"
    assert "browser_profile_counter" in pdir

    role, path, pdir = launcher.get_role_info(["--role=counter"])
    assert role == "employee"
    assert path == "/pos"
    assert "browser_profile_counter" in pdir

    role, path, pdir = launcher.get_role_info(["--employee"])
    assert role == "employee"
    assert path == "/pos"
    assert "browser_profile_counter" in pdir

    role, path, pdir = launcher.get_role_info(["--counter"])
    assert role == "employee"
    assert path == "/pos"
    assert "browser_profile_counter" in pdir


def test_active_port_file_lifecycle():
    """Verify saving, reading, and removing active port."""
    test_port = 8099
    launcher.save_active_port(test_port)
    assert os.path.exists(launcher.PORT_FILE)
    
    read_p = launcher.read_active_port()
    assert read_p == test_port

    launcher.remove_active_port()
    assert not os.path.exists(launcher.PORT_FILE)


def test_profile_lock_cleanup():
    """Verify stale chromium singleton locks are purged prior to launch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_p = os.path.join(tmpdir, lock_name)
            with open(lock_p, "w") as f:
                f.write("lock")
            assert os.path.exists(lock_p)

        launcher.clean_profile_locks(tmpdir)

        for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            lock_p = os.path.join(tmpdir, lock_name)
            assert not os.path.exists(lock_p)


def test_browser_command_flags():
    """Verify mandatory zero-popup flags and safe-mode GPU suppression."""
    dummy_profile = os.path.join(config.DATA_DIR, "test_prof")
    dummy_url = "http://127.0.0.1:8085/pos"

    # Standard launch
    cmd, is_app = launcher.get_browser_command(dummy_url, dummy_profile, argv=[])
    if cmd:
        assert f"--app={dummy_url}" in cmd
        assert f"--user-data-dir={dummy_profile}" in cmd
        assert "--no-first-run" in cmd
        assert "--no-default-browser-check" in cmd
        assert "--disable-sync" in cmd
        assert "--disable-features=TranslateUI" in cmd
        assert "--autoplay-policy=no-user-gesture-required" in cmd
        assert "--disable-gpu" not in cmd

    # Safe mode launch
    cmd_safe, _ = launcher.get_browser_command(dummy_url, dummy_profile, argv=["--safe-mode"])
    if cmd_safe:
        assert "--disable-gpu" in cmd_safe


def test_setup_iss_specifications():
    """Verify setup.iss has lowest privileges, distinct shortcuts, and no DB deletion."""
    iss_path = os.path.join(os.path.dirname(__file__), "setup.iss")
    assert os.path.exists(iss_path)
    with open(iss_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "PrivilegesRequired=lowest" in content
    assert "Mobile Shop ERP (Admin)" in content
    assert "Mobile Shop POS (Counter)" in content
    assert "--role=admin" in content
    assert "--role=employee" in content
    assert "mobile_erp.db" not in content  # Must NOT delete mobile_erp.db on uninstall


def test_pyinstaller_spec_specifications():
    """Verify MobileShopERP.spec has console=False, upx=False, and required imports."""
    spec_path = os.path.join(os.path.dirname(__file__), "MobileShopERP.spec")
    assert os.path.exists(spec_path)
    with open(spec_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "console=False" in content
    assert "upx=False" in content
    for imp in ["bcrypt", "logo_engine", "PIL", "auth", "inventory", "printing", "waitress"]:
        assert f"'{imp}'" in content or f'"{imp}"' in content
