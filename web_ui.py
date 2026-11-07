# MOBILE & ACCESSORIES ERP — Master Web UI & Application Server
import os, sys, json, time, io, csv, urllib.parse, html
from datetime import datetime, timedelta
from bottle import Bottle, request, response, redirect, static_file, abort, HTTPResponse
from beaker.middleware import SessionMiddleware

import config, db, auth, scanner, printing, inventory, pos, purchasing, credit, services, accounting, lookups, search, alert_engine, top_sellers, logo_engine

app = Bottle()

# Session Configuration
SESSION_OPTIONS = {
    "session.type": "file",
    "session.cookie_expires": config.SESSION_TIMEOUT,
    "session.data_dir": config.SESSION_DATA_DIR,
    "session.auto": True,
    "session.key": "mobile_erp_session",
    "session.secret": config.SESSION_SECRET,
    "session.httponly": True,
    "session.samesite": "Strict"
}

def get_session():
    return request.environ.get("beaker.session")

def get_current_user():
    s = get_session()
    if s and s.get("uid"):
        return db.query_one("SELECT * FROM users WHERE id = ? AND is_active = 1", (s["uid"],))
    return None

def require_login():
    u = get_current_user()
    if not u:
        redirect("/login")
    return u

def require_admin():
    u = require_login()
    if u["role"] != "ADMIN":
        abort(403, "Access Denied: Admin authorization required.")
    return u

def require_perm(perm_name):
    u = require_login()
    if u["role"] == "ADMIN":
        return u
    perms = {}
    try:
        perms = json.loads(u.get("permissions") or "{}")
    except Exception:
        pass
    if isinstance(perms, dict) and perms.get(perm_name):
        return u
    if isinstance(perms, list) and perm_name in perms:
        return u
    abort(403, f"Access Denied: Permission '{perm_name}' required.")

def safe_int(val, default=0):
    """Safely converts any input into integer without throwing ValueError on empty strings."""
    try:
        if val is None:
            return default
        s = str(val).strip()
        return int(s) if s else default
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    """Safely converts any input into float without throwing ValueError on empty strings."""
    try:
        if val is None:
            return default
        s = str(val).strip()
        return float(s) if s else default
    except (ValueError, TypeError):
        return default

import calendar
def get_month_date_range(ym_str):
    """Returns (start_date, end_date) for a 'YYYY-MM' string with exact month calendar days."""
    try:
        parts = str(ym_str).strip()[:7].split("-")
        y, m = int(parts[0]), int(parts[1])
        last_day = calendar.monthrange(y, m)[1]
        return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"
    except Exception:
        s = str(ym_str).strip()[:7]
        return f"{s}-01", f"{s}-28"

@app.error(403)
def error_403_handler(error):
    u = get_current_user()
    content = f"""
    <div style="max-width: 620px; margin: 60px auto; text-align: center; background: var(--card, #1e293b); padding: 40px; border-radius: 12px; border: 1px solid var(--card-border, #334155); box-shadow: 0 10px 25px rgba(0,0,0,0.3); border-top: 4px solid #ef4444;">
        <div style="font-size: 54px; margin-bottom: 12px;">🔒</div>
        <h2 style="font-size: 22px; color: var(--text, #fff); margin-bottom: 8px;">Access Restricted (403)</h2>
        <p style="color: var(--text-muted, #94a3b8); font-size: 14px; margin-bottom: 24px; line-height: 1.5;">
            {error.body or 'You do not have permission to access this administrative module. Please use your authorized Counter POS functions or contact the shop administrator.'}
        </p>
        <div style="display: flex; gap: 12px; justify-content: center;">
            <a href="/pos" class="btn btn-primary" style="padding: 10px 20px; border-radius: 8px; font-weight: 600; text-decoration: none;">Go to POS Counter</a>
            <a href="javascript:history.back()" class="btn btn-secondary" style="padding: 10px 20px; border-radius: 8px; font-weight: 600; text-decoration: none;">Go Back</a>
        </div>
    </div>
    """
    if u:
        return layout("Access Restricted", content, active_nav="pos", user=u)
    return f"<!DOCTYPE html><html><head><title>Access Restricted</title><link rel='stylesheet' href='/static/smart_select.css'></head><body style='background:#0f172a; color:#fff; font-family:sans-serif;'>{content}</body></html>"

# ═══════════════════════════════════════════════════════════
# COMMON HTML LAYOUT & COMPONENTS
# ═══════════════════════════════════════════════════════════

def layout(title, content, active_nav="pos", user=None):
    user = user or get_current_user()
    shop = printing.get_shop_info()
    username = user["username"] if user else "Guest"
    role = user["role"] if user else ""
    is_admin = (role == "ADMIN")

    # Quick drawer cash indicator
    today = datetime.now().strftime("%Y-%m-%d")
    close_info = accounting.get_day_closing_data(today)
    drawer_cash = close_info["expected_cash"]

    # Stock alert counts for top-bar bell & low stock nav
    alert_summary = alert_engine.get_alert_summary()
    tot_urgent = alert_summary["total_urgent"]
    out_c = alert_summary["out_count"]
    low_c = alert_summary["low_count"]
    urgent_items = alert_engine.get_urgent_alert_items(10)

    feed_state = db.get_change_feed_state()
    feed_ver = feed_state.get("version", 1)
    prof_ver = feed_state.get("profile_version", 1)

    drawer_items_html = ""
    for ui in urgent_items:
        st_color = "#ef4444" if ui["state"] == "OUT" else "#f59e0b"
        st_text = "OUT OF STOCK" if ui["state"] == "OUT" else f"LOW: {ui['current_stock']} left"
        specs = f"{ui['ram']} {ui['storage']} {ui['color']}".strip()
        drawer_items_html += f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid rgba(255,255,255,0.06);">
          <div>
            <div style="font-size:12px; font-weight:bold; color:var(--text);">{ui['brand']} {ui['model_name']}</div>
            <div style="font-size:11px; color:var(--text-muted);">{specs} &bull; Alert at {ui['effective_level']}</div>
          </div>
          <div style="text-align:right;">
            <span style="font-size:10px; font-weight:800; color:{st_color}; background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:4px; border:1px solid {st_color}40;">{st_text}</span>
          </div>
        </div>
        """
    if not drawer_items_html:
        drawer_items_html = '<div style="padding:16px; text-align:center; color:var(--text-muted); font-size:12px;">✅ All inventory items are well-stocked!</div>'

    nav_items = [
        ("pos", "⚡ POS (F1)", "/pos", True),
        ("sales", "🧾 Daily Sales", "/sales", True),
        ("inventory", "📦 Inventory (F2)", "/inventory", True),
        ("low_stock", f"⚠️ Low Stock ({tot_urgent})", "/inventory/low-stock", True),
        ("purchasing", "📥 Purchases (F3)", "/purchasing", is_admin),
        ("returns", "🔄 Returns & Trade-In", "/returns", True),
        ("repairs", "🔧 Repairs (F4)", "/repairs", True),
        ("software", "💻 Software (F5)", "/software", True),
        ("quick_services", "⚡ Quick Services", "/quick-services", True),
        ("credit", "👥 Udhaar & Plans (F6)", "/credit", True),
        ("expenses", "💸 Expenses (F7)", "/expenses", is_admin),
        ("reports", "📊 Reports (F8)", "/reports", is_admin),
        ("top_sellers", "🔥 Top Sellers", "/reports/top-sellers", is_admin),
        ("closing", "🔒 Day Closing (F9)", "/day-closing", is_admin),
        ("settings", "⚙️ Settings (F10)", "/settings", is_admin),
    ]

    nav_html = ""
    for nid, label, url, visible in nav_items:
        if not visible:
            continue
        active_cls = "active" if active_nav == nid else ""
        nav_html += f'<a href="{url}" class="nav-btn {active_cls}">{label}</a>\n'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {shop['name']}</title>
<link rel="stylesheet" href="/static/smart_select.css">
<style>
  :root {{
    --bg: #0f172a;
    --card: #1e293b;
    --card-bg: #1e293b;
    --card-border: #334155;
    --border: #334155;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --success: #10b981;
    --success-hover: #059669;
    --warning: #f59e0b;
    --danger: #ef4444;
    --purple: #8b5cf6;
  }}
  :root[data-theme="light"] {{
    --bg: #f8fafc;
    --card: #ffffff;
    --card-bg: #ffffff;
    --card-border: #e2e8f0;
    --border: #cbd5e1;
    --text: #0f172a;
    --text-muted: #64748b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  body {{ background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column; transition: background 0.15s, color 0.15s; }}
  
  /* Top Bar */
  .top-bar {{ background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(8px); border-bottom: 1px solid var(--card-border); padding: 8px 16px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 1000; }}
  :root[data-theme="light"] .top-bar {{ background: rgba(255, 255, 255, 0.95); }}
  .brand-area {{ display: flex; align-items: center; gap: 12px; }}
  .shop-title {{ font-size: 16px; font-weight: 800; color: var(--text); letter-spacing: 0.5px; }}
  .shop-sub {{ font-size: 11px; color: var(--text-muted); }}
  
  .search-trigger {{ display: flex; align-items: center; gap: 8px; background: rgba(0,0,0,0.15); border: 1px solid var(--card-border); padding: 6px 14px; border-radius: 20px; cursor: pointer; color: var(--text-muted); font-size: 12.5px; min-width: 260px; user-select: none; transition: 0.15s; }}
  .search-trigger:hover {{ border-color: var(--primary); color: var(--text); background: rgba(59,130,246,0.06); }}
  .search-trigger kbd {{ background: rgba(148,163,184,0.2); padding: 2px 6px; border-radius: 4px; font-size: 10.5px; margin-left: auto; font-weight: 700; }}

  .top-right {{ display: flex; align-items: center; gap: 10px; font-size: 12.5px; }}
  .badge-cash {{ background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success); color: #34d399; padding: 4px 10px; border-radius: 20px; font-weight: bold; }}
  .user-badge {{ background: rgba(59, 130, 246, 0.2); border: 1px solid var(--primary); color: #93c5fd; padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: bold; }}
  .theme-toggle-btn, .shortcuts-btn {{ background: transparent; border: 1px solid var(--card-border); color: var(--text); padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 12px; }}
  .theme-toggle-btn:hover, .shortcuts-btn:hover {{ background: rgba(255,255,255,0.06); }}
  .logout-btn {{ color: var(--danger); text-decoration: none; font-weight: bold; padding: 4px 8px; border-radius: 4px; border: 1px solid rgba(239,68,68,0.3); }}
  .logout-btn:hover {{ background: rgba(239,68,68,0.2); }}

  /* Sub Navigation */
  .sub-nav {{ background: var(--card); border-bottom: 1px solid var(--card-border); padding: 6px 16px; display: flex; gap: 6px; overflow-x: auto; }}
  .nav-btn {{ color: var(--text-muted); text-decoration: none; font-size: 12.5px; font-weight: 600; padding: 7px 12px; border-radius: 6px; white-space: nowrap; transition: 0.15s; }}
  .nav-btn:hover {{ background: rgba(255,255,255,0.06); color: var(--text); }}
  .nav-btn.active {{ background: var(--primary); color: #fff; }}

  /* Main Container */
  .main-content {{ flex: 1; padding: 16px; max-width: 1550px; margin: 0 auto; width: 100%; }}

  /* Grid & Cards */
  .grid-2 {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }}
  .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  .grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
  .grid-5 {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }}

  .card {{ background: var(--card); border: 1px solid var(--card-border); border-radius: 8px; padding: 16px; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.06); }}
  .card-title {{ font-size: 14.5px; font-weight: 700; color: var(--text); }}

  /* Buttons */
  .btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 8px 14px; font-size: 13px; font-weight: 600; border-radius: 6px; border: none; cursor: pointer; text-decoration: none; transition: 0.15s; min-height: 38px; }}
  .btn-primary {{ background: var(--primary); color: #fff; }}
  .btn-primary:hover {{ background: var(--primary-hover); }}
  .btn-success {{ background: var(--success); color: #fff; }}
  .btn-success:hover {{ background: var(--success-hover); }}
  .btn-warning {{ background: var(--warning); color: #000; }}
  .btn-danger {{ background: var(--danger); color: #fff; }}
  .btn-secondary {{ background: #475569; color: #fff; }}
  .btn-secondary:hover {{ background: #334155; }}
  .btn-sm {{ padding: 4px 8px; font-size: 11.5px; border-radius: 4px; min-height: 28px; }}

  /* Forms & Inputs */
  .form-group {{ margin-bottom: 12px; }}
  .form-label {{ display: block; font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 4px; }}
  .form-control {{ width: 100%; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 8px 10px; font-size: 13px; outline: none; transition: 0.15s; }}
  .form-control:focus {{ border-color: var(--primary); box-shadow: 0 0 0 2px rgba(59,130,246,0.25); }}

  /* Tables */
  .table-responsive {{ overflow-x: auto; }}
  table.data-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; text-align: left; }}
  table.data-table th {{ background: rgba(0,0,0,0.15); color: var(--text-muted); padding: 8px 10px; font-weight: 600; border-bottom: 1px solid var(--card-border); }}
  table.data-table td {{ padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.05); color: var(--text); vertical-align: middle; }}
  table.data-table tr:hover td {{ background: rgba(255,255,255,0.03); }}

  /* Badges & Tags */
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
  .badge-success {{ background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }}
  .badge-danger {{ background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3); }}
  .badge-warning {{ background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3); }}
  .badge-info {{ background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); }}
  .badge-purple {{ background: rgba(139,92,246,0.15); color: #c084fc; border: 1px solid rgba(139,92,246,0.3); }}

  /* Global Search Modal */
  .search-modal-backdrop {{ position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(15,23,42,0.7); backdrop-filter: blur(4px); z-index: 10000; display: flex; align-items: flex-start; justify-content: center; padding-top: 80px; }}
  .search-modal-box {{ background: var(--card); border: 1px solid var(--card-border); border-radius: 12px; width: 100%; max-width: 680px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5); overflow: hidden; }}
  .search-modal-input-area {{ display: flex; align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--card-border); gap: 10px; }}
  .search-modal-input {{ width: 100%; background: transparent; border: none; outline: none; font-size: 16px; color: var(--text); font-weight: 600; }}
  .search-modal-results {{ max-height: 420px; overflow-y: auto; padding: 12px; }}
  .search-res-group-title {{ font-size: 11px; font-weight: 800; color: var(--text-muted); text-transform: uppercase; padding: 6px 10px; margin-top: 6px; letter-spacing: 0.5px; }}
  .search-res-item {{ display: flex; justify-content: space-between; align-items: center; padding: 9px 12px; border-radius: 8px; cursor: pointer; text-decoration: none; color: inherit; transition: background 0.1s; }}
  .search-res-item:hover, .search-res-item.highlighted {{ background: rgba(59,130,246,0.12); color: #38bdf8; }}
  .search-res-title {{ font-size: 13.5px; font-weight: 700; }}
  .search-res-sub {{ font-size: 11.5px; color: var(--text-muted); }}

  /* Footer Watermark */
  .footer {{ text-align: center; padding: 12px; font-size: 11.5px; color: var(--text-muted); border-top: 1px solid var(--card-border); margin-top: auto; }}
  .footer strong {{ color: var(--text); }}
</style>
<script src="/static/scanner_engine.js"></script>
<script src="/static/smart_select.js"></script>
<script>
  // Theme Management
  (function() {{
    const saved = localStorage.getItem('mobile_erp_theme') || 'dark';
    if (saved === 'light') document.documentElement.setAttribute('data-theme', 'light');
  }})();

  function toggleTheme() {{
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'light' ? 'dark' : 'light';
    if (next === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('mobile_erp_theme', next);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.innerText = next === 'light' ? '☀️' : '🌙';
  }}

  function toggleAlertsDrawer() {{
    const d = document.getElementById('stock-alerts-drawer');
    if (d) d.style.display = (d.style.display === 'block') ? 'none' : 'block';
  }}
  document.addEventListener('click', function(e) {{
    const d = document.getElementById('stock-alerts-drawer');
    if (d && d.style.display === 'block' && !e.target.closest('#stock-alerts-drawer') && !e.target.closest('button[onclick*="toggleAlertsDrawer"]')) {{
      d.style.display = 'none';
    }}
  }});

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', function(e) {{
    // Ctrl + K = Global Search
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {{
      e.preventDefault();
      openGlobalSearchModal();
      return;
    }}
    // F1 = Shortcuts Help
    if (e.key === 'F1' && !e.ctrlKey && !e.altKey) {{
      e.preventDefault();
      openShortcutsModal();
      return;
    }}

    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {{
      if (e.key === 'F12' || (e.key === 'Enter' && e.ctrlKey)) {{
        var payBtn = document.getElementById('btn-pay-print');
        if (payBtn) {{ e.preventDefault(); payBtn.click(); }}
      }}
      return;
    }}

    switch(e.key) {{
      case 'F2': e.preventDefault(); window.location.href = '/inventory'; break;
      case 'F3': e.preventDefault(); window.location.href = '/purchasing'; break;
      case 'F4': e.preventDefault(); window.location.href = '/repairs'; break;
      case 'F5': e.preventDefault(); window.location.href = '/software'; break;
      case 'F6': e.preventDefault(); window.location.href = '/credit'; break;
      case 'F7': e.preventDefault(); window.location.href = '/expenses'; break;
      case 'F8': e.preventDefault(); window.location.href = '/reports'; break;
      case 'F9': e.preventDefault(); window.location.href = '/day-closing'; break;
      case 'F10': e.preventDefault(); window.location.href = '/settings'; break;
    }}
  }});

  // Universal text and Urdu normalizer for client-side instant filters
  window.normText = function(t) {{
    if (!t) return '';
    return t.toString().toLowerCase().trim()
      .replace(/[۰-۹]/g, d => '0123456789'['۰۱۲۳۴۵۶۷۸۹'.indexOf(d)])
      .replace(/[٠-٩]/g, d => '0123456789'['٠١٢٣٤٥٦٧٨٩'.indexOf(d)])
      .replace(/[ي]/g, 'ی').replace(/[ك]/g, 'ک').replace(/[ةھ]/g, 'ہ').replace(/[ؤ]/g, 'و').replace(/[إأآ]/g, 'ا');
  }};

  // Global Universal Search (Ctrl+K)
  let searchDebounce = null;
  function openGlobalSearchModal() {{
    let m = document.getElementById('global-search-modal');
    if (!m) {{
      m = document.createElement('div');
      m.id = 'global-search-modal';
      m.className = 'search-modal-backdrop';
      m.innerHTML = `
        <div class="search-modal-box">
          <div class="search-modal-input-area">
            <span style="font-size:18px;">🔍</span>
            <input type="text" id="global-search-input" class="search-modal-input" placeholder="Search phone models, IMEIs, customers, invoices, repairs..." autofocus autocomplete="off" />
            <kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-size:11px;color:#94a3b8;">Esc</kbd>
          </div>
          <div id="global-search-results" class="search-modal-results">
            <div style="padding:24px;text-align:center;color:#64748b;font-size:13px;">Type model name, 15-digit IMEI, customer phone, or invoice number...</div>
          </div>
        </div>
      `;
      document.body.appendChild(m);
      m.onclick = (e) => {{ if (e.target === m) closeGlobalSearchModal(); }};

      const inp = m.querySelector('#global-search-input');
      let gHighlightIdx = -1;
      inp.oninput = () => {{
        clearTimeout(searchDebounce);
        const q = inp.value.trim();
        if (!q) {{
          m.querySelector('#global-search-results').innerHTML = '<div style="padding:24px;text-align:center;color:#64748b;font-size:13px;">Type model name, 15-digit IMEI, customer phone, or invoice number...</div>';
          gHighlightIdx = -1;
          return;
        }}
        searchDebounce = setTimeout(() => executeGlobalSearch(q), 30);
      }};
      inp.onkeydown = (e) => {{
        if (e.key === 'Escape') {{ closeGlobalSearchModal(); return; }}
        const items = m.querySelectorAll('.search-res-item');
        if (!items.length) return;
        if (e.key === 'ArrowDown') {{
          e.preventDefault();
          gHighlightIdx = (gHighlightIdx + 1) % items.length;
          items.forEach((it, idx) => it.style.background = (idx === gHighlightIdx ? 'rgba(59, 130, 246, 0.25)' : ''));
          items[gHighlightIdx].scrollIntoView({{ block: 'nearest' }});
        }} else if (e.key === 'ArrowUp') {{
          e.preventDefault();
          gHighlightIdx = (gHighlightIdx - 1 + items.length) % items.length;
          items.forEach((it, idx) => it.style.background = (idx === gHighlightIdx ? 'rgba(59, 130, 246, 0.25)' : ''));
          items[gHighlightIdx].scrollIntoView({{ block: 'nearest' }});
        }} else if (e.key === 'Enter') {{
          if (gHighlightIdx >= 0 && gHighlightIdx < items.length) {{
            e.preventDefault();
            items[gHighlightIdx].click();
          }}
        }}
      }};
    }}
    m.style.display = 'flex';
    setTimeout(() => {{
      const inp = m.querySelector('#global-search-input');
      inp.value = '';
      inp.focus();
    }}, 40);
  }}

  function closeGlobalSearchModal() {{
    const m = document.getElementById('global-search-modal');
    if (m) m.style.display = 'none';
  }}

  async function executeGlobalSearch(query) {{
    const resBox = document.getElementById('global-search-results');
    try {{
      const resp = await fetch('/api/search?q=' + encodeURIComponent(query));
      const data = await resp.json();
      if (!data.results || data.total_count === 0) {{
        resBox.innerHTML = '<div style="padding:24px;text-align:center;color:#64748b;font-size:13px;">No results found for "' + query + '"</div>';
        return;
      }}

      let html = '';
      const r = data.results;

      if (r.products && r.products.length) {{
        html += '<div class="search-res-group-title">📱 Phones & Inventory Stock</div>';
        r.products.forEach(p => {{
          html += `<a href="${{p.url}}" class="search-res-item" onclick="closeGlobalSearchModal()">
            <div><div class="search-res-title">${{p.title}}</div><div class="search-res-sub">${{p.subtitle}}</div></div>
            <div style="font-weight:bold;color:#38bdf8;">Rs. ${{Number(p.price).toLocaleString()}}</div>
          </a>`;
        }});
      }}

      if (r.customers && r.customers.length) {{
        html += '<div class="search-res-group-title">👥 Customers & Khata</div>';
        r.customers.forEach(c => {{
          html += `<a href="${{c.url}}" class="search-res-item" onclick="closeGlobalSearchModal()">
            <div><div class="search-res-title">${{c.title}}</div><div class="search-res-sub">${{c.subtitle}}</div></div>
            <div style="font-size:11px;color:#94a3b8;">Khata Ledger &rarr;</div>
          </a>`;
        }});
      }}

      if (r.sales && r.sales.length) {{
        html += '<div class="search-res-group-title">🧾 Sales Invoices</div>';
        r.sales.forEach(s => {{
          html += `<a href="${{s.url}}" class="search-res-item" onclick="closeGlobalSearchModal()">
            <div><div class="search-res-title">${{s.title}}</div><div class="search-res-sub">${{s.subtitle}}</div></div>
            <div style="font-weight:bold;color:#34d399;">Rs. ${{Number(s.grand_total).toLocaleString()}}</div>
          </a>`;
        }});
      }}

      if (r.repairs && r.repairs.length) {{
        html += '<div class="search-res-group-title">🔧 Repair Job Tickets</div>';
        r.repairs.forEach(rp => {{
          html += `<a href="${{rp.url}}" class="search-res-item" onclick="closeGlobalSearchModal()">
            <div><div class="search-res-title">${{rp.title}}</div><div class="search-res-sub">${{rp.subtitle}}</div></div>
            <div style="font-size:11px;color:#fbbf24;">Repair &rarr;</div>
          </a>`;
        }});
      }}

      if (r.software && r.software.length) {{
        html += '<div class="search-res-group-title">💻 Software Services</div>';
        r.software.forEach(sw => {{
          html += `<a href="${{sw.url}}" class="search-res-item" onclick="closeGlobalSearchModal()">
            <div><div class="search-res-title">${{sw.title}}</div><div class="search-res-sub">${{sw.subtitle}}</div></div>
            <div style="font-size:11px;color:#c084fc;">Software &rarr;</div>
          </a>`;
        }});
      }}

      resBox.innerHTML = html;
    }} catch (e) {{
      resBox.innerHTML = '<div style="padding:16px;text-align:center;color:#ef4444;">Search request error: ' + e.message + '</div>';
    }}
  }}

  // Shortcuts Cheat Sheet Modal
  function openShortcutsModal() {{
    let m = document.getElementById('shortcuts-help-modal');
    if (!m) {{
      m = document.createElement('div');
      m.id = 'shortcuts-help-modal';
      m.className = 'search-modal-backdrop';
      m.innerHTML = `
        <div class="search-modal-box" style="max-width:520px;padding:24px;">
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--card-border);padding-bottom:12px;">
            <h3 style="font-size:17px;font-weight:800;color:var(--text);">⌨️ Keyboard Shortcuts Cheat Sheet</h3>
            <button onclick="document.getElementById('shortcuts-help-modal').style.display='none'" style="background:none;border:none;font-size:18px;cursor:pointer;color:var(--text-muted);">✕</button>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;font-size:13px;">
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">Ctrl + K</kbd> Universal Search</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F1</kbd> POS Terminal</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F2</kbd> Inventory Stock</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F3</kbd> Purchases / Inward</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F4</kbd> Repairs Workshop</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F5</kbd> Software Services</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F6</kbd> Udhaar & Plans</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F7</kbd> Shop Expenses</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F8</kbd> P&L Reports</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F9</kbd> Day Closing</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F10</kbd> System Settings</div>
            <div><kbd style="background:rgba(255,255,255,0.1);padding:2px 8px;border-radius:4px;font-weight:bold;">F12 / Enter</kbd> Pay & Print</div>
          </div>
          <div style="text-align:right;margin-top:20px;">
            <button onclick="document.getElementById('shortcuts-help-modal').style.display='none'" class="btn btn-primary btn-sm">Close</button>
          </div>
        </div>
      `;
      document.body.appendChild(m);
      m.onclick = (e) => {{ if (e.target === m) m.style.display = 'none'; }};
    }}
    m.style.display = 'flex';
  }}

  // Live Change-Feed Polling (< 0.2% CPU, 2000ms active, slows when hidden)
  (function() {{
    let currentFeedVersion = {feed_ver};
    let currentProfileVersion = {prof_ver};
    let pollTimer = null;

    async function pollChangeFeed() {{
      if (document.hidden) {{
        pollTimer = setTimeout(pollChangeFeed, 10000);
        return;
      }}
      try {{
        const resp = await fetch('/api/change-feed?v=' + currentFeedVersion);
        if (resp.ok) {{
          const data = await resp.json();
          if (data.version !== currentFeedVersion) {{
            currentFeedVersion = data.version;
            // Update Alerts Count Badge
            if (data.alerts_count !== undefined) {{
              const bellBadge = document.getElementById('top-bar-alert-badge');
              if (bellBadge) {{
                if (data.alerts_count > 0) {{
                  bellBadge.innerText = data.alerts_count;
                  bellBadge.style.display = 'inline-block';
                }} else {{
                  bellBadge.style.display = 'none';
                }}
              }}
            }}
            // Update Profile Info (Shop Name, Tagline, Title, Logo)
            if (data.profile && data.profile.version !== currentProfileVersion) {{
              currentProfileVersion = data.profile.version;
              const titleEl = document.querySelector('.shop-title');
              if (titleEl) titleEl.innerText = '📱 ' + data.profile.name;
              const subEl = document.querySelector('.shop-sub');
              if (subEl) subEl.innerText = data.profile.tagline;
              const logoBox = document.getElementById('top-bar-logo-box');
              const logoImg = document.getElementById('top-bar-logo-img');
              if (logoBox && logoImg) {{
                if (data.profile.has_logo) {{
                  logoImg.src = '/api/shop/logo?v=' + data.profile.version;
                  logoBox.style.display = 'block';
                }} else {{
                  logoBox.style.display = 'none';
                }}
              }}
              document.title = document.title.split(' — ')[0] + ' — ' + data.profile.name;
            }}
          }}
        }}
      }} catch (err) {{}}
      pollTimer = setTimeout(pollChangeFeed, 2000);
    }}
    pollTimer = setTimeout(pollChangeFeed, 2000);
  }})();

  function exitApp() {{
    if (confirm('Do you want to close and exit Mobile Shop ERP?')) {{
      fetch('/api/server/shutdown', {{ method: 'POST' }})
        .then(function() {{
          document.body.innerHTML = '<div style="color:#fff;text-align:center;padding:60px;font-family:sans-serif;"><h2>✅ Server Stopped Cleanly</h2><p style="color:#94a3b8;">You may now safely close this window.</p></div>';
        }})
        .catch(function(err) {{
          alert('Server exit signaled.');
        }});
    }}
  }}
</script>
</head>
<body>

<div class="top-bar">
  <div class="brand-area">
    <div id="top-bar-logo-box" style="{'display:none;' if not shop.get('has_logo') else ''}">
      <img id="top-bar-logo-img" src="/api/shop/logo?v={prof_ver}" style="max-height:36px; max-width:120px; object-fit:contain; border-radius:4px; vertical-align:middle; margin-right:8px;" alt="Logo" />
    </div>
    <div>
      <div class="shop-title">📱 {shop['name']}</div>
      <div class="shop-sub">{shop['tagline']}</div>
    </div>
  </div>

  <div class="search-trigger" onclick="openGlobalSearchModal()" title="Universal Search across all phones, IMEIs, customers, repairs...">
    <span>🔍</span>
    <span>Search anything...</span>
    <kbd>Ctrl+K</kbd>
  </div>

  <div class="top-right">
    <!-- Stock Alert Bell -->
    <div style="position:relative; display:inline-block;">
      <button type="button" class="shortcuts-btn" onclick="toggleAlertsDrawer()" style="position:relative; font-size:13px; padding:4px 9px;" title="Urgent Stock Alerts & Reorder Advice">
        🔔
        <span id="top-bar-alert-badge" style="position:absolute; top:-5px; right:-5px; background:#ef4444; color:#fff; font-size:9.5px; font-weight:800; border-radius:10px; padding:0 4px; line-height:14px; border:1px solid #7f1d1d; {'display:none;' if tot_urgent <= 0 else ''}">{tot_urgent}</span>
      </button>
      <div id="stock-alerts-drawer" style="display:none; position:absolute; right:0; top:36px; width:340px; background:var(--card); border:1px solid var(--card-border); border-radius:10px; box-shadow:0 15px 35px rgba(0,0,0,0.5); z-index:99999; overflow:hidden;">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:rgba(0,0,0,0.2); border-bottom:1px solid var(--card-border);">
          <strong style="font-size:13px; color:var(--text);">🚨 Stock Alerts ({tot_urgent})</strong>
          <span style="font-size:11px;"><span style="color:#f87171; font-weight:bold;">{out_c} Out</span> &bull; <span style="color:#fbbf24; font-weight:bold;">{low_c} Low</span></span>
        </div>
        <div style="max-height:300px; overflow-y:auto;">
          {drawer_items_html}
        </div>
        <div style="padding:8px 12px; background:rgba(0,0,0,0.15); border-top:1px solid var(--card-border); text-align:center;">
          <a href="/inventory/low-stock" class="btn btn-primary btn-sm" style="width:100%; font-size:11.5px; font-weight:bold;">View Low Stock & Reorder Advice &rarr;</a>
        </div>
      </div>
    </div>

    <button type="button" id="theme-toggle-btn" class="theme-toggle-btn" onclick="toggleTheme()" title="Toggle Dark/Light Mode">🌙</button>
    <button type="button" class="shortcuts-btn" onclick="openShortcutsModal()" title="Keyboard Shortcuts Cheat Sheet">⌨️ F1</button>
    <div class="badge-cash">💵 Drawer: Rs. {drawer_cash:,.0f}</div>
    <div class="user-badge">👤 {username.upper()} ({role})</div>
    <a href="/logout" class="logout-btn">Logout</a>
    <button type="button" onclick="exitApp()" class="logout-btn" style="background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); margin-left: 6px; cursor:pointer;" title="Exit & Close ERP Server">⏻ Exit</button>
  </div>
</div>

<nav class="sub-nav">
  {nav_html}
</nav>

<main class="main-content">
  {content}
</main>

<footer class="footer">
  <span>{shop['name']} &bull; Fully Offline Desktop ERP & POS &bull; <strong>Developed by Ahmed</strong></span>
</footer>

</body>
</html>
"""

# ═══════════════════════════════════════════════════════════
# AUTHENTICATION ROUTES
# ═══════════════════════════════════════════════════════════

@app.route("/setup", method=["GET", "POST"])
def setup_wizard_route():
    has_sales = False
    try:
        has_sales = (db.query_one("SELECT COUNT(*) AS c FROM sales") or {}).get("c", 0) > 0
    except Exception:
        pass
    if not auth.is_setup_required() and has_sales and not request.query.get("force"):
        user = auth.get_current_user()
        if not user or user.get("role") != "ADMIN":
            return redirect("/login")
    
    error_msg = ""
    if request.method == "POST":
        shop_name = request.forms.get("shop_name", "").strip()
        shop_address = request.forms.get("shop_address", "").strip()
        shop_phone = request.forms.get("shop_phone", "").strip()
        shop_whatsapp = request.forms.get("shop_whatsapp", "").strip()
        admin_uname = request.forms.get("admin_username", "").strip()
        admin_pass1 = request.forms.get("admin_password", "").strip()
        admin_pass2 = request.forms.get("admin_password_confirm", "").strip()

        if not shop_name:
            error_msg = "Shop Name is required."
        elif not admin_uname:
            error_msg = "Admin Username is required."
        elif len(admin_pass1) < 8:
            error_msg = "Admin password must be at least 8 characters long."
        elif admin_pass1 != admin_pass2:
            error_msg = "Passwords do not match. Please re-type."
        else:
            res = auth.complete_first_run_setup(shop_name, shop_address, shop_phone, shop_whatsapp, admin_uname, admin_pass1)
            if res["success"]:
                rec_key = res["recovery_key"]
                return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Setup Complete — Recovery Key</title>
<style>
  body {{ background: #0f172a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
  .box {{ background: #1e293b; border: 1px solid #334155; padding: 36px; border-radius: 12px; width: 480px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); text-align: center; }}
  .key-box {{ background: #0f172a; border: 2px dashed #3b82f6; padding: 14px; border-radius: 8px; font-family: monospace; font-size: 19px; font-weight: bold; letter-spacing: 2px; color: #60a5fa; margin: 20px 0; user-select: all; }}
  .alert-box {{ background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); padding: 12px; border-radius: 8px; color: #fbbf24; font-size: 13px; text-align: left; margin-bottom: 20px; }}
  button {{ width: 100%; padding: 12px; background: #10b981; border: none; border-radius: 8px; color: #fff; font-weight: bold; font-size: 15px; cursor: pointer; }}
  button:hover {{ background: #059669; }}
</style>
</head>
<body>
<div class="box">
  <div style="font-size: 42px;">🔐</div>
  <h2 style="margin: 10px 0 4px;">Admin Recovery Key</h2>
  <p style="color:#94a3b8; font-size: 13px; margin-bottom: 16px;">Setup complete! This 24-character key is the <strong>ONLY</strong> way to recover your Admin account if you forget your password.</p>
  
  <div class="key-box">{rec_key}</div>

  <div class="alert-box">
    ⚠️ <strong>Important:</strong> Write down or copy this key and store it safely in your locker or notebook. It will NOT be shown again!
  </div>

  <form action="/login" method="GET">
    <label style="display:flex; align-items:center; gap:8px; font-size:13px; color:#cbd5e1; margin-bottom:18px; text-align:left; cursor:pointer;">
      <input type="checkbox" required style="width:18px; height:18px;"> I have securely saved and written down my Recovery Key.
    </label>
    <button type="submit">Proceed to Login →</button>
  </form>
</div>
</body></html>"""
            else:
                error_msg = res.get("message", "Setup failed.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Initial System Setup — Mobile Shop ERP</title>
<style>
  body {{ background: #0f172a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px 0; }}
  .box {{ background: #1e293b; border: 1px solid #334155; padding: 32px; border-radius: 12px; width: 440px; box-shadow: 0 10px 30px rgba(0,0,0,0.6); }}
  h2 {{ margin-top: 0; margin-bottom: 6px; text-align: center; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 20px; text-align: center; }}
  label {{ display: block; font-size: 12px; font-weight: 600; color: #cbd5e1; margin-top: 12px; margin-bottom: 4px; }}
  input {{ width: 100%; padding: 10px; background: #0f172a; border: 1px solid #475569; border-radius: 6px; color: #fff; box-sizing: border-box; font-size: 13.5px; }}
  input:focus {{ outline: none; border-color: #3b82f6; }}
  button {{ width: 100%; padding: 12px; background: #3b82f6; border: none; border-radius: 6px; color: #fff; font-weight: bold; font-size: 14px; cursor: pointer; margin-top: 24px; }}
  button:hover {{ background: #2563eb; }}
  .err {{ background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #fca5a5; padding: 10px; border-radius: 6px; font-size: 13px; margin-bottom: 14px; }}
</style>
</head>
<body>
<div class="box">
  <h2>🚀 First-Time Shop Setup</h2>
  <p class="sub">Configure your shop details and master admin account</p>
  {f'<div class="err">{error_msg}</div>' if error_msg else ''}
  <form method="POST">
    <div style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #38bdf8; letter-spacing: 0.5px; margin-top: 10px;">🏪 Shop Details</div>
    <label>Shop Name *</label>
    <input type="text" name="shop_name" placeholder="e.g. Al-Madina Mobile & Accessories" required value="PAK MOBILE & ACCESSORIES">
    
    <label>Shop Address</label>
    <input type="text" name="shop_address" placeholder="e.g. Shop # 12, Hafeez Center, Lahore" value="Shop # 15, Ground Floor, Hafeez Center, Lahore">

    <div style="display:flex; gap:10px;">
      <div style="flex:1;">
        <label>Shop Phone</label>
        <input type="text" name="shop_phone" placeholder="03001234567" value="+92 300 1234567">
      </div>
      <div style="flex:1;">
        <label>WhatsApp</label>
        <input type="text" name="shop_whatsapp" placeholder="03001234567" value="+92 300 1234567">
      </div>
    </div>

    <div style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #38bdf8; letter-spacing: 0.5px; margin-top: 18px;">👑 Master Admin Account</div>
    <label>Admin Username *</label>
    <input type="text" name="admin_username" placeholder="e.g. admin" required value="admin">

    <label>Admin Password (min 8 chars) *</label>
    <input type="password" name="admin_password" placeholder="Enter secure password" required minlength="8">

    <label>Confirm Admin Password *</label>
    <input type="password" name="admin_password_confirm" placeholder="Re-enter password" required minlength="8">

    <button type="submit">Complete Setup & Generate Recovery Key →</button>
  </form>
</div>
</body></html>"""

@app.route("/recover-admin", method=["GET", "POST"])
def recover_admin_route():
    shop = printing.get_shop_info()
    error_msg = ""
    if request.method == "POST":
        key = request.forms.get("recovery_key", "").strip()
        pass1 = request.forms.get("new_password", "").strip()
        pass2 = request.forms.get("new_password_confirm", "").strip()
        if not key:
            error_msg = "Recovery Key is required."
        elif len(pass1) < 8:
            error_msg = "New password must be at least 8 characters long."
        elif pass1 != pass2:
            error_msg = "Passwords do not match."
        else:
            res = auth.reset_admin_password_with_recovery_key(key, pass1)
            if res["success"]:
                new_key = res["new_recovery_key"]
                return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Admin Password Reset Successfully</title>
<style>
  body {{ background: #0f172a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .box {{ background: #1e293b; border: 1px solid #334155; padding: 36px; border-radius: 12px; width: 440px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; }}
  .key-box {{ background: #0f172a; border: 2px dashed #10b981; padding: 14px; border-radius: 8px; font-family: monospace; font-size: 18px; font-weight: bold; letter-spacing: 2px; color: #34d399; margin: 16px 0; user-select: all; }}
  a {{ display: inline-block; padding: 11px 24px; background: #3b82f6; border-radius: 6px; color: #fff; font-weight: bold; text-decoration: none; margin-top: 16px; }}
</style>
</head>
<body>
<div class="box">
  <div style="font-size: 42px;">✅</div>
  <h2>Admin Password Reset!</h2>
  <p style="color:#94a3b8; font-size: 13px;">Your password for Admin account <strong>{res['username']}</strong> has been reset.</p>
  <p style="color:#f59e0b; font-size: 12px; margin-top: 14px;"><strong>Your Replacement Recovery Key:</strong></p>
  <div class="key-box">{new_key}</div>
  <p style="color:#94a3b8; font-size: 12px;">The previous key is now expired. Please record this replacement key safely.</p>
  <a href="/login">Proceed to Login</a>
</div>
</body></html>"""
            else:
                error_msg = res.get("message", "Password recovery failed.")

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Admin Recovery — {shop['name']}</title>
<style>
  body {{ background: #0f172a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .box {{ background: #1e293b; border: 1px solid #334155; padding: 32px; border-radius: 10px; width: 380px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; }}
  input {{ width: 100%; padding: 10px; margin: 8px 0; background: #0f172a; border: 1px solid #475569; border-radius: 6px; color: #fff; box-sizing: border-box; font-size: 13.5px; }}
  button {{ width: 100%; padding: 11px; background: #f59e0b; border: none; border-radius: 6px; color: #1e293b; font-weight: bold; font-size: 14px; cursor: pointer; margin-top: 12px; }}
  button:hover {{ background: #d97706; color: #fff; }}
  .err {{ color: #ef4444; font-size: 13px; margin-bottom: 10px; }}
</style>
</head>
<body>
<div class="box">
  <div style="font-size: 36px; margin-bottom: 8px;">🔑</div>
  <h2 style="margin-bottom:6px;">Admin Password Recovery</h2>
  <p style="color:#94a3b8; font-size:12px; margin-bottom:18px;">Enter your 24-character Recovery Key to reset Admin password</p>
  {f'<div class="err">{error_msg}</div>' if error_msg else ''}
  <form method="POST">
    <input type="text" name="recovery_key" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX" required autofocus style="text-align:center; font-family:monospace; letter-spacing:1px;">
    <input type="password" name="new_password" placeholder="New Admin Password (min 8 chars)" required minlength="8">
    <input type="password" name="new_password_confirm" placeholder="Confirm New Password" required minlength="8">
    <button type="submit">Verify Key & Reset Password</button>
  </form>
  <div style="margin-top:16px;"><a href="/login" style="color:#38bdf8; font-size:12px; text-decoration:none;">← Back to Login</a></div>
</div>
</body></html>"""

@app.route("/login", method=["GET", "POST"])
def login_route():
    if auth.is_setup_required():
        return redirect("/setup")

    shop = printing.get_shop_info()
    error_msg = ""
    if request.method == "POST":
        u = request.forms.get("username", "").strip()
        p = request.forms.get("password", "").strip()
        res = auth.authenticate(u, p, ip=request.remote_addr)
        if isinstance(res, dict) and res.get("error") == "RATE_LIMITED":
            error_msg = f"Too many failed login attempts! Please wait {res.get('wait_seconds', 30)} seconds."
        elif res:
            s = get_session()
            s["uid"] = res["id"]
            s.save()
            return redirect("/pos")
        else:
            error_msg = "Invalid username or password!"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>Login — {shop['name']}</title>
<style>
  body {{ background: #0f172a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .box {{ background: #1e293b; border: 1px solid #334155; padding: 32px; border-radius: 10px; width: 360px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; }}
  input {{ width: 100%; padding: 10px; margin: 8px 0; background: #0f172a; border: 1px solid #475569; border-radius: 6px; color: #fff; box-sizing: border-box; font-size: 14px; }}
  button {{ width: 100%; padding: 11px; background: #3b82f6; border: none; border-radius: 6px; color: #fff; font-weight: bold; font-size: 14px; cursor: pointer; margin-top: 10px; }}
  button:hover {{ background: #2563eb; }}
  .err {{ color: #ef4444; font-size: 13px; margin-bottom: 10px; }}
</style>
</head>
<body>
<div class="box">
  <h2 style="margin-bottom:6px;">📱 {shop['name']}</h2>
  <p style="color:#94a3b8; font-size:12px; margin-bottom:18px;">Sign in to Mobile Shop ERP</p>
  {f'<div class="err">{error_msg}</div>' if error_msg else ''}
  <form method="POST">
    <input type="text" name="username" placeholder="Username" required autofocus>
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">Sign In</button>
  </form>
  <div style="margin-top:14px; display:flex; justify-content:space-between; font-size:12px;">
    <a href="/recover-admin" style="color:#38bdf8; text-decoration:none;">Forgot password?</a>
    <a href="/setup" style="color:#64748b; text-decoration:none;">First run setup</a>
  </div>
  <div style="margin-top:20px; font-size:11px; color:#64748b;">Offline Desktop POS &bull; Developed by Ahmed</div>
</div>
</body></html>"""

@app.route("/logout")
def logout_route():
    s = get_session()
    if s:
        s.delete()
    return redirect("/login")

@app.route("/my-account")
def my_account_screen():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    
    content = f"""
    <div style="max-width:700px; margin:0 auto;">
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header">
          <div class="card-title">👤 My Account: {user['username'].upper()}</div>
          <span class="badge badge-info">{user['role']}</span>
        </div>
        <div style="padding:12px 0;">
          <p style="color:var(--text-muted); font-size:13px;">Full Name: <strong>{user.get('full_name') or user['username']}</strong></p>
          <p style="color:var(--text-muted); font-size:13px;">Account Created: <strong>{user.get('created_at') or 'Initial Setup'}</strong></p>
          <p style="color:var(--text-muted); font-size:13px;">Last Login: <strong>{user.get('last_login') or 'Now'}</strong></p>
        </div>
      </div>

      <div class="card" style="margin-bottom:20px;">
        <div class="card-title" style="margin-bottom:12px;">🔑 Change My Password</div>
        <form id="change-pwd-form" onsubmit="event.preventDefault(); submitChangePassword();">
          <div class="form-group">
            <label class="form-label">Current Password *</label>
            <input type="password" id="cur-pass" class="form-control" required>
          </div>
          <div class="form-group">
            <label class="form-label">New Password (min 6 characters) *</label>
            <input type="password" id="new-pass" class="form-control" required minlength="6">
          </div>
          <div class="form-group">
            <label class="form-label">Confirm New Password *</label>
            <input type="password" id="confirm-pass" class="form-control" required minlength="6">
          </div>
          <div id="pwd-msg" style="margin-bottom:10px; font-size:13px;"></div>
          <button type="submit" class="btn btn-primary">Update Password</button>
        </form>
      </div>

      {"<div class='card'>" + f'''
        <div class="card-title" style="margin-bottom:12px;">🛡️ Cashier Override PIN (Admin Only)</div>
        <p style="color:var(--text-muted); font-size:12.5px; margin-bottom:14px;">
          Set a 4 to 8 digit secret PIN to authorize special cashier discounts or returns at POS counter.
        </p>
        <form id="set-pin-form" onsubmit="event.preventDefault(); submitSetPin();">
          <div class="form-group">
            <label class="form-label">Admin Override PIN (4-8 digits) *</label>
            <input type="password" id="admin-pin-val" class="form-control" placeholder="e.g. 1234" maxlength="8" required>
          </div>
          <div id="pin-msg" style="margin-bottom:10px; font-size:13px;"></div>
          <button type="submit" class="btn btn-warning">Save Override PIN</button>
        </form>
      </div>''' if is_admin else ""}
    </div>

    <script>
      async function submitChangePassword() {{
        const cur = document.getElementById('cur-pass').value;
        const p1 = document.getElementById('new-pass').value;
        const p2 = document.getElementById('confirm-pass').value;
        const msg = document.getElementById('pwd-msg');

        if (p1 !== p2) {{
          msg.innerHTML = '<span style="color:#ef4444;">Passwords do not match!</span>';
          return;
        }}

        try {{
          const res = await fetch('/api/users/change-password', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{current_password: cur, new_password: p1}})
          }});
          const data = await res.json();
          if (data.success) {{
            msg.innerHTML = '<span style="color:#10b981;">✅ ' + data.message + '</span>';
            document.getElementById('change-pwd-form').reset();
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">❌ ' + data.message + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Error updating password.</span>';
        }}
      }}

      async function submitSetPin() {{
        const pin = document.getElementById('admin-pin-val').value;
        const msg = document.getElementById('pin-msg');
        try {{
          const res = await fetch('/api/users/set-pin', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{pin: pin}})
          }});
          const data = await res.json();
          if (data.success) {{
            msg.innerHTML = '<span style="color:#10b981;">✅ ' + data.message + '</span>';
            document.getElementById('set-pin-form').reset();
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">❌ ' + data.message + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Error saving PIN.</span>';
        }}
      }}
    </script>
    """
    return layout("My Account", content, "settings", user)

@app.route("/settings/users")
def settings_users_screen():
    user = require_admin()
    users_list = db.query_all("SELECT id, username, role, full_name, is_active, last_login, created_at, permissions, can_backdate FROM users ORDER BY role ASC, username ASC")
    
    rows_html = ""
    for u in users_list:
        is_cur = (u["id"] == user["id"])
        status_badge = '<span class="badge badge-success">Active</span>' if u["is_active"] else '<span class="badge badge-danger">Disabled</span>'
        role_badge = '<span class="badge badge-purple">Admin</span>' if u["role"] == "ADMIN" else '<span class="badge badge-info">Employee</span>'
        toggle_label = "Disable" if u["is_active"] else "Enable"
        toggle_cls = "btn-danger" if u["is_active"] else "btn-success"
        
        actions = f"""
          <button class="btn btn-secondary btn-sm" onclick="openResetModal({u['id']}, '{u['username']}')">Reset Password</button>
        """
        if u["role"] != "ADMIN":
            raw_perms = html.escape(u.get("permissions") or "{}")
            actions += f"""
              <button class="btn btn-primary btn-sm" data-uid="{u['id']}" data-uname="{u['username']}" data-perms="{raw_perms}" data-bd="{1 if u.get('can_backdate') else 0}" onclick="openPermsModal(this)">🔑 Permissions</button>
            """
        if not is_cur:
            actions += f"""
              <button class="btn {toggle_cls} btn-sm" onclick="toggleUserStatus({u['id']}, {0 if u['is_active'] else 1})">{toggle_label}</button>
            """
            if u["role"] != "ADMIN":
                actions += f"""
              <button class="btn btn-danger btn-sm" style="margin-left:4px;" onclick="deleteEmployee({u['id']}, '{u['username']}')">🗑️ Delete</button>
            """

        rows_html += f"""
        <tr>
          <td><strong>{u['username']}</strong> {" (You)" if is_cur else ""}</td>
          <td>{u['full_name'] or '-'}</td>
          <td>{role_badge}</td>
          <td>{status_badge}</td>
          <td>{u['last_login'] or 'Never'}</td>
          <td style="text-align:right;">{actions}</td>
        </tr>
        """

    content = f"""
    <div style="max-width:960px; margin:0 auto;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <div style="display:flex; gap:8px;">
          <a href="/settings" class="btn btn-secondary">⚙️ Shop & Printer</a>
          <a href="/settings/users" class="btn btn-primary">👥 Users & Permissions</a>
          <a href="/settings/lookups" class="btn btn-secondary">📋 Lists & Categories</a>
          <a href="/settings/scanner-test" class="btn btn-secondary">🔬 USB Scanner Diagnostics</a>
          <a href="/settings/diagnostics" class="btn btn-secondary">🩺 System Health</a>
        </div>
        <button class="btn btn-success" onclick="openAddEmployeeModal()">+ Add Employee</button>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">👥 Team & Employee Accounts</div>
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Full Name</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Add Employee Modal -->
    <div id="add-emp-modal" class="search-modal-backdrop" style="display:none; align-items:center; padding-top:0;">
      <div class="search-modal-box" style="padding:24px; max-width:440px;">
        <h3 style="margin-top:0; margin-bottom:12px; color:var(--text);">+ Add New Employee</h3>
        <form onsubmit="event.preventDefault(); submitAddEmployee();">
          <div class="form-group"><label class="form-label">Username *</label><input type="text" id="add-emp-uname" class="form-control" required></div>
          <div class="form-group"><label class="form-label">Full Name</label><input type="text" id="add-emp-fullname" class="form-control"></div>
          <div class="form-group"><label class="form-label">Temporary Password *</label><input type="password" id="add-emp-pass" class="form-control" required minlength="6"></div>
          <div id="add-emp-msg" style="margin-bottom:10px; font-size:13px;"></div>
          <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeAddEmployeeModal()">Cancel</button>
            <button type="submit" class="btn btn-success">Create Account</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Reset Password Modal -->
    <div id="reset-pwd-modal" class="search-modal-backdrop" style="display:none; align-items:center; padding-top:0;">
      <div class="search-modal-box" style="padding:24px; max-width:440px;">
        <h3 style="margin-top:0; margin-bottom:12px; color:var(--text);">Reset Password for <span id="reset-target-name"></span></h3>
        <form onsubmit="event.preventDefault(); submitResetPassword();">
          <input type="hidden" id="reset-target-id">
          <div class="form-group"><label class="form-label">New Temporary Password *</label><input type="password" id="reset-pass-val" class="form-control" required minlength="6"></div>
          <div id="reset-pwd-msg" style="margin-bottom:10px; font-size:13px;"></div>
          <div style="display:flex; gap:8px; justify-content:flex-end; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeResetModal()">Cancel</button>
            <button type="submit" class="btn btn-warning">Reset Password</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Employee Permissions Modal -->
    <div id="perms-modal" class="search-modal-backdrop" style="display:none; align-items:center; padding-top:0;">
      <div class="search-modal-box" style="padding:24px; max-width:540px;">
        <h3 style="margin-top:0; margin-bottom:12px; color:var(--text);">🔑 Granular Permissions for <span id="perms-target-name" style="color:#38bdf8;"></span></h3>
        <p style="font-size:12px; color:#94a3b8; margin-bottom:16px;">
          Select the administrative and operational modules this employee is permitted to access. Unchecked modules are strictly forbidden.
        </p>
        <form id="form-edit-perms" onsubmit="event.preventDefault(); submitSavePermissions();">
          <input type="hidden" id="perms-target-id">
          
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px;">
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-pos" name="pos">
              <span>🛒 POS Billing / Checkout</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-inventory" name="inventory_view">
              <span>📦 Inventory & Stock View</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-sales" name="sales_view">
              <span>📊 Daily Sales Reports</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-software" name="software_jobs">
              <span>💻 Software Services</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-repairs" name="repair_jobs">
              <span>🔧 Repair Workshop</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-quick-services" name="quick_services">
              <span>⚡ Quick Services (Load)</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-trade-in" name="trade_in">
              <span>🔄 Trade-In Buy-Back</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-expenses" name="expenses_entry">
              <span>💸 Record Expenses</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-alerts" name="manage_stock_alerts">
              <span>🚨 Stock Alert Mgmt</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-lists" name="add_list_options">
              <span>📋 Add Dropdown Lists</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="perm-stock" name="manage_stock">
              <span>📦 Direct Add Stock</span>
            </label>
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer; grid-column:span 2;">
              <input type="checkbox" id="perm-backdate" name="can_backdate">
              <span style="color:#f59e0b; font-weight:600;">🕒 Allow Back-Dated Transactions</span>
            </label>
          </div>

          <div id="perms-msg" style="margin-bottom:10px; font-size:13px;"></div>
          <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button type="button" class="btn btn-secondary" onclick="closePermsModal()">Cancel</button>
            <button type="submit" class="btn btn-primary font-weight-bold">💾 Save Permissions</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function openAddEmployeeModal() {{
        document.getElementById('add-emp-msg').innerText = '';
        document.getElementById('add-emp-modal').style.display = 'flex';
      }}
      function closeAddEmployeeModal() {{
        document.getElementById('add-emp-modal').style.display = 'none';
      }}
      async function submitAddEmployee() {{
        const u = document.getElementById('add-emp-uname').value;
        const fn = document.getElementById('add-emp-fullname').value;
        const p = document.getElementById('add-emp-pass').value;
        const msg = document.getElementById('add-emp-msg');
        try {{
          const res = await fetch('/api/users/create', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{username: u, full_name: fn, password: p}})
          }});
          const data = await res.json();
          if (data.success) {{
            window.location.reload();
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">' + data.message + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Failed to create account</span>';
        }}
      }}

      function openResetModal(id, uname) {{
        document.getElementById('reset-target-id').value = id;
        document.getElementById('reset-target-name').innerText = uname;
        document.getElementById('reset-pass-val').value = '';
        document.getElementById('reset-pwd-msg').innerText = '';
        document.getElementById('reset-pwd-modal').style.display = 'flex';
      }}
      function closeResetModal() {{
        document.getElementById('reset-pwd-modal').style.display = 'none';
      }}
      async function submitResetPassword() {{
        const id = document.getElementById('reset-target-id').value;
        const p = document.getElementById('reset-pass-val').value;
        const msg = document.getElementById('reset-pwd-msg');
        try {{
          const res = await fetch('/api/users/reset-password', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{user_id: id, new_password: p}})
          }});
          const data = await res.json();
          if (data.success) {{
            closeResetModal();
            alert(data.message);
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">' + data.message + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Failed to reset password</span>';
        }}
      }}

      async function toggleUserStatus(id, activeVal) {{
        if (!confirm('Are you sure you want to change this user status?')) return;
        try {{
          const res = await fetch('/api/users/toggle-status', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{user_id: id, is_active: activeVal}})
          }});
          const data = await res.json();
          if (data.success) {{
            window.location.reload();
          }} else {{
            alert(data.message);
          }}
        }} catch(e) {{
          alert('Failed to update status');
        }}
      }}

      function openPermsModal(btn) {{
        const uid = btn.dataset.uid;
        const uname = btn.dataset.uname;
        let perms = {{}};
        try {{
          perms = JSON.parse(btn.dataset.perms || '{{}}');
        }} catch(e) {{}}
        const canBd = btn.dataset.bd === '1';
        
        document.getElementById('perms-target-id').value = uid;
        document.getElementById('perms-target-name').innerText = uname;
        document.getElementById('perms-msg').innerText = '';
        
        const form = document.getElementById('form-edit-perms');
        const inputs = form.querySelectorAll('input[type="checkbox"]');
        inputs.forEach(cb => {{
          if (cb.name === 'can_backdate') {{
            cb.checked = canBd || !!perms['can_backdate'];
          }} else if (cb.name in perms) {{
            cb.checked = !!perms[cb.name];
          }} else {{
            cb.checked = ['pos', 'inventory_view', 'sales_view', 'software_jobs', 'repair_jobs', 'quick_services'].includes(cb.name);
          }}
        }});
        document.getElementById('perms-modal').style.display = 'flex';
      }}

      function closePermsModal() {{
        document.getElementById('perms-modal').style.display = 'none';
      }}

      async function submitSavePermissions() {{
        const uid = document.getElementById('perms-target-id').value;
        const msg = document.getElementById('perms-msg');
        const form = document.getElementById('form-edit-perms');
        const inputs = form.querySelectorAll('input[type="checkbox"]');
        const perms = {{}};
        inputs.forEach(cb => {{
          perms[cb.name] = cb.checked;
        }});
        try {{
          const res = await fetch('/api/users/update-permissions', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{user_id: uid, permissions: perms}})
          }});
          const data = await res.json();
          if (data.success) {{
            window.location.reload();
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">' + (data.message || 'Failed to update') + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Failed to save permissions</span>';
        }}
      }}

      async function deleteEmployee(id, uname) {{
        if (!confirm('Are you sure you want to delete employee "' + uname + '"?\\n\\nIf this account has past sales, expenses, or repair records, it will be safely deactivated and archived to preserve your shop audit history.')) return;
        try {{
          const res = await fetch('/api/users/delete', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{user_id: id}})
          }});
          const data = await res.json();
          alert(data.message);
          if (data.success) {{
            window.location.reload();
          }}
        }} catch(e) {{
          alert('Failed to delete employee account.');
        }}
      }}
    </script>
    """
    return layout("Users & Permissions", content, "settings", user)

# ═══════════════════════════════════════════════════════════
# USER MANAGEMENT API ROUTES
# ═══════════════════════════════════════════════════════════

@app.route("/api/users/create", method="POST")
def api_users_create():
    admin = require_admin()
    data = request.json or {}
    res = auth.create_employee(
        username=data.get("username"),
        password=data.get("password"),
        full_name=data.get("full_name", ""),
        current_admin_id=admin["id"],
        current_admin_name=admin["username"]
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/reset-password", method="POST")
def api_users_reset_password():
    admin = require_admin()
    data = request.json or {}
    res = auth.reset_user_password(
        target_user_id=int(data.get("user_id") or 0),
        new_password=data.get("new_password", ""),
        current_admin_id=admin["id"],
        current_admin_name=admin["username"]
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/toggle-status", method="POST")
def api_users_toggle_status():
    admin = require_admin()
    data = request.json or {}
    res = auth.toggle_user_status(
        target_user_id=int(data.get("user_id") or 0),
        is_active=bool(data.get("is_active")),
        current_admin_id=admin["id"],
        current_admin_name=admin["username"]
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/update-permissions", method="POST")
def api_users_update_permissions():
    admin = require_admin()
    data = request.json or {}
    uid = int(data.get("user_id") or 0)
    perms = data.get("permissions") or {}
    can_bd = 1 if perms.get("can_backdate") else 0
    with db.get_connection() as cx:
        cx.execute("UPDATE users SET permissions = ?, can_backdate = ? WHERE id = ?",
                   (json.dumps(perms), can_bd, uid))
        cx.commit()
    auth.log_audit(admin["id"], admin["username"], "UPDATE_PERMISSIONS", "users", str(uid), "", json.dumps(perms))
    response.content_type = "application/json"
    return json.dumps({"success": True})

@app.route("/api/users/delete", method="POST")
def api_users_delete():
    admin = require_admin()
    data = request.json or {}
    uid = safe_int(data.get("user_id"))
    res = auth.delete_employee(
        target_user_id=uid,
        current_admin_id=admin["id"],
        current_admin_name=admin["username"]
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/change-password", method="POST")
def api_users_change_password():
    user = require_login()
    data = request.json or {}
    res = auth.change_own_password(
        user_id=user["id"],
        current_password=data.get("current_password", ""),
        new_password=data.get("new_password", "")
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/set-pin", method="POST")
def api_users_set_pin():
    admin = require_admin()
    data = request.json or {}
    res = auth.set_admin_override_pin(
        pin_code=data.get("pin", ""),
        admin_id=admin["id"],
        admin_name=admin["username"]
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/users/verify-pin", method="POST")
def api_users_verify_pin():
    data = request.json or {}
    pin = data.get("pin", "")
    is_valid = auth.verify_admin_override_pin(pin)
    response.content_type = "application/json"
    return json.dumps({"valid": is_valid})

# ═══════════════════════════════════════════════════════════
# DASHBOARD ROUTE
# ═══════════════════════════════════════════════════════════

@app.route("/")
def dashboard_route():
    user = require_login()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # KPIs
    sales_today = db.query_one("SELECT COALESCE(SUM(grand_total), 0) AS total, COUNT(*) AS c FROM sales WHERE substr(created_at, 1, 10) = ? AND status != 'CANCELLED'", (today,))
    phones_stock = db.query_one("SELECT COUNT(*) AS c FROM units WHERE status = 'IN_STOCK'")
    repairs_active = db.query_one("SELECT COUNT(*) AS c FROM repair_jobs WHERE status NOT IN ('DELIVERED', 'CANCELLED', 'RETURNED_UNREPAIRED')")
    overdue_inst = db.query_one("SELECT COUNT(*) AS c FROM installment_schedule WHERE status != 'PAID' AND due_date < ?", (today,))

    # 5 Stream Earnings snapshot (month to date)
    m_start = datetime.now().strftime("%Y-%m-01")
    earnings = accounting.get_earnings_center(m_start, today)

    # Stock Alert Summary & Top Urgent Items
    alert_sum = alert_engine.get_alert_summary()
    top_urgent = alert_engine.get_urgent_alert_items(5)

    urgent_rows = ""
    for u in top_urgent:
        st_badge = "badge-danger" if u["state"] == "OUT" else "badge-warning"
        st_lbl = "OUT OF STOCK" if u["state"] == "OUT" else f"LOW ({u['current_stock']} left)"
        specs = f"{u['ram']} {u['storage']} {u['color']}".strip()
        urgent_rows += f"""
        <tr>
          <td><strong>{u['brand']} {u['model_name']}</strong><br><small style="color:#94a3b8;">{specs}</small></td>
          <td><span class="badge {st_badge}">{st_lbl}</span></td>
          <td style="text-align:center; color:#94a3b8;">Alert at {u['effective_level']}</td>
          <td style="text-align:right;">
            <a href="/purchasing/receive" class="btn btn-sm btn-primary" style="padding:2px 8px; font-size:11px;">+ Reorder</a>
          </td>
        </tr>
        """

    # Recent sales
    recent_sales = db.query_all("SELECT * FROM sales ORDER BY id DESC LIMIT 6")

    rows_html = ""
    for s in recent_sales:
        rows_html += f"""
        <tr>
          <td><a href="/print/sale/{s['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">{s['invoice_no']}</a></td>
          <td>{s['created_at'][11:16]}</td>
          <td>{s['customer_name']}</td>
          <td>Rs. {s['grand_total']:,.0f}</td>
          <td><span class="badge badge-info">{s['payment_method']}</span></td>
        </tr>
        """

    content = f"""
    <!-- Top KPI Grid with Smart Stock Alerts -->
    <div style="display:grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px;">
      <div class="card" style="border-left: 4px solid var(--primary); padding:12px;">
        <div style="font-size: 10.5px; color: var(--text-muted);">TODAY'S SALES</div>
        <div style="font-size: 19px; font-weight: 800; color: #fff; margin-top: 2px;">Rs. {sales_today['total']:,.0f}</div>
        <div style="font-size: 10.5px; color: #94a3b8;">{sales_today['c']} Invoices</div>
      </div>
      <div class="card" style="border-left: 4px solid var(--success); padding:12px;">
        <div style="font-size: 10.5px; color: var(--text-muted);">PHONES IN STOCK</div>
        <div style="font-size: 19px; font-weight: 800; color: #34d399; margin-top: 2px;">{phones_stock['c']} Devices</div>
        <div style="font-size: 10.5px; color: #94a3b8;">By unique IMEI</div>
      </div>
      <div class="card" style="border-left: 4px solid #ef4444; padding:12px; cursor:pointer;" onclick="window.location.href='/inventory/low-stock'">
        <div style="font-size: 10.5px; color: #f87171; font-weight:bold;">🚨 OUT OF STOCK</div>
        <div style="font-size: 19px; font-weight: 800; color: #ef4444; margin-top: 2px;">{alert_sum['out_count']} Items</div>
        <div style="font-size: 10.5px; color: #94a3b8;">Zero stock remaining &rarr;</div>
      </div>
      <div class="card" style="border-left: 4px solid #f59e0b; padding:12px; cursor:pointer;" onclick="window.location.href='/inventory/low-stock'">
        <div style="font-size: 10.5px; color: #fbbf24; font-weight:bold;">⚠️ LOW STOCK</div>
        <div style="font-size: 19px; font-weight: 800; color: #f59e0b; margin-top: 2px;">{alert_sum['low_count']} Items</div>
        <div style="font-size: 10.5px; color: #94a3b8;">Below alert level &rarr;</div>
      </div>
      <div class="card" style="border-left: 4px solid var(--warning); padding:12px;">
        <div style="font-size: 10.5px; color: var(--text-muted);">ACTIVE REPAIRS</div>
        <div style="font-size: 19px; font-weight: 800; color: #fbbf24; margin-top: 2px;">{repairs_active['c']} Jobs</div>
        <div style="font-size: 10.5px; color: #94a3b8;">In workshop</div>
      </div>
      <div class="card" style="border-left: 4px solid var(--danger); padding:12px;">
        <div style="font-size: 10.5px; color: var(--text-muted);">OVERDUE UDHAAR</div>
        <div style="font-size: 19px; font-weight: 800; color: #f87171; margin-top: 2px;">{overdue_inst['c']} Due</div>
        <div style="font-size: 10.5px; color: #94a3b8;">Requires follow-up</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div class="card-title">📈 5-Stream Earnings Center (Month-to-Date)</div>
          <a href="/reports" class="btn btn-sm btn-secondary">Full Report</a>
        </div>
        <div class="grid-5" style="margin-bottom: 12px;">
          <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted);">PHONES</div>
            <div style="font-size: 13px; font-weight: bold; color: #34d399;">Rs. {earnings['stream1_phones']['profit']:,.0f}</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted);">ACCESSORIES</div>
            <div style="font-size: 13px; font-weight: bold; color: #34d399;">Rs. {earnings['stream2_accessories']['profit']:,.0f}</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted);">REPAIRS</div>
            <div style="font-size: 13px; font-weight: bold; color: #34d399;">Rs. {earnings['stream3_repairs']['profit']:,.0f}</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted);">SOFTWARE</div>
            <div style="font-size: 13px; font-weight: bold; color: #34d399;">Rs. {earnings['stream4_software']['profit']:,.0f}</div>
          </div>
          <div style="background: rgba(0,0,0,0.2); padding: 8px; border-radius: 6px; text-align: center;">
            <div style="font-size: 10px; color: var(--text-muted);">QUICK SERV.</div>
            <div style="font-size: 13px; font-weight: bold; color: #34d399;">Rs. {earnings['stream5_quick_services']['profit']:,.0f}</div>
          </div>
        </div>
        <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); padding: 12px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 13px; font-weight: bold;">NET CLEAR PROFIT THIS MONTH:</span>
          <span style="font-size: 18px; font-weight: 800; color: #34d399;">Rs. {earnings['net_profit']:,.0f}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">🧾 Recent POS Sales</div>
          <a href="/pos" class="btn btn-sm btn-primary">Open POS</a>
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Time</th>
                <th>Customer</th>
                <th>Total</th>
                <th>Method</th>
              </tr>
            </thead>
            <tbody>
              {rows_html or '<tr><td colspan="5" style="text-align:center; color:#888;">No sales recorded yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Urgent Stock Alerts Card -->
    <div class="card" style="margin-top: 16px;">
      <div class="card-header">
        <div class="card-title">🚨 Urgent Stock Reorder Advice (Top 5 Urgencies)</div>
        <a href="/inventory/low-stock" class="btn btn-sm btn-primary">View All & Reorder Advice &rarr;</a>
      </div>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>Product & Variant</th>
              <th>Stock Status</th>
              <th style="text-align:center;">Threshold</th>
              <th style="text-align:right;">Action</th>
            </tr>
          </thead>
          <tbody>
            {urgent_rows or '<tr><td colspan="4" style="text-align:center; padding:16px; color:#10b981;">✅ All stock levels are currently above alert thresholds.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """
    return layout("Dashboard", content, "pos", user)

# ═══════════════════════════════════════════════════════════
# POS (POINT OF SALE) TERMINAL
# ═══════════════════════════════════════════════════════════

@app.route("/pos")
def pos_screen():
    user = require_login()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Quick accessory buttons
    quick_accs = db.query_all("""
        SELECT v.id, v.retail_price, v.color, p.name AS product_name, v.stock_quantity
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE p.item_type = 'ACCESSORY' AND v.is_archived = 0
        LIMIT 8
    """)
    acc_chips = ""
    for a in quick_accs:
        acc_chips += f"""
        <button type="button" class="btn btn-secondary btn-sm" onclick="addAccessoryCart({a['id']}, '{a['product_name']} ({a['color']})', {a['retail_price']})" style="font-size:11px; margin:2px;">
          + {a['product_name'][:18]} (Rs. {a['retail_price']:,.0f})
        </button>
        """

    content = f"""
    <div class="grid-2">
      <!-- Left: Scanning & Cart Table -->
      <div>
        <div class="card" style="margin-bottom: 12px; padding: 12px; position: relative;">
          <div style="display: flex; gap: 8px;">
            <input type="text" id="pos-scan-input" class="form-control" placeholder="🔍 Scan IMEI sticker, accessory barcode, or type name..." autofocus style="font-size: 15px; font-weight: bold; letter-spacing: 0.5px; border: 2px solid var(--primary);" autocomplete="off">
            <button type="button" class="btn btn-primary" onclick="handleScanSubmit()">Add</button>
          </div>
          <!-- Live Typeahead Search Dropdown for POS -->
          <div id="pos-search-dropdown" class="pos-search-results-dropdown" style="display: none;"></div>
          <div style="margin-top: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <div style="font-size: 11px; color: var(--text-muted);">Quick Accessories:</div>
              <div>{acc_chips}</div>
            </div>
            <button type="button" class="btn btn-warning btn-sm" id="btn-toggle-top-sellers" onclick="togglePosTopSellers()" style="font-size: 11px; padding: 3px 8px; font-weight: bold; background: rgba(245, 158, 11, 0.2); border: 1px solid #f59e0b; color: #fbbf24;">
              🔥 Top Sellers
            </button>
          </div>
          <!-- Collapsible POS Top Sellers Quick Panel -->
          <div id="pos-top-sellers-panel" style="display: none; background: #0f172a; border: 1px solid #f59e0b; border-radius: 8px; padding: 10px; margin-top: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.5);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <div style="font-size: 12px; font-weight: bold; color: #fbbf24;">🔥 Fast-Selling Products (Last 30 Days)</div>
              <div id="pos-top-seller-cat-chips" style="display: flex; gap: 4px; flex-wrap: wrap;"></div>
            </div>
            <div id="pos-top-sellers-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; max-height: 200px; overflow-y: auto;">
              <div style="color: #94a3b8; font-size: 11.5px; padding: 8px;">Loading fast sellers...</div>
            </div>
          </div>
        </div>

        <div class="card" style="min-height: 480px; display: flex; flex-direction: column;">
          <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
            <div style="display: flex; gap: 8px; align-items: center;">
              <div class="card-title">🛒 Invoice Cart (<span id="cart-item-count">0</span> items)</div>
              <a href="/sales" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 3px 8px; font-weight: bold;" title="View today's sales bills">🧾 Today's Bills</a>
              <a href="/returns" class="btn btn-secondary btn-sm" style="font-size: 11px; padding: 3px 8px; font-weight: bold;" title="Process returns & exchanges">🔄 Returns</a>
            </div>
            <div style="display: flex; gap: 6px; align-items: center;">
              <button type="button" class="btn btn-warning btn-sm" id="btn-hold-cart" onclick="holdCurrentCart()" style="font-size: 11.5px; padding: 4px 10px; font-weight: bold; background: rgba(245, 158, 11, 0.2); border: 1px solid #f59e0b; color: #f59e0b;">⏸️ Hold Cart</button>
              <span id="held-carts-container"></span>
              <button type="button" class="btn btn-danger btn-sm" onclick="clearCart()" style="font-size: 11.5px; padding: 4px 10px;">Clear Cart</button>
            </div>
          </div>
          <div class="table-responsive" style="flex: 1;">
            <table class="data-table" id="pos-cart-table">
              <thead>
                <tr>
                  <th style="width: 35%;">Item & Specifications</th>
                  <th style="width: 20%;">IMEI / Serial</th>
                  <th style="width: 20%; text-align: right;">Price & Disc (Rs.)</th>
                  <th style="width: 13%; text-align: center;">Qty</th>
                  <th style="width: 12%; text-align: right;">Total / Remove</th>
                </tr>
              </thead>
              <tbody id="cart-tbody">
                <tr><td colspan="5" style="text-align: center; color: #64748b; padding: 40px;">Cart is empty. Scan an IMEI or barcode to begin.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Right: Customer, Totals & Payment Panel -->
      <div>
        <div class="card" style="margin-bottom: 12px;">
          <div class="card-header" style="margin-bottom:8px; padding-bottom:6px;">
            <div class="card-title">👤 Customer Details</div>
            <button type="button" class="btn btn-sm btn-primary" onclick="QuickAdd.open('customer', {{}})">+ Add Customer</button>
          </div>
          <div style="position: relative;">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
              <input type="text" id="cust-phone" class="form-control" placeholder="📞 Phone (e.g. 0300...)" oninput="posLookupCustomer(this.value, 'phone')">
              <input type="text" id="cust-name" class="form-control" placeholder="👤 Customer Name" value="Walk-in Customer" oninput="posLookupCustomer(this.value, 'name')" onfocus="if(this.value==='Walk-in Customer') this.select()">
            </div>
            <!-- Live Customer Autocomplete Dropdown -->
            <div id="cust-search-dropdown" style="display:none; position:absolute; top:42px; left:0; right:0; background:#1e293b; border:2px solid #3b82f6; border-radius:8px; box-shadow:0 12px 28px rgba(0,0,0,0.6); max-height:260px; overflow-y:auto; z-index:10001; padding:4px 0;"></div>
          </div>
          <div id="cust-udhaar-pill" style="display:none; margin-top:8px; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); padding:6px 10px; border-radius:6px; font-size:12px; color:#f87171; font-weight:bold; display:flex; justify-content:space-between; align-items:center;">
            <span>⚠️ Previous Udhaar Due: <strong id="cust-udhaar-amt">Rs. 0</strong></span>
            <a id="cust-udhaar-link" href="/credit" target="_blank" style="color:#60a5fa; font-size:11px; text-decoration:underline;">View Khata &rarr;</a>
          </div>
        </div>

        <div class="card">
          <div class="card-title" style="margin-bottom: 12px;">💰 Payment & Billing</div>
          
          <table style="width: 100%; font-size: 13.5px; margin-bottom: 12px;">
            <tr><td>Subtotal:</td><td style="text-align: right; font-weight: bold;" id="disp-subtotal">Rs. 0</td></tr>
            <tr>
              <td>Discount (Rs.):</td>
              <td style="text-align: right;"><input type="number" id="input-discount" class="form-control" value="0" style="width: 100px; text-align: right; display: inline-block;" oninput="updateTotals()"></td>
            </tr>
            <tr style="font-size: 18px; font-weight: 800; border-top: 1px solid var(--card-border); color: #fff;">
              <td style="padding-top: 8px;">GRAND TOTAL:</td>
              <td style="text-align: right; padding-top: 8px; color: #38bdf8;" id="disp-grand-total">Rs. 0</td>
            </tr>
          </table>

          <div class="form-group" style="margin-bottom: 10px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <label class="form-label" style="font-size:12px; margin-bottom:2px;">📅 Sale Date</label>
              <small style="color:#94a3b8; font-size:11px;">Change for back-date sale</small>
            </div>
            <input type="date" id="pos-sale-date" class="form-control" value="{today}" style="padding:6px 10px; font-size:13px; font-weight:bold;">
          </div>

          <div class="form-group">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label class="form-label" style="margin-bottom:0;">Payment Mode</label>
              <span id="pm-active-label" style="font-weight:bold; color:#38bdf8; font-size:11px;">💵 CASH</span>
            </div>
            <!-- Quick 1-Click Payment Buttons -->
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 6px; margin-bottom: 8px;">
              <button type="button" class="btn btn-sm btn-pm-quick" id="btn-pm-cash" onclick="posSetPaymentMethod('CASH')" style="background:#0284c7; color:#fff; font-weight:bold; font-size:12px; padding:7px 2px;">💵 Cash</button>
              <button type="button" class="btn btn-sm btn-pm-quick" id="btn-pm-udhaar" onclick="posSetPaymentMethod('UDHAAR')" style="background:#dc2626; color:#fff; font-weight:bold; font-size:12px; padding:7px 2px;">📝 Udhaar</button>
              <button type="button" class="btn btn-sm btn-pm-quick" id="btn-pm-online" onclick="posSetPaymentMethod('ONLINE')" style="background:#10b981; color:#fff; font-weight:bold; font-size:12px; padding:7px 2px;">📲 Online</button>
              <button type="button" class="btn btn-sm btn-pm-quick" id="btn-pm-card" onclick="posSetPaymentMethod('CARD')" style="background:#6366f1; color:#fff; font-weight:bold; font-size:12px; padding:7px 2px;">💳 Card</button>
            </div>
            <select id="pay-method" class="form-control" onchange="togglePaymentInputs()">
              <option value="CASH">💵 Cash (Cash Drawer)</option>
              <option value="ONLINE">📲 Online (Raast / EasyPaisa / JazzCash / Bank)</option>
              <option value="CARD">💳 Debit / Credit Card</option>
              <option value="UDHAAR">📝 Udhaar / Full Credit</option>
              <option value="INSTALLMENT">📅 Easy Installment Plan</option>
              <option value="TRADE_IN">🔄 Buyback / Trade-In Deduction</option>
            </select>
          </div>

          <div class="form-group" id="group-paid-amount">
            <label class="form-label">Amount Paid by Customer</label>
            <input type="number" id="input-paid" class="form-control" style="font-size: 16px; font-weight: bold; color: #34d399;" value="0" oninput="this.dataset.manual='1'; updateTotals()">
          </div>

          <div id="disp-change-box" style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; display: flex; justify-content: space-between;">
            <span style="font-size: 12.5px;">Return Change:</span>
            <span style="font-size: 15px; font-weight: bold; color: #34d399;" id="disp-change">Rs. 0</span>
          </div>

          <button type="button" id="btn-pay-print" class="btn btn-success" style="width: 100%; padding: 14px; font-size: 16px; font-weight: 800;" onclick="submitCheckout()">
            🖨️ PAY & PRINT RECEIPT (F12 / Enter)
          </button>
        </div>
      </div>
    </div>

    <!-- POS Search Dropdown Styles -->
    <style>
      .pos-search-results-dropdown {{
        position: absolute;
        top: 52px;
        left: 12px;
        right: 12px;
        background: #1e293b;
        border: 2px solid #3b82f6;
        border-radius: 8px;
        box-shadow: 0 16px 36px rgba(0,0,0,0.6);
        max-height: 380px;
        overflow-y: auto;
        z-index: 10000;
        padding: 4px 0;
      }}
      .pos-search-item {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 14px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        cursor: pointer;
        transition: background 0.1s;
      }}
      .pos-search-item:hover, .pos-search-item.highlighted {{
        background: rgba(59, 130, 246, 0.25);
      }}
      .pos-search-item-title {{
        font-weight: 700;
        font-size: 13.5px;
        color: #f8fafc;
      }}
      .pos-search-item-sub {{
        font-size: 11.5px;
        color: #94a3b8;
        margin-top: 2px;
        display: flex;
        gap: 6px;
        align-items: center;
      }}
      .pos-search-item-price {{
        font-size: 14.5px;
        font-weight: 800;
        color: #38bdf8;
        text-align: right;
      }}
      .pos-search-badge-instock {{
        background: rgba(16, 185, 129, 0.2);
        color: #34d399;
        font-size: 10.5px;
        padding: 1px 6px;
        border-radius: 4px;
        font-weight: bold;
      }}
      .pos-search-badge-outstock {{
        background: rgba(239, 68, 68, 0.2);
        color: #f87171;
        font-size: 10.5px;
        padding: 1px 6px;
        border-radius: 4px;
        font-weight: bold;
      }}
    </style>

    <!-- Modal: Select Phone IMEI for POS -->
    <div id="pos-imei-picker-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(3px); z-index:20000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:20px; border-radius:12px; width:540px; max-width:94vw; max-height:85vh; display:flex; flex-direction:column; box-shadow:0 20px 40px rgba(0,0,0,0.5);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--border);">
          <div>
            <h3 id="imei-picker-title" style="font-size:16px; font-weight:800; color:var(--text);">Select Phone Unit (IMEI)</h3>
            <div id="imei-picker-sub" style="font-size:12px; color:var(--text-muted);">Multiple in-stock devices available</div>
          </div>
          <button type="button" onclick="closeImeiPickerModal()" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <div style="margin-bottom:8px;">
          <input type="text" id="imei-picker-filter" class="form-control" placeholder="🔍 Filter IMEI numbers..." style="font-size:13px; padding:6px 10px;" oninput="filterImeiPickerList(this.value)">
        </div>
        <div id="imei-picker-list" style="flex:1; overflow-y:auto; max-height:360px; border:1px solid var(--border); border-radius:6px; background:rgba(0,0,0,0.2);">
        </div>
        <div style="display:flex; justify-content:flex-end; margin-top:12px;">
          <button type="button" class="btn btn-secondary btn-sm" onclick="closeImeiPickerModal()">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Pos JavaScript logic -->
    <script>
      var cart = [];

      window.posSetCustomer = function(c) {{
        document.getElementById('cust-name').value = c.title || c.name || '';
        document.getElementById('cust-phone').value = (c.phone && !c.phone.startsWith('NOP-')) ? c.phone : '';
        const pill = document.getElementById('cust-udhaar-pill');
        const link = document.getElementById('cust-udhaar-link');
        const bal = parseFloat(c.balance_udhaar || 0);
        if (bal > 0) {{
          pill.style.display = 'flex';
          document.getElementById('cust-udhaar-amt').innerText = 'Rs. ' + Math.round(bal).toLocaleString();
          if (link && c.id) link.href = '/credit/customer/' + c.id;
        }} else {{
          pill.style.display = 'none';
        }}
      }};

      window.posSelectCustomer = function(c) {{
        window.posSetCustomer(c);
        const drop = document.getElementById('cust-search-dropdown');
        if (drop) drop.style.display = 'none';
      }};

      let custSearchDebounce = null;
      window.posLookupCustomer = function(val, field) {{
        clearTimeout(custSearchDebounce);
        const q = (val || '').trim();
        const drop = document.getElementById('cust-search-dropdown');
        if (!drop) return;
        if (q.length < 2 || q.toLowerCase() === 'walk-in customer') {{
          drop.style.display = 'none';
          return;
        }}
        custSearchDebounce = setTimeout(async () => {{
          try {{
            const res = await fetch('/api/search/customers?q=' + encodeURIComponent(q));
            const data = await res.json();
            if (data.items && data.items.length > 0) {{
              drop.innerHTML = data.items.map(c => {{
                const bal = parseFloat(c.balance_udhaar || 0);
                const balHtml = bal > 0 ? '<span style="color:#f87171; font-weight:bold; font-size:11px; background:rgba(239,68,68,0.18); border:1px solid rgba(239,68,68,0.3); padding:2px 6px; border-radius:4px;">⚠️ Udhaar: Rs. ' + Math.round(bal).toLocaleString() + '</span>' : '<span style="color:#34d399; font-size:11px;">✅ Clear</span>';
                const pDisp = (!c.phone || c.phone.startsWith('NOP-')) ? '' : ('📞 ' + c.phone);
                const safeJson = JSON.stringify(c).replace(/"/g, '&quot;');
                return '<div class="pos-cust-opt" onmousedown="window.posSelectCustomer(' + safeJson + ')" style="padding:8px 12px; border-bottom:1px solid rgba(255,255,255,0.06); cursor:pointer; display:flex; justify-content:space-between; align-items:center;">' +
                  '<div><strong style="color:#fff; font-size:13px;">' + c.title + '</strong> <span style="color:#94a3b8; font-size:12px; margin-left:6px;">' + pDisp + '</span></div>' +
                  '<div>' + balHtml + '</div>' +
                  '</div>';
              }}).join('');
              drop.style.display = 'block';
            }} else {{
              drop.style.display = 'none';
            }}
          }} catch(e) {{
            drop.style.display = 'none';
          }}
        }}, 120);
      }};

      document.addEventListener('click', function(e) {{
        const drop = document.getElementById('cust-search-dropdown');
        if (drop && !e.target.closest('#cust-search-dropdown') && e.target.id !== 'cust-phone' && e.target.id !== 'cust-name') {{
          drop.style.display = 'none';
        }}
      }});

      window.posSetPaymentMethod = function(pm) {{
        var sel = document.getElementById('pay-method');
        if (sel) {{
          sel.value = pm;
          togglePaymentInputs();
        }}
      }};

      function togglePaymentInputs() {{
        var pm = document.getElementById('pay-method') ? document.getElementById('pay-method').value : 'CASH';
        var paidInput = document.getElementById('input-paid');
        var grandText = document.getElementById('disp-grand-total').innerText.replace(/[^0-9.]/g, '');
        var grand = parseFloat(grandText) || 0;
        
        // Highlight active quick button & update badge
        var lbl = document.getElementById('pm-active-label');
        if (lbl) {{
          if (pm === 'UDHAAR') lbl.innerHTML = '<span style="color:#ef4444;">📝 UDHAAR (CREDIT)</span>';
          else if (pm === 'ONLINE') lbl.innerHTML = '<span style="color:#10b981;">📲 ONLINE</span>';
          else if (pm === 'CARD') lbl.innerHTML = '<span style="color:#6366f1;">💳 CARD</span>';
          else lbl.innerHTML = '<span style="color:#38bdf8;">💵 CASH</span>';
        }}

        ['cash', 'udhaar', 'online', 'card'].forEach(function(k) {{
          var b = document.getElementById('btn-pm-' + k);
          if (b) {{
            var isActive = (k.toUpperCase() === pm);
            b.style.opacity = isActive ? '1' : '0.6';
            b.style.boxShadow = isActive ? '0 0 0 2px #fff' : 'none';
          }}
        }});

        if (pm === 'UDHAAR') {{
          paidInput.value = 0;
          paidInput.dataset.manual = '1';
          updateTotals();
          var cName = document.getElementById('cust-name').value.trim();
          if (!cName || cName.toLowerCase() === 'walk-in customer') {{
            document.getElementById('cust-name').focus();
            if (typeof ScannerEngine !== 'undefined' && ScannerEngine.showToast) {{
              ScannerEngine.showToast('📝 Udhaar selected: Please enter customer name or select an existing customer.', false);
            }}
          }}
        }} else if (pm === 'CASH' || pm === 'ONLINE' || pm === 'CARD') {{
          paidInput.dataset.manual = '0';
          paidInput.value = grand;
          updateTotals();
        }}
      }}

      function updateTotals() {{
        var subtotal = 0;
        cart.forEach(function(item) {{
          var ltot = Math.max(0, (item.unit_price * item.qty) - (item.discount || 0));
          subtotal += ltot;
        }});
        var discount = parseFloat(document.getElementById('input-discount').value) || 0;
        var grand = Math.max(0, subtotal - discount);
        document.getElementById('disp-subtotal').innerText = 'Rs. ' + subtotal.toLocaleString();
        document.getElementById('disp-grand-total').innerText = 'Rs. ' + grand.toLocaleString();
        
        var paidInput = document.getElementById('input-paid');
        var payMethod = document.getElementById('pay-method') ? document.getElementById('pay-method').value : 'CASH';
        if (payMethod === 'UDHAAR') {{
          if (paidInput.dataset.manual !== '1') {{
            paidInput.value = 0;
          }}
        }} else {{
          if (paidInput.dataset.manual !== '1') {{
            paidInput.value = grand;
          }}
        }}
        var paid = parseFloat(paidInput.value) || 0;
        var change = Math.max(0, paid - grand);
        var due = Math.max(0, grand - paid);
        var changeBox = document.getElementById('disp-change-box');
        if (changeBox) {{
          if (due > 0) {{
            changeBox.style.background = 'rgba(239,68,68,0.12)';
            changeBox.style.borderColor = 'rgba(239,68,68,0.35)';
            changeBox.innerHTML = '<span style="font-size:12.5px; color:#f87171; font-weight:bold;">⚠️ Udhaar / Balance Due:</span><span style="font-size:15px; font-weight:bold; color:#f87171;">Rs. ' + due.toLocaleString() + '</span>';
          }} else {{
            changeBox.style.background = 'rgba(16,185,129,0.1)';
            changeBox.style.borderColor = 'rgba(16,185,129,0.3)';
            changeBox.innerHTML = '<span style="font-size:12.5px;">Return Change:</span><span style="font-size:15px; font-weight:bold; color:#34d399;" id="disp-change">Rs. ' + change.toLocaleString() + '</span>';
          }}
        }}
        document.getElementById('cart-item-count').innerText = cart.length;
      }}

      function updateCartPrice(idx, val) {{
        var p = parseFloat(val);
        if (!isNaN(p) && p >= 0) {{
          cart[idx].unit_price = p;
          updateTotals();
          var ltSpan = document.getElementById('line-tot-' + idx);
          if (ltSpan) {{
            var ltot = Math.max(0, (cart[idx].unit_price * cart[idx].qty) - (cart[idx].discount || 0));
            ltSpan.innerText = 'Rs. ' + ltot.toLocaleString();
          }}
        }}
      }}

      function updateCartDiscount(idx, val) {{
        var d = parseFloat(val);
        if (!isNaN(d) && d >= 0) {{
          cart[idx].discount = d;
          updateTotals();
          var ltSpan = document.getElementById('line-tot-' + idx);
          if (ltSpan) {{
            var ltot = Math.max(0, (cart[idx].unit_price * cart[idx].qty) - (cart[idx].discount || 0));
            ltSpan.innerText = 'Rs. ' + ltot.toLocaleString();
          }}
        }}
      }}

      function changeCartQty(idx, delta) {{
        if (cart[idx].item_type === 'PHONE') return;
        var newQ = Math.max(1, (cart[idx].qty || 1) + delta);
        cart[idx].qty = newQ;
        renderCart();
      }}

      function renderCart() {{
        var tbody = document.getElementById('cart-tbody');
        if (cart.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #64748b; padding: 40px;">Cart is empty. Scan an IMEI or barcode to begin.</td></tr>';
          updateTotals();
          return;
        }}
        var html = '';
        cart.forEach(function(item, idx) {{
          var imeiHtml = item.imei1 ? ('<code>' + item.imei1 + '</code><br><small style="color:#10b981;">' + (item.pta_status || 'PTA Approved') + '</small>') : '<span style="color:#888;">N/A (Accessory)</span>';
          var qtyHtml = item.item_type === 'PHONE' ? '<span class="badge badge-info" style="font-size:12px;">1</span>' : (
            '<div style="display:flex; align-items:center; justify-content:center; gap:2px;">' +
            '<button type="button" class="btn btn-secondary btn-xs" style="padding:1px 6px; font-weight:bold;" onclick="changeCartQty(' + idx + ', -1)">-</button>' +
            '<input type="number" min="1" value="' + item.qty + '" style="width:42px; text-align:center; background:#0f172a; color:#fff; border:1px solid #475569; border-radius:4px; padding:2px; font-size:12px;" onchange="updateCartQty(' + idx + ', this.value)">' +
            '<button type="button" class="btn btn-secondary btn-xs" style="padding:1px 6px; font-weight:bold;" onclick="changeCartQty(' + idx + ', 1)">+</button>' +
            '</div>'
          );
          var lineTotal = Math.max(0, (item.unit_price * item.qty) - (item.discount || 0));
          html += '<tr>' +
            '<td><strong>' + item.item_name + '</strong><br><small style="color:#94a3b8;">' + (item.variant_desc || '') + '</small></td>' +
            '<td>' + imeiHtml + '</td>' +
            '<td style="text-align:right;">' +
              '<input type="number" min="0" value="' + item.unit_price + '" style="width:85px; text-align:right; background:#0f172a; color:#fff; border:1px solid #475569; border-radius:4px; padding:2px 5px; font-size:12px; font-weight:600;" onchange="updateCartPrice(' + idx + ', this.value)" title="Unit Price">' +
              '<div style="margin-top:3px; display:flex; align-items:center; justify-content:flex-end; gap:3px;">' +
                '<span style="font-size:10px; color:#94a3b8;">Disc:</span>' +
                '<input type="number" min="0" value="' + (item.discount || 0) + '" style="width:60px; text-align:right; background:#0f172a; color:#f59e0b; border:1px solid #475569; border-radius:4px; padding:1px 4px; font-size:11px;" onchange="updateCartDiscount(' + idx + ', this.value)" title="Line Discount">' +
              '</div>' +
            '</td>' +
            '<td style="text-align:center;">' + qtyHtml + '</td>' +
            '<td style="text-align:right;">' +
              '<div id="line-tot-' + idx + '" style="font-weight:bold; font-size:12.5px; color:#38bdf8;">Rs. ' + lineTotal.toLocaleString() + '</div>' +
              '<button class="btn btn-danger btn-xs" style="padding:1px 6px; margin-top:3px;" onclick="removeCartItem(' + idx + ')" title="Remove item">✕</button>' +
            '</td>' +
            '</tr>';
        }});
        tbody.innerHTML = html;
        updateTotals();
      }}

      function addPhoneUnitToCart(unit) {{
        var uid = parseInt(unit.unit_id || unit.id || 0);
        var vid = parseInt(unit.variant_id || 0);
        for (var i = 0; i < cart.length; i++) {{
          if (cart[i].unit_id === uid && cart[i].item_type === 'PHONE') {{
            ScannerEngine.playErrorBeep();
            ScannerEngine.showToast('This IMEI (' + (unit.imei1 || '') + ') is already in your cart!', false);
            return;
          }}
        }}
        cart.push({{
          item_type: 'PHONE',
          variant_id: vid,
          unit_id: uid,
          id: uid,
          item_name: (unit.brand ? unit.brand + ' ' : '') + (unit.model_name || unit.product_name || ''),
          variant_desc: (unit.ram || '') + '/' + (unit.storage || '') + ' ' + (unit.color || ''),
          imei1: unit.imei1 || '',
          pta_status: unit.pta_status || '',
          unit_price: parseFloat(unit.retail_price || 0),
          qty: 1
        }});
        ScannerEngine.playSuccessBeep();
        ScannerEngine.flashScreen('rgba(16, 185, 129, 0.4)');
        renderCart();
      }}

      function addAccessoryCart(vid, name, price) {{
        for (var i = 0; i < cart.length; i++) {{
          if (cart[i].variant_id === vid && cart[i].item_type !== 'PHONE') {{
            cart[i].qty += 1;
            ScannerEngine.playSuccessBeep();
            renderCart();
            return;
          }}
        }}
        cart.push({{
          item_type: 'ACCESSORY',
          variant_id: vid,
          unit_id: 0,
          item_name: name,
          variant_desc: '',
          imei1: '',
          unit_price: price,
          qty: 1
        }});
        ScannerEngine.playSuccessBeep();
        renderCart();
      }}

      // Universal scan router hook
      window.posAddToCart = function(codeOrData) {{
        const sdd = document.getElementById('pos-search-dropdown');
        if (sdd) {{ sdd.style.display = 'none'; }}
        if (typeof codeOrData === 'object' && codeOrData.success) {{
          if (codeOrData.type === 'UNIT_FOUND' || codeOrData.type === 'PHONE_UNIT') {{
            addPhoneUnitToCart(codeOrData.unit);
          }} else if (codeOrData.type === 'ACCESSORY_FOUND' || codeOrData.type === 'ACCESSORY') {{
            const v = codeOrData.variant;
            addAccessoryCart(v.id || v.variant_id, (v.brand ? v.brand + ' ' : '') + (v.model_name || v.product_name), v.retail_price);
          }}
        }} else if (typeof codeOrData === 'string') {{
          document.getElementById('pos-scan-input').value = codeOrData;
          handleScanSubmit();
        }}
      }};

      function updateCartQty(idx, val) {{
        var q = parseInt(val) || 1;
        cart[idx].qty = Math.max(1, q);
        renderCart();
      }}

      function removeCartItem(idx) {{
        cart.splice(idx, 1);
        renderCart();
      }}

      function clearCart() {{
        if (confirm('Clear entire cart?')) {{ cart = []; renderCart(); }}
      }}

      // ─── HOLD & RESUME CART ──────────────────────────────────
      var heldCarts = JSON.parse(localStorage.getItem('pos_held_carts') || '[]');
      function updateHeldCartsUI() {{
        var container = document.getElementById('held-carts-container');
        if (!container) return;
        if (!heldCarts || heldCarts.length === 0) {{
          container.innerHTML = '';
          return;
        }}
        var html = '<select class="form-control" style="width:auto; display:inline-block; padding:3px 8px; font-size:11px; font-weight:bold; background:#1e293b; color:#f59e0b; border:1px solid #f59e0b; border-radius:4px;" onchange="resumeHeldCart(this.value); this.selectedIndex=0;">';
        html += '<option value="">▶️ Resume (' + heldCarts.length + ' held)...</option>';
        heldCarts.forEach(function(h, idx) {{
          html += '<option value="' + idx + '">#' + (idx+1) + ' ' + (h.customer_name || 'Walk-in') + ' (' + h.items.length + ' items · Rs. ' + (h.total || 0).toLocaleString() + ')</option>';
        }});
        html += '</select>';
        container.innerHTML = html;
      }}
      setTimeout(updateHeldCartsUI, 100);

      function holdCurrentCart() {{
        if (cart.length === 0) {{
          ScannerEngine.showToast('Cart is empty, nothing to hold.', false);
          return;
        }}
        var total = cart.reduce(function(acc, item) {{ return acc + ((item.unit_price || 0) * (item.qty || 1)); }}, 0);
        var custName = document.getElementById('cust-name').value.trim();
        var custPhone = document.getElementById('cust-phone').value.trim();
        heldCarts.push({{
          timestamp: new Date().toLocaleTimeString(),
          customer_name: custName,
          customer_phone: custPhone,
          items: cart,
          total: total
        }});
        localStorage.setItem('pos_held_carts', JSON.stringify(heldCarts));
        cart = [];
        document.getElementById('cust-name').value = 'Walk-in Customer';
        document.getElementById('cust-phone').value = '';
        renderCart();
        updateHeldCartsUI();
        ScannerEngine.showToast('Cart held! You can now serve the next customer.', true);
      }}

      function resumeHeldCart(idx) {{
        if (idx === '' || idx === null || idx === undefined) return;
        idx = parseInt(idx);
        var held = heldCarts[idx];
        if (!held) return;
        if (cart.length > 0) {{
          if (!confirm('Current cart has items. Replace with held cart?')) return;
        }}
        cart = held.items;
        document.getElementById('cust-name').value = held.customer_name || 'Walk-in Customer';
        document.getElementById('cust-phone').value = held.customer_phone || '';
        heldCarts.splice(idx, 1);
        localStorage.setItem('pos_held_carts', JSON.stringify(heldCarts));
        renderCart();
        updateHeldCartsUI();
        ScannerEngine.showToast('Held cart restored successfully!', true);
      }}

      // ═══════════════════════════════════════════════════════
      // POS Live Typeahead & Instant Search Engine
      // ═══════════════════════════════════════════════════════
      let posSearchDebounce = null;
      let posHighlightedIndex = -1;
      let posSearchResults = [];
      let currentPickerUnits = [];

      const scanInput = document.getElementById('pos-scan-input');
      const searchDropdown = document.getElementById('pos-search-dropdown');

      scanInput.addEventListener('input', function() {{
        clearTimeout(posSearchDebounce);
        const q = scanInput.value.trim();
        if (!q) {{
          searchDropdown.style.display = 'none';
          searchDropdown.innerHTML = '';
          posSearchResults = [];
          posHighlightedIndex = -1;
          return;
        }}

        posSearchDebounce = setTimeout(async function() {{
          try {{
            const resp = await fetch('/api/search/products?q=' + encodeURIComponent(q));
            const data = await resp.json();
            if (!data.items || data.items.length === 0) {{
              searchDropdown.innerHTML = '<div style="padding:14px; text-align:center; color:#94a3b8; font-size:12.5px;">No matching items for "<strong>' + q + '</strong>"</div>';
              searchDropdown.style.display = 'block';
              posSearchResults = [];
              posHighlightedIndex = -1;
              return;
            }}
            posSearchResults = data.items;
            posHighlightedIndex = 0;
            renderPosSearchDropdown();
          }} catch (err) {{
            console.error('POS Search Error:', err);
          }}
        }}, 35);
      }});

      function renderPosSearchDropdown() {{
        let html = '';
        posSearchResults.forEach((item, idx) => {{
          const isHigh = (idx === posHighlightedIndex) ? 'highlighted' : '';
          const inStock = (item.in_stock_count > 0);
          const badge = inStock 
            ? '<span class="pos-search-badge-instock">' + (item.item_type === 'PHONE' ? item.in_stock_count + ' in stock' : item.in_stock_count + ' pcs') + '</span>'
            : '<span class="pos-search-badge-outstock">Out of Stock</span>';
          
          html += '<div class="pos-search-item ' + isHigh + '" data-idx="' + idx + '" onmousedown="selectPosSearchResult(' + idx + ')">';
          html += '  <div style="flex:1; padding-right:12px;">';
          html += '    <div class="pos-search-item-title">' + item.title + '</div>';
          html += '    <div class="pos-search-item-sub"><span>' + item.subtitle + '</span> ' + badge + '</div>';
          html += '  </div>';
          html += '  <div class="pos-search-item-price">Rs. ' + Number(item.price).toLocaleString() + '</div>';
          html += '</div>';
        }});
        searchDropdown.innerHTML = html;
        searchDropdown.style.display = 'block';
      }}

      function selectPosSearchResult(idx) {{
        const item = posSearchResults[idx];
        if (!item) return;

        searchDropdown.style.display = 'none';
        scanInput.value = '';
        scanInput.focus();

        if (item.type === 'unit') {{
          fetch('/api/scan-route?code=' + encodeURIComponent(item.imei) + '&context=POS')
            .then(r => r.json())
            .then(data => {{
              if (data.success && data.unit) {{
                addPhoneUnitToCart(data.unit);
              }} else {{
                ScannerEngine.showToast(data.error || 'Unit unavailable', false);
              }}
            }});
          return;
        }}

        if (item.item_type === 'ACCESSORY') {{
          if (item.in_stock_count <= 0) {{
            ScannerEngine.showToast('⚠️ ' + item.title + ' is OUT OF STOCK!', false);
            ScannerEngine.playErrorBeep();
            return;
          }}
          addAccessoryCart(item.variant_id, item.title, item.price);
          return;
        }}

        if (item.item_type === 'PHONE') {{
          if (item.in_stock_count <= 0) {{
            ScannerEngine.showToast('⚠️ ' + item.title + ' has 0 phones in stock!', false);
            ScannerEngine.playErrorBeep();
            return;
          }}
          fetch('/api/pos/variant-units/' + item.variant_id)
            .then(r => r.json())
            .then(res => {{
              if (res.units && res.units.length === 1) {{
                addPhoneUnitToCart(res.units[0]);
              }} else if (res.units && res.units.length > 1) {{
                openImeiPickerModal(item, res.units);
              }} else {{
                ScannerEngine.showToast('No active in-stock units found for this model.', false);
              }}
            }});
        }}
      }}

      function openImeiPickerModal(item, units) {{
        currentPickerUnits = units;
        document.getElementById('imei-picker-title').innerText = item.title;
        document.getElementById('imei-picker-sub').innerText = units.length + ' devices physically in stock. Choose IMEI to bill:';
        document.getElementById('imei-picker-filter').value = '';
        renderImeiPickerList(units);
        document.getElementById('pos-imei-picker-modal').style.display = 'flex';
        setTimeout(() => document.getElementById('imei-picker-filter').focus(), 60);
      }}

      function renderImeiPickerList(units) {{
        const box = document.getElementById('imei-picker-list');
        if (!units.length) {{
          box.innerHTML = '<div style="padding:20px; text-align:center; color:#888;">No matching units found.</div>';
          return;
        }}
        let html = '';
        units.forEach(u => {{
          html += `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; border-bottom:1px solid rgba(255,255,255,0.06); transition:background 0.1s;">
            <div>
              <div style="font-weight:bold; font-size:13.5px; color:#fff;"><code>${{u.imei1}}</code></div>
              <div style="font-size:11.5px; color:#94a3b8; margin-top:2px;">${{u.ram}}/${{u.storage}} ${{u.color}} &bull; ${{u.condition}} &bull; <strong style="color:#10b981;">${{u.pta_status}}</strong></div>
            </div>
            <button type="button" class="btn btn-sm btn-success" onclick="selectPickerUnit(${{u.id}})" style="font-weight:bold; padding:6px 14px;">+ Add to Cart</button>
          </div>
          `;
        }});
        box.innerHTML = html;
      }}

      function filterImeiPickerList(q) {{
        q = q.toLowerCase().trim();
        const filtered = currentPickerUnits.filter(u => {{
          return (u.imei1 || '').toLowerCase().includes(q) || 
                 (u.imei2 || '').toLowerCase().includes(q) ||
                 (u.color || '').toLowerCase().includes(q) ||
                 (u.condition || '').toLowerCase().includes(q);
        }});
        renderImeiPickerList(filtered);
      }}

      function selectPickerUnit(uid) {{
        const u = currentPickerUnits.find(unit => unit.id === uid);
        if (u) {{
          addPhoneUnitToCart(u);
          closeImeiPickerModal();
        }}
      }}

      function closeImeiPickerModal() {{
        document.getElementById('pos-imei-picker-modal').style.display = 'none';
        scanInput.focus();
      }}

      document.addEventListener('click', function(e) {{
        if (!scanInput.contains(e.target) && !searchDropdown.contains(e.target)) {{
          searchDropdown.style.display = 'none';
        }}
      }});

      scanInput.addEventListener('keydown', function(e) {{
        if (searchDropdown.style.display === 'block' && posSearchResults.length > 0) {{
          if (e.key === 'ArrowDown') {{
            e.preventDefault();
            posHighlightedIndex = (posHighlightedIndex + 1) % posSearchResults.length;
            renderPosSearchDropdown();
            return;
          }} else if (e.key === 'ArrowUp') {{
            e.preventDefault();
            posHighlightedIndex = (posHighlightedIndex - 1 + posSearchResults.length) % posSearchResults.length;
            renderPosSearchDropdown();
            return;
          }} else if (e.key === 'Enter') {{
            if (posHighlightedIndex >= 0 && posHighlightedIndex < posSearchResults.length) {{
              e.preventDefault();
              selectPosSearchResult(posHighlightedIndex);
              return;
            }}
          }} else if (e.key === 'Escape') {{
            searchDropdown.style.display = 'none';
            return;
          }}
        }}

        if (e.key === 'Enter') {{
          e.preventDefault();
          handleScanSubmit();
        }}
      }});

      function handleScanSubmit() {{
        searchDropdown.style.display = 'none';
        var inp = document.getElementById('pos-scan-input');
        var val = inp.value.trim();
        if (!val) return;
        
        fetch('/api/scan-route?code=' + encodeURIComponent(val) + '&context=POS')
          .then(r => r.json())
          .then(data => {{
            if (data.success) {{
              if (data.type === 'UNIT_FOUND' || data.type === 'PHONE_UNIT') {{
                addPhoneUnitToCart(data.unit);
                inp.value = '';
                inp.focus();
              }} else if (data.type === 'ACCESSORY_FOUND' || data.type === 'ACCESSORY') {{
                addAccessoryCart(data.variant.id || data.variant.variant_id, (data.variant.brand ? data.variant.brand + ' ' : '') + (data.variant.model_name || data.variant.product_name), data.variant.retail_price);
                inp.value = '';
                inp.focus();
              }} else if (data.type === 'SEARCH_MATCHES') {{
                if (data.items && data.items.length) {{
                  posSearchResults = data.items;
                  posHighlightedIndex = 0;
                  renderPosSearchDropdown();
                }}
              }} else if (data.type === 'INVOICE_FOUND' || data.type === 'SALE_INVOICE') {{
                window.open('/print/sale/' + data.sale.id, '_blank');
              }}
            }} else {{
              ScannerEngine.playErrorBeep();
              ScannerEngine.flashScreen('rgba(239, 68, 68, 0.5)');
              alert('Scan Alert: ' + (data.error || 'Item not found'));
              inp.select();
            }}
          }});
      }}

      async function submitCheckout() {{
        if (cart.length === 0) {{ alert('Cart is empty!'); return; }}
        var custName = document.getElementById('cust-name').value.trim();
        var custPhone = document.getElementById('cust-phone').value.trim();
        var discount = parseFloat(document.getElementById('input-discount').value) || 0;
        var paid = parseFloat(document.getElementById('input-paid').value) || 0;
        var payMethod = document.getElementById('pay-method').value;
        var saleDate = (document.getElementById('pos-sale-date') ? document.getElementById('pos-sale-date').value.trim() : '');
        var backdateReason = '';

        var todayStr = new Date().toISOString().slice(0, 10);
        if (saleDate && saleDate < todayStr) {{
          try {{
            var chk = await fetch('/api/check-closed-day?date=' + encodeURIComponent(saleDate)).then(r => r.json());
            if (chk && chk.is_closed) {{
              var rPrompt = prompt('⚠️ Day ' + saleDate + ' is already CLOSED.\\nEnter mandatory reason for back-dating (min 10 characters):');
              if (!rPrompt || rPrompt.trim().length < 10) {{
                alert('A valid reason (minimum 10 characters) is required to back-date into a closed day.');
                return;
              }}
              backdateReason = rPrompt.trim();
            }} else {{
              var rPrompt2 = prompt('This bill is being back-dated to ' + saleDate + '.\\nEnter optional reason / note for audit log:');
              if (rPrompt2) {{ backdateReason = rPrompt2.trim(); }}
            }}
          }} catch(e) {{}}
        }}

        var subtotal = 0;
        cart.forEach(function(item) {{
          subtotal += Math.max(0, (item.unit_price * item.qty) - (item.discount || 0));
        }});
        var grand = Math.max(0, subtotal - discount);
        if (payMethod === 'UDHAAR' || (paid < grand && grand > 0)) {{
          if (!custName || custName.toLowerCase() === 'walk-in customer' || custName.toLowerCase() === 'walk-in') {{
            alert('⚠️ Customer account is required for Udhaar / Credit sale.\\nPlease select an existing customer from the search or enter Customer Name & Phone on the right panel.');
            const nameEl = document.getElementById('cust-name');
            nameEl.focus();
            if (nameEl.value.trim().toLowerCase() === 'walk-in customer') {{
              nameEl.value = '';
            }}
            return;
          }}
        }}

        var payload = {{
          items: cart,
          customer_name: custName,
          customer_phone: custPhone,
          discount_amount: discount,
          paid_amount: paid,
          payment_method: payMethod,
          sale_date: saleDate,
          backdate_reason: backdateReason
        }};

        fetch('/api/pos/checkout', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }})
        .then(r => r.json())
        .then(res => {{
          if (res.success) {{
            // Show non-blocking alert toasts if stock transitions occurred
            if (res.alert_notifications && res.alert_notifications.length > 0) {{
              res.alert_notifications.forEach(function(n) {{
                var isOut = (n.transition === 'OK_TO_OUT' || n.transition === 'LOW_TO_OUT');
                var icon = isOut ? '🚨 OUT OF STOCK' : '⚠️ LOW STOCK';
                ScannerEngine.showToast(icon + ': ' + n.brand + ' ' + n.model_name + ' (' + n.new_stock + ' left)', !isOut);
              }});
            }}
            // Open print window
            window.open('/print/sale/' + res.sale_id, '_blank');
            cart = [];
            renderCart();
            document.getElementById('cust-name').value = 'Walk-in Customer';
            document.getElementById('cust-phone').value = '';
            const pill = document.getElementById('cust-udhaar-pill');
            if (pill) pill.style.display = 'none';
            if (window.posSetPaymentMethod) window.posSetPaymentMethod('CASH');
            document.getElementById('input-paid').dataset.manual = '0';
            document.getElementById('pos-scan-input').value = '';
            document.getElementById('pos-scan-input').focus();
          }} else {{
            alert('Checkout Error: ' + res.error);
          }}
        }});
      }}

      // ─── POS TOP SELLERS LOGIC ─────────────────────────────────
      let posTopSellersLoaded = false;
      let posTopSellerActiveCat = '';

      function togglePosTopSellers() {{
        const panel = document.getElementById('pos-top-sellers-panel');
        if (!panel) return;
        if (panel.style.display === 'none') {{
          panel.style.display = 'block';
          if (!posTopSellersLoaded) {{
            loadPosTopSellers('');
          }}
        }} else {{
          panel.style.display = 'none';
        }}
      }}

      function loadPosTopSellers(cat) {{
        posTopSellerActiveCat = cat;
        const grid = document.getElementById('pos-top-sellers-grid');
        grid.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px;">Loading fast sellers...</div>';
        fetch('/api/pos/quick-top-sellers?category=' + encodeURIComponent(cat))
          .then(r => r.json())
          .then(data => {{
            posTopSellersLoaded = true;
            if (!data.items || data.items.length === 0) {{
              grid.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px;">No sales activity recorded.</div>';
              return;
            }}
            // Populate category chips if empty
            const chipsBox = document.getElementById('pos-top-seller-cat-chips');
            if (chipsBox && chipsBox.children.length === 0) {{
              const cats = Array.from(new Set(data.items.map(it => it.category).filter(Boolean)));
              let cHtml = `<button type="button" class="btn btn-xs ${{!cat ? 'btn-warning' : 'btn-secondary'}}" onclick="loadPosTopSellers('')" style="font-size:10px; padding:2px 6px;">All</button>`;
              cats.forEach(c => {{
                cHtml += ` <button type="button" class="btn btn-xs ${{cat === c ? 'btn-warning' : 'btn-secondary'}}" onclick="loadPosTopSellers('${{c}}')" style="font-size:10px; padding:2px 6px;">${{c}}</button>`;
              }});
              chipsBox.innerHTML = cHtml;
            }}

            let html = '';
            data.items.forEach(it => {{
              const stockBadge = it.current_stock > 0
                ? `<span style="background:rgba(16,185,129,0.2); color:#34d399; font-size:10px; padding:1px 4px; border-radius:3px;">${{it.current_stock}} in stock</span>`
                : `<span style="background:rgba(239,68,68,0.2); color:#f87171; font-size:10px; padding:1px 4px; border-radius:3px; font-weight:bold;">OUT</span>`;

              const itJson = JSON.stringify(it).replace(/"/g, '&quot;');
              html += `
              <div style="background:#1e293b; border:1px solid #334155; border-radius:6px; padding:7px 9px; cursor:pointer;"
                   onmouseover="this.style.borderColor='#38bdf8'" onmouseout="this.style.borderColor='#334155'"
                   onclick="clickPosTopSellerItem(${{itJson}})">
                <div style="font-size:12px; font-weight:bold; color:#f8fafc; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${{it.brand}} ${{it.model_name}}</div>
                <div style="font-size:10px; color:#94a3b8; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${{it.specs || it.category}}</div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:3px;">
                  <span style="font-size:11.5px; font-weight:800; color:#38bdf8;">Rs. ${{Number(it.retail_price).toLocaleString()}}</span>
                  <span style="font-size:10px; color:#fbbf24;">⚡ ${{it.net_units_sold}} sold</span>
                </div>
                <div style="margin-top:2px;">${{stockBadge}}</div>
              </div>
              `;
            }});
            grid.innerHTML = html;
          }});
      }}

      function clickPosTopSellerItem(it) {{
        if (it.item_type === 'PHONE') {{
          if (it.current_stock <= 0) {{
            ScannerEngine.showToast('⚠️ ' + it.model_name + ' has 0 phones in stock!', false);
            ScannerEngine.playErrorBeep();
            return;
          }}
          fetch('/api/pos/variant-units/' + it.variant_id)
            .then(r => r.json())
            .then(res => {{
              if (res.units && res.units.length === 1) {{
                addPhoneUnitToCart(res.units[0]);
              }} else if (res.units && res.units.length > 1) {{
                openImeiPickerModal({{title: it.brand + ' ' + it.model_name}}, res.units);
              }} else {{
                ScannerEngine.showToast('No active in-stock units found for this model.', false);
              }}
            }});
        }} else {{
          if (it.current_stock <= 0) {{
            ScannerEngine.showToast('⚠️ ' + it.model_name + ' is OUT OF STOCK!', false);
            ScannerEngine.playErrorBeep();
            return;
          }}
          addAccessoryCart(it.variant_id, it.brand + ' ' + it.model_name + (it.specs ? ' (' + it.specs + ')' : ''), it.retail_price);
        }}
      }}
    </script>
    """
    return layout("POS Terminal", content, "pos", user)

# ═══════════════════════════════════════════════════════════
# INVENTORY MANAGER & MATRIX CREATOR
# ═══════════════════════════════════════════════════════════

@app.route("/inventory")
def inventory_screen():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")

    products = db.query_all("SELECT * FROM products WHERE is_archived = 0 ORDER BY brand ASC, name ASC")
    
    # Stock valuation summary
    val = inventory.get_stock_valuation()
    aging = inventory.get_aging_stock()

    # Dynamic Brands and Categories
    brand_items = lookups.get_lookup_list("brand")
    brand_opts = "".join(f'<option value="{b["label"]}">{b["label"]}</option>' for b in brand_items)

    cat_items = lookups.get_lookup_list("category")
    cat_opts = "".join(f'<option value="{c["label"]}">{c["label"]}</option>' for c in cat_items)

    phone_count = sum(1 for p in products if p.get("item_type") in ("PHONE", "SERIAL"))
    acc_count = sum(1 for p in products if p.get("item_type") == "ACCESSORY")
    part_count = sum(1 for p in products if p.get("item_type") == "SPARE_PART")

    prod_rows = ""
    for p in products:
        itype = p.get("item_type", "PHONE")
        variants = inventory.get_variants_for_product(p["id"])
        total_units = sum(v["units_in_stock"] for v in variants)
        v0 = variants[0] if variants else None
        v0_id = v0["id"] if v0 else 0
        v0_retail = v0["retail_price"] if v0 else 0
        v0_cost = v0["wholesale_price"] if v0 else 0
        v0_barcode = (v0.get("barcode") or "") if v0 else ""
        v0_sku = (v0.get("sku") or "") if v0 else ""

        # Type badge and unit label
        if itype in ("PHONE", "SERIAL"):
            type_badge = '<span class="badge" style="background:#0284c7; color:#fff; font-size:10px; padding:2px 6px;">📱 Phone</span>'
            unit_label = f"{total_units} Phones"
        elif itype == "ACCESSORY":
            type_badge = '<span class="badge" style="background:#8b5cf6; color:#fff; font-size:10px; padding:2px 6px;">🎧 Accessory</span>'
            unit_label = f"{total_units} Pcs"
        else:
            type_badge = '<span class="badge" style="background:#f59e0b; color:#fff; font-size:10px; padding:2px 6px;">🔧 Spare Part</span>'
            unit_label = f"{total_units} Pcs"

        stock_badge = "badge-success" if total_units > 0 else "badge-danger"

        # Details display
        safe_title = html.escape(f"{p['brand']} {p['name']}")
        if itype in ("PHONE", "SERIAL"):
            var_pills = ""
            for v in variants:
                var_pills += f'<span class="badge badge-info" style="margin:2px;">{v["ram"]}/{v["storage"]} {v["color"]} ({v["units_in_stock"]})</span> '
            details_html = f'{len(variants)} variants<br>{var_pills}'
            if is_admin:
                action_html = f'''
                    <button type="button" class="btn btn-sm btn-success" data-pid="{p['id']}" data-title="{safe_title}" onclick="openPhoneStockFromBtn(this)">➕ Add Stock</button>
                    <a href="/inventory/product/{p['id']}/units" class="btn btn-sm btn-secondary">📱 Units</a>
                    <button type="button" class="btn btn-sm btn-primary" onclick="openEditItemModal({p['id']})">✏️ Edit</button>
                    <a href="/inventory/matrix-create?product_id={p['id']}" class="btn btn-sm btn-secondary">⚡ Matrix</a>
                    <button type="button" class="btn btn-sm btn-danger" onclick="confirmDeleteItem({p['id']}, '{safe_title}')" title="Delete or Archive">🗑️</button>
                '''
            else:
                action_html = f'''
                    <a href="/inventory/product/{p['id']}/units" class="btn btn-sm btn-secondary">📱 Units</a>
                    <a href="/inventory/product/{p['id']}" class="btn btn-sm btn-secondary">Details</a>
                '''
        else:
            # Accessory or Spare Part
            barcode_str = f"<code>{v0_barcode or v0_sku}</code>" if (v0_barcode or v0_sku) else '<span style="color:#64748b; font-size:11px;">No Barcode</span>'
            details_html = f'''
                <div style="font-size:12px;">
                  Retail: <strong style="color:#38bdf8;">Rs. {v0_retail:,.0f}</strong>{f" &bull; Cost: Rs. {v0_cost:,.0f}" if is_admin else ""}<br>
                  Barcode: {barcode_str}
                </div>
            '''
            if is_admin:
                action_html = f'''
                    <button type="button" class="btn btn-sm btn-success" data-vid="{v0_id}" data-pid="{p['id']}" data-title="{safe_title}" data-cost="{v0_cost}" onclick="openQuickStockFromBtn(this)">➕ Add Stock</button>
                    <button type="button" class="btn btn-sm btn-primary" onclick="openEditItemModal({p['id']})">✏️ Edit</button>
                    {f'<a href="/print/barcode-label/{v0_id}" target="_blank" class="btn btn-sm btn-secondary">🖨️ Label</a>' if v0_id else ''}
                    <button type="button" class="btn btn-sm btn-danger" onclick="confirmDeleteItem({p['id']}, '{safe_title}')" title="Delete or Archive">🗑️</button>
                '''
            else:
                action_html = f'''
                    {f'<a href="/print/barcode-label/{v0_id}" target="_blank" class="btn btn-sm btn-secondary">🖨️ Label</a>' if v0_id else ''}
                '''

        b_low = (p['brand'] or '').lower()
        n_low = (p['name'] or '').lower()
        c_low = (p['category'] or '').lower()
        search_corpus = f"{b_low} {n_low} {c_low} {itype.lower()} {v0_barcode.lower()} {v0_sku.lower()}"

        prod_rows += f"""
        <tr id="prod-row-{p['id']}" class="inv-row" data-type="{itype}" data-search="{search_corpus}">
          <td><strong>{p['brand']}</strong></td>
          <td>
            <strong>{p['name']}</strong><br>
            <small style="color:#94a3b8;">{p['category']} &bull; {type_badge}</small>
          </td>
          <td>{details_html}</td>
          <td><span class="badge {stock_badge}" style="font-size:12px; font-weight:bold;">{unit_label}</span></td>
          <td style="text-align:right; white-space:nowrap;">
            {action_html}
          </td>
        </tr>
        """

    content = f"""
    <div class="grid-3" style="margin-bottom: 16px;">
      <div class="card">
        <div style="font-size: 11px; color: var(--text-muted);">PHONE STOCK VALUATION</div>
        <div style="font-size: 18px; font-weight: 800; color: #34d399; margin-top: 4px;">{val['phones']['total_count']} Phones (Rs. {val['phones']['total_retail']:,.0f})</div>
        <div style="font-size: 11px; color: #94a3b8;">{f"Wholesale Cost: Rs. {val['phones']['total_cost']:,.0f}" if is_admin else "Retail Valuation"}</div>
      </div>
      <div class="card">
        <div style="font-size: 11px; color: var(--text-muted);">ACCESSORIES & SPARE PARTS</div>
        <div style="font-size: 18px; font-weight: 800; color: #60a5fa; margin-top: 4px;">{val['accessories']['total_count'] + val['parts']['total_count']} Items (Rs. {val['accessories']['total_retail'] + val['parts']['total_retail']:,.0f})</div>
        <div style="font-size: 11px; color: #94a3b8;">{f"Stock Cost: Rs. {val['accessories']['total_cost'] + val['parts']['total_cost']:,.0f}" if is_admin else "Retail Valuation"}</div>
      </div>
      <div class="card">
        <div style="font-size: 11px; color: var(--text-muted);">AGING INVENTORY ALERT</div>
        <div style="font-size: 18px; font-weight: 800; color: #f87171; margin-top: 4px;">{aging['total_aging']} Phones Unsold &gt; 30 Days</div>
        <div style="font-size: 11px; color: #94a3b8;">Capital tied up in aging stock</div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <div class="card-title">📦 Product Catalog & Stock Inventory ({len(products)})</div>
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" id="inv-table-filter" placeholder="🔍 Live filter items..." class="form-control" style="width:200px; padding:6px 10px; font-size:12px;" oninput="filterInventoryTable(this.value)">
          {f'<a href="/inventory/matrix-create" class="btn btn-primary btn-sm">⚡ Variant Matrix Creator</a>' if is_admin else ''}
          {f'<button class="btn btn-success btn-sm" onclick="openUnifiedItemModal()">+ Add New Product / Accessory</button>' if is_admin else ''}
        </div>
      </div>

      <!-- Filter Tabs -->
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; padding:12px 16px 0 16px;">
        <div style="display:flex; gap:6px;">
          <button type="button" class="btn btn-xs inv-tab-btn" id="tab-filter-ALL" onclick="filterInvTab('ALL')" style="font-weight:bold; background:var(--primary); color:#fff;">📦 All Items ({len(products)})</button>
          <button type="button" class="btn btn-xs btn-secondary inv-tab-btn" id="tab-filter-PHONE" onclick="filterInvTab('PHONE')" style="font-weight:bold;">📱 Phones ({phone_count})</button>
          <button type="button" class="btn btn-xs btn-secondary inv-tab-btn" id="tab-filter-ACCESSORY" onclick="filterInvTab('ACCESSORY')" style="font-weight:bold;">🎧 Accessories ({acc_count})</button>
          <button type="button" class="btn btn-xs btn-secondary inv-tab-btn" id="tab-filter-SPARE_PART" onclick="filterInvTab('SPARE_PART')" style="font-weight:bold;">🔧 Spare Parts ({part_count})</button>
        </div>
        <div style="font-size:11px; color:#94a3b8;">
          Showing <span id="visible-item-count">{len(products)}</span> items
        </div>
      </div>

      <div class="table-responsive" style="margin-top:10px;">
        <table class="data-table" id="inventory-models-table">
          <thead>
            <tr>
              <th style="width:120px;">Brand</th>
              <th>Item / Model Name</th>
              <th>Specifications / Pricing</th>
              <th style="width:140px;">Stock In Hand</th>
              <th style="text-align: right; width:220px;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {prod_rows or '<tr><td colspan="5" style="text-align:center; color:#888;">No items found</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    {f'''
    <!-- Unified Item Creation Modal (Admin Only) -->
    <div id="unified-item-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); z-index:2000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:540px; max-width:94vw; max-height:92vh; overflow-y:auto; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
          <div>
            <h3 style="font-size:17px; font-weight:800; color:var(--text); margin:0;">📦 Add New Inventory Item</h3>
            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Fast entry &bull; Ctrl+Enter to Save & Add Another</div>
          </div>
          <button type="button" onclick="closeUnifiedItemModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer; padding:4px 8px;">✕</button>
        </div>

        <!-- Tabs -->
        <div style="display:flex; gap:6px; margin-bottom:16px; background:rgba(0,0,0,0.25); padding:4px; border-radius:8px;">
          <button type="button" class="btn btn-xs" id="tab-btn-acc" onclick="switchItemTab('ACCESSORY')" style="flex:1; font-weight:bold; background:var(--primary); color:#fff;">🎧 Accessory</button>
          <button type="button" class="btn btn-xs btn-secondary" id="tab-btn-phone" onclick="switchItemTab('PHONE')" style="flex:1; font-weight:bold;">📱 Phone Model</button>
          <button type="button" class="btn btn-xs btn-secondary" id="tab-btn-part" onclick="switchItemTab('SPARE_PART')" style="flex:1; font-weight:bold;">🔧 Spare Part</button>
        </div>

        <form id="unified-item-form" onsubmit="submitUnifiedItem(event)">
          <input type="hidden" id="item-type-input" name="item_type" value="ACCESSORY">

          <div id="unified-form-alert" style="display:none; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-size:12.5px;"></div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <div class="form-group">
              <label class="form-label">Brand *</label>
              <select id="u-brand" name="brand" class="form-control smart-select" data-list-key="brand" data-entity-name="Brand" data-quickadd="lookup" required>
                {brand_opts}
              </select>
              <div class="field-error" id="err-brand" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
            </div>

            <div class="form-group">
              <label class="form-label">Category</label>
              <select id="u-category" name="category" class="form-control smart-select" data-list-key="category" data-entity-name="Category" data-quickadd="lookup">
                {cat_opts}
              </select>
              <div class="field-error" id="err-category" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label" id="lbl-item-name">Item / Accessory Name *</label>
            <input type="text" id="u-name" name="name" class="form-control" placeholder="e.g. 20W Fast Charger, Type-C Cable, Matte Cover" required autofocus>
            <div class="field-error" id="err-name" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
          </div>

          <!-- Non-phone fields (Price & Stock) -->
          <div id="price-stock-fields">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
              <div class="form-group">
                <label class="form-label">Retail Selling Price (Rs.) *</label>
                <input type="text" id="u-retail-price" name="retail_price" class="form-control" placeholder="e.g. 1,500 or 1500" value="0">
                <div class="field-error" id="err-retail-price" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
              </div>
              <div class="form-group">
                <label class="form-label">Cost / Wholesale Price (Rs.)</label>
                <input type="text" id="u-wholesale-price" name="wholesale_price" class="form-control" placeholder="e.g. 1,000" value="0">
                <div class="field-error" id="err-wholesale-price" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
              <div class="form-group">
                <label class="form-label" style="font-weight:700; color:#38bdf8;">Opening Stock Quantity (Pieces) *</label>
                <div style="display:flex; gap:4px; margin-bottom:5px;">
                  <button type="button" class="btn btn-xs btn-secondary" onclick="setInitialQty(5)">+5</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="setInitialQty(10)">+10</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="setInitialQty(20)">+20</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="setInitialQty(50)">+50</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="setInitialQty(100)">+100</button>
                </div>
                <input type="number" id="u-stock-qty" name="stock_quantity" class="form-control" placeholder="e.g. 10" value="10" min="0" style="font-weight:bold; font-size:14px;">
                <div class="field-error" id="err-stock-quantity" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
              </div>
              <div class="form-group">
                <label class="form-label">Barcode / SKU <small style="color:#94a3b8;">(Auto if blank)</small></label>
                <div style="height:24px;"></div>
                <input type="text" id="u-barcode" name="barcode" class="form-control" placeholder="Scan or leave blank for auto">
                <div class="field-error" id="err-barcode" style="color:#ef4444; font-size:11px; margin-top:3px; display:none;"></div>
              </div>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:10px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px; margin-top:4px;">
              <div class="form-group" style="margin-bottom:0;">
                <label class="form-label">Alert Threshold <small style="color:#94a3b8;">(Low Stock Alert)</small></label>
                <input type="number" id="u-low-stock" name="low_stock_level" class="form-control" placeholder="Category default (5)" min="0">
              </div>
              <div class="form-group" style="margin-bottom:0;">
                <label class="form-label">Default Reorder Qty</label>
                <input type="number" id="u-reorder-qty" name="reorder_qty" class="form-control" placeholder="Category default (20)" min="0">
              </div>
            </div>
          </div>

          <!-- Phone specific section: Variants & Opening Stock Builder -->
          <div id="phone-variants-section" style="display:none; margin-top:14px; border-top:1px solid var(--border); padding-top:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
              <div>
                <strong style="font-size:13px; color:#38bdf8;">📱 Phone Variants & Opening Stock</strong>
                <div style="font-size:11px; color:#94a3b8;">Har variant (Color / RAM / Storage) ka alag stock aur alag IMEIs darj karein.</div>
              </div>
              <button type="button" class="btn btn-xs btn-primary" onclick="addPhoneVariantCard()">+ Add Another Variant</button>
            </div>

            <div id="phone-variants-container">
              <!-- Dynamic Variant Cards will be rendered here -->
            </div>

            <div style="margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
              <button type="button" class="btn btn-sm btn-secondary" onclick="addPhoneVariantCard()">+ Add Variant / Color</button>
              <a href="/inventory/matrix-create" target="_blank" style="font-size:11px; color:#60a5fa; text-decoration:none;">⚡ Or open Variant Matrix Creator &rarr;</a>
            </div>
          </div>

          <!-- Spare Part specific field: Compatible Models -->
          <div id="spare-part-fields" style="display:none; margin-top:10px;">
            <div class="form-group">
              <label class="form-label">Compatible Phone Models</label>
              <input type="text" id="u-compatible" name="compatible_models" class="form-control" placeholder="e.g. iPhone 13, iPhone 14, Galaxy A15">
            </div>
          </div>

          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px; border-top:1px solid var(--border); padding-top:14px;">
            <button type="button" class="btn btn-secondary" onclick="closeUnifiedItemModal()">Cancel (Esc)</button>
            <div style="display:flex; gap:8px;">
              <button type="button" id="btn-save-another" class="btn btn-primary" onclick="submitUnifiedItem(event, true)">Save & Add Another <small style="opacity:0.8;">(Ctrl+Enter)</small></button>
              <button type="submit" id="btn-save-item" class="btn btn-success">Save Item</button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <!-- Quick Stock Addition Modal for Accessories & Parts -->
    <div id="quick-stock-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); z-index:2100; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:440px; max-width:92vw; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
          <div>
            <h3 style="font-size:16px; font-weight:800; margin:0; color:var(--text);" id="qs-modal-title">➕ Add Stock</h3>
            <div style="font-size:11px; color:#94a3b8;" id="qs-item-subtitle">Direct piece quantity intake</div>
          </div>
          <button type="button" onclick="closeQuickStockModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer;">✕</button>
        </div>
        <form id="quick-stock-form" onsubmit="submitQuickStock(event)">
          <input type="hidden" id="qs-variant-id" name="variant_id" value="">
          <div id="qs-alert" style="display:none; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:12px;"></div>
          
          <div class="form-group">
            <label class="form-label" style="font-weight:700; color:#38bdf8;">Quantity to Add *</label>
            <div style="display:flex; gap:6px; margin-bottom:8px;">
              <button type="button" class="btn btn-xs btn-secondary" onclick="addQsQty(5)">+5</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="addQsQty(10)">+10</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="addQsQty(20)">+20</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="addQsQty(50)">+50</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="addQsQty(100)">+100</button>
            </div>
            <input type="number" id="qs-qty" name="qty" class="form-control" value="10" min="1" required autofocus style="font-size:16px; font-weight:bold;">
          </div>

          <div class="form-group">
            <label class="form-label">Cost / Wholesale Price (Rs.) <small style="color:#94a3b8;">(Optional)</small></label>
            <input type="text" id="qs-cost" name="cost_price" class="form-control" placeholder="Leave blank to keep existing cost">
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:20px; border-top:1px solid var(--border); padding-top:12px;">
            <button type="button" class="btn btn-secondary" onclick="closeQuickStockModal()">Cancel</button>
            <button type="submit" id="btn-submit-qs" class="btn btn-success">➕ Add to Stock</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Phone Stock / IMEI Intake Modal (Admin Only) -->
    <div id="phone-stock-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); z-index:2100; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:520px; max-width:94vw; max-height:92vh; overflow-y:auto; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
          <div>
            <h3 style="font-size:16px; font-weight:800; margin:0; color:var(--text);" id="ps-modal-title">➕ Receive Phone Stock / IMEIs</h3>
            <div style="font-size:11px; color:#94a3b8;" id="ps-modal-subtitle">Fast inventory intake with serial/IMEI validation</div>
          </div>
          <button type="button" onclick="closePhoneStockModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer;">✕</button>
        </div>
        <form id="phone-stock-form" onsubmit="submitPhoneStock(event)">
          <input type="hidden" id="ps-product-id" name="product_id" value="">
          <div id="ps-alert" style="display:none; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:12px;"></div>

          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">Variant / Specification *</label>
            <select id="ps-variant-select" name="variant_id" class="form-control" required onchange="onPhoneStockVariantChanged()"></select>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Unit Cost Price (Rs.)</label>
              <input type="text" id="ps-cost" name="cost_price" class="form-control form-control-sm" placeholder="e.g. 45000">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">PTA Status</label>
              <select id="ps-pta" name="pta_status" class="form-control form-control-sm">
                <option value="PTA_APPROVED">PTA Approved</option>
                <option value="NON_PTA">Non-PTA</option>
                <option value="JV">JV / Gevey</option>
                <option value="OFFICIAL">Official Warranty</option>
                <option value="FACTORY_UNLOCKED">Factory Unlocked</option>
              </select>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Condition</label>
              <select id="ps-condition" name="condition" class="form-control form-control-sm">
                <option value="NEW_BOX_PACK">New Box Pack</option>
                <option value="OPEN_BOX">Open Box (10/10)</option>
                <option value="USED">Used / Kit</option>
                <option value="REFURBISHED">Refurbished</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Quantity (If no IMEIs scanned)</label>
              <input type="number" id="ps-qty" name="qty" class="form-control form-control-sm" value="1" min="0">
            </div>
          </div>

          <div class="form-group" style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label class="form-label" style="font-size:12px; margin-bottom:0; font-weight:bold; color:#38bdf8;">Scan / Enter IMEIs</label>
              <span id="ps-imei-badge" class="badge badge-info" style="font-size:11px;">0 IMEIs</span>
            </div>
            <textarea id="ps-imeis" name="imeis" class="form-control" rows="3" style="font-family:monospace; font-size:12px;" placeholder="Scan barcode with scanner or enter 15-digit IMEIs (comma or new line separated)..." oninput="updatePhoneStockImeiCount()"></textarea>
            <small style="color:#94a3b8; font-size:11px;">Har device ka alag IMEI dakhil karein, ya box barcode scan karein.</small>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px; border-top:1px solid var(--border); padding-top:12px;">
            <button type="button" class="btn btn-secondary" onclick="closePhoneStockModal()">Cancel</button>
            <button type="submit" id="btn-submit-ps" class="btn btn-success font-weight-bold">➕ Add to Stock</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Edit Item Modal -->
    <div id="edit-item-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); z-index:2100; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:520px; max-width:94vw; max-height:92vh; overflow-y:auto; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
          <div>
            <h3 style="font-size:16px; font-weight:800; margin:0; color:var(--text);" id="edit-modal-title">✏️ Edit Inventory Item</h3>
            <div style="font-size:11px; color:#94a3b8;">Update pricing, barcode, stock quantity</div>
          </div>
          <button type="button" onclick="closeEditItemModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer;">✕</button>
        </div>
        <form id="edit-item-form" onsubmit="submitEditItem(event)">
          <input type="hidden" id="edit-product-id" name="product_id" value="">
          <input type="hidden" id="edit-variant-id" name="variant_id" value="">
          <div id="edit-form-alert" style="display:none; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:12px;"></div>

          <!-- Phone Items Notice & Direct Action Buttons -->
          <div id="edit-phone-notice" style="display:none; margin-bottom:14px; padding:10px 14px; border-radius:6px; background:rgba(59,130,246,0.12); border:1px solid #3b82f6; font-size:12px;">
            <div style="font-weight:bold; color:#60a5fa; margin-bottom:4px;">📱 Mobile Phone Model</div>
            <div style="color:#cbd5e1; margin-bottom:8px; line-height:1.4;">
              Brand aur Model Name yahan se update ho jayenge. Individual <strong>IMEI numbers, PTA Status, Condition, Cost</strong> ya <strong>Variants</strong> edit karne ke liye neeche buttons use karein:
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <button type="button" class="btn btn-xs btn-success" onclick="openPhoneStockFromEdit()">➕ Receive Stock / Scan IMEIs</button>
              <a id="edit-phone-units-link" href="#" class="btn btn-xs btn-primary">📱 Manage & Edit Phone IMEIs</a>
              <a id="edit-phone-matrix-link" href="#" class="btn btn-xs btn-secondary">⚡ Variants & Specs Matrix</a>
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <div class="form-group">
              <label class="form-label">Brand *</label>
              <input type="text" id="edit-brand" name="brand" class="form-control" required>
            </div>
            <div class="form-group">
              <label class="form-label">Category</label>
              <input type="text" id="edit-category" name="category" class="form-control">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Item / Model Name *</label>
            <input type="text" id="edit-name" name="name" class="form-control" required>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <div class="form-group">
              <label class="form-label">Retail Price (Rs.) *</label>
              <input type="text" id="edit-retail-price" name="retail_price" class="form-control" required>
            </div>
            <div class="form-group">
              <label class="form-label">Cost / Wholesale Price (Rs.)</label>
              <input type="text" id="edit-wholesale-price" name="wholesale_price" class="form-control">
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
            <div class="form-group">
              <label class="form-label" id="edit-stock-qty-label">Total Stock Quantity</label>
              <input type="number" id="edit-stock-qty" name="stock_quantity" class="form-control" min="0">
              <div id="edit-phone-stock-badge" style="display:none; font-size:11px; color:#38bdf8; margin-top:3px; font-weight:600;">📱 Derived from physical Units (IMEIs)</div>
            </div>
            <div class="form-group">
              <label class="form-label">Barcode / SKU</label>
              <input type="text" id="edit-barcode" name="barcode" class="form-control">
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:10px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label">Low Stock Alert Threshold</label>
              <input type="number" id="edit-low-stock" name="low_stock_level" class="form-control" min="0">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label">Default Reorder Qty</label>
              <input type="number" id="edit-reorder-qty" name="reorder_qty" class="form-control" min="0">
            </div>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:20px; border-top:1px solid var(--border); padding-top:12px;">
            <button type="button" class="btn btn-secondary" onclick="closeEditItemModal()">Cancel</button>
            <button type="submit" id="btn-save-edit" class="btn btn-primary">Save Changes</button>
          </div>
        </form>
      </div>
    </div>
    ''' if is_admin else ''}

    <script>
      let variantCardIndex = 0;

      function addPhoneVariantCard(initialData) {{
        initialData = initialData || {{}};
        variantCardIndex++;
        const idx = variantCardIndex;
        const container = document.getElementById('phone-variants-container');
        if (!container) return;

        const card = document.createElement('div');
        card.id = 'vcard-' + idx;
        card.className = 'phone-vcard';
        card.style.cssText = 'background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px;';

        const count = container.querySelectorAll('.phone-vcard').length + 1;
        card.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.07); padding-bottom:6px;">
            <span style="font-size:12px; font-weight:bold; color:#38bdf8;">Variant #${{count}}</span>
            ${{count > 1 ? `<button type="button" class="btn btn-xs btn-danger" style="padding:1px 6px; font-size:11px;" onclick="removeVariantCard(${{idx}})">🗑️ Remove</button>` : ''}}
          </div>
          
          <div style="display:grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 8px;">
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">RAM</label>
              <input type="text" class="form-control form-control-sm v-ram" placeholder="e.g. 8GB" value="${{initialData.ram || '8GB'}}">
            </div>
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Storage</label>
              <input type="text" class="form-control form-control-sm v-storage" placeholder="e.g. 128GB" value="${{initialData.storage || '128GB'}}">
            </div>
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Color *</label>
              <input type="text" class="form-control form-control-sm v-color" placeholder="e.g. Black, Blue" value="${{initialData.color || 'Black'}}" required>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 8px;">
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Retail Price (Rs.) *</label>
              <input type="text" class="form-control form-control-sm v-retail" placeholder="e.g. 45,000" value="${{initialData.retail_price || '0'}}" required>
            </div>
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Cost Price (Rs.)</label>
              <input type="text" class="form-control form-control-sm v-cost" placeholder="e.g. 40,000" value="${{initialData.wholesale_price || '0'}}">
            </div>
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Stock Qty</label>
              <input type="number" class="form-control form-control-sm v-qty" placeholder="0" value="${{initialData.stock_quantity || '0'}}" min="0">
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">PTA Status</label>
              <select class="form-control form-control-sm v-pta">
                <option value="PTA_APPROVED">PTA Approved</option>
                <option value="NON_PTA">Non-PTA</option>
                <option value="JV">JV / Gevey</option>
                <option value="OFFICIAL">Official Warranty</option>
                <option value="FACTORY_UNLOCKED">Factory Unlocked</option>
              </select>
            </div>
            <div>
              <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Condition</label>
              <select class="form-control form-control-sm v-condition">
                <option value="NEW_BOX_PACK">New Box Pack</option>
                <option value="OPEN_BOX">Open Box (10/10)</option>
                <option value="USED">Used / Kit</option>
                <option value="REFURBISHED">Refurbished</option>
              </select>
            </div>
          </div>

          <div style="margin-bottom:6px; background:rgba(0,0,0,0.15); padding:8px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label style="font-size:11px; font-weight:bold; color:#38bdf8; margin-bottom:0;">📱 Dual-IMEI Smartphone Intake (SIM 1 & SIM 2)</label>
              <span class="badge badge-info v-imei-count" id="v-count-${{idx}}" style="font-size:10px;">0 Phones (0 IMEIs)</span>
            </div>
            
            <div style="display:grid; grid-template-columns: 1fr 1fr auto; gap:6px; margin-bottom:6px;">
              <div>
                <input type="text" id="v-quick-imei1-${{idx}}" class="form-control form-control-sm" placeholder="Scan IMEI 1 (SIM 1)" style="font-family:monospace; font-size:11px;" onkeydown="handleCardQuickImeiKey(event, ${{idx}}, 1)">
              </div>
              <div>
                <input type="text" id="v-quick-imei2-${{idx}}" class="form-control form-control-sm" placeholder="Scan IMEI 2 (SIM 2 / Dual SIM)" style="font-family:monospace; font-size:11px;" onkeydown="handleCardQuickImeiKey(event, ${{idx}}, 2)">
              </div>
              <div>
                <button type="button" class="btn btn-xs btn-primary" style="padding:3px 8px; font-size:11px;" onclick="addCardQuickImeiPair(${{idx}})">+ Add Phone</button>
              </div>
            </div>

            <textarea class="form-control form-control-sm v-imeis" rows="2" style="font-family:monospace; font-size:11px;" placeholder="IMEI 1 / IMEI 2 (1 phone per line, or use scanner above)..." oninput="updateImeiCounter(${{idx}})">${{initialData.imeis || ''}}</textarea>
            <small style="color:#94a3b8; font-size:10px;">Har phone ke 2 IMEIs hote hain. 1 phone ke dono IMEIs <code>IMEI 1 / IMEI 2</code> format mein likhein ya upar scan karein.</small>
          </div>
        `;

        container.appendChild(card);
        updateImeiCounter(idx);
      }}

      function handleCardQuickImeiKey(e, idx, fieldNum) {{
        if (e.key === 'Enter') {{
          e.preventDefault();
          if (fieldNum === 1) {{
            const f2 = document.getElementById('v-quick-imei2-' + idx);
            if (f2) f2.focus();
          }} else {{
            addCardQuickImeiPair(idx);
          }}
        }}
      }}

      function addCardQuickImeiPair(idx) {{
        const card = document.getElementById('vcard-' + idx);
        if (!card) return;
        const im1Input = document.getElementById('v-quick-imei1-' + idx);
        const im2Input = document.getElementById('v-quick-imei2-' + idx);
        if (!im1Input) return;
        const im1 = im1Input.value.trim();
        const im2 = im2Input ? im2Input.value.trim() : '';
        if (!im1 && !im2) return;
        const pair = im1 && im2 ? (im1 + ' / ' + im2) : (im1 || im2);
        const txtarea = card.querySelector('.v-imeis');
        if (txtarea) {{
          txtarea.value = txtarea.value.trim() ? (txtarea.value.trim() + '\\n' + pair) : pair;
        }}
        im1Input.value = '';
        if (im2Input) im2Input.value = '';
        im1Input.focus();
        updateImeiCounter(idx);
      }}

      function removeVariantCard(idx) {{
        const card = document.getElementById('vcard-' + idx);
        if (card) card.remove();
      }}

      function updateImeiCounter(idx) {{
        const card = document.getElementById('vcard-' + idx);
        if (!card) return;
        const txt = card.querySelector('.v-imeis').value.trim();
        const countBadge = card.querySelector('#v-count-' + idx);
        const qtyInput = card.querySelector('.v-qty');
        
        if (!txt) {{
          if (countBadge) {{
            countBadge.innerText = '0 Phones (0 IMEIs)';
            countBadge.className = 'badge badge-info';
          }}
          return;
        }}
        const lines = txt.replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        let phoneCount = lines.length;
        let imeiCount = 0;
        lines.forEach(l => {{
          if (l.includes('/') || l.includes('|') || l.includes('\\t') || l.includes(',')) {{
            imeiCount += 2;
          }} else {{
            imeiCount += 1;
          }}
        }});
        if (countBadge) {{
          countBadge.innerText = phoneCount + (phoneCount === 1 ? ' Phone' : ' Phones') + ' (' + imeiCount + ' IMEIs)';
          countBadge.className = phoneCount > 0 ? 'badge badge-success' : 'badge badge-info';
        }}
        if (phoneCount > 0 && (!qtyInput.value || parseInt(qtyInput.value) < phoneCount)) {{
          qtyInput.value = phoneCount;
        }}
      }}

      function openUnifiedItemModal() {{
        const m = document.getElementById('unified-item-modal');
        if (m) {{
          m.style.display = 'flex';
          setTimeout(() => {{
            const n = document.getElementById('u-name');
            if (n) n.focus();
          }}, 50);
        }}
      }}

      function closeUnifiedItemModal() {{
        const m = document.getElementById('unified-item-modal');
        if (m) m.style.display = 'none';
      }}

      function switchItemTab(type) {{
        document.getElementById('item-type-input').value = type;
        const bAcc = document.getElementById('tab-btn-acc');
        const bPhn = document.getElementById('tab-btn-phone');
        const bPrt = document.getElementById('tab-btn-part');
        const psFields = document.getElementById('price-stock-fields');
        const spFields = document.getElementById('spare-part-fields');
        const phnSection = document.getElementById('phone-variants-section');
        const lblName = document.getElementById('lbl-item-name');
        const btnSave = document.getElementById('btn-save-item');
        const btnAnother = document.getElementById('btn-save-another');

        [bAcc, bPhn, bPrt].forEach(b => {{
          b.className = 'btn btn-xs btn-secondary';
          b.style.background = '';
        }});

        if (type === 'ACCESSORY') {{
          bAcc.className = 'btn btn-xs';
          bAcc.style.background = 'var(--primary)';
          psFields.style.display = 'block';
          spFields.style.display = 'none';
          if (phnSection) phnSection.style.display = 'none';
          lblName.innerText = 'Item / Accessory Name *';
          btnSave.innerText = 'Save Accessory';
          if (btnAnother) btnAnother.style.display = 'inline-block';
        }} else if (type === 'SPARE_PART') {{
          bPrt.className = 'btn btn-xs';
          bPrt.style.background = 'var(--primary)';
          psFields.style.display = 'block';
          spFields.style.display = 'block';
          if (phnSection) phnSection.style.display = 'none';
          lblName.innerText = 'Spare Part Name *';
          btnSave.innerText = 'Save Spare Part';
          if (btnAnother) btnAnother.style.display = 'inline-block';
        }} else if (type === 'PHONE') {{
          bPhn.className = 'btn btn-xs';
          bPhn.style.background = 'var(--primary)';
          psFields.style.display = 'none';
          spFields.style.display = 'none';
          if (phnSection) {{
            phnSection.style.display = 'block';
            const pvc = document.getElementById('phone-variants-container');
            if (pvc && pvc.children.length === 0) {{
              addPhoneVariantCard();
            }}
          }}
          lblName.innerText = 'Phone Model Name *';
          btnSave.innerText = 'Save Phone & Variants';
          if (btnAnother) btnAnother.style.display = 'inline-block';
        }}
      }}

      // Keyboard ergonomics: Ctrl+Enter saves and adds another, Esc closes modal
      document.addEventListener('keydown', function(e) {{
        const m = document.getElementById('unified-item-modal');
        if (!m || m.style.display !== 'flex') return;
        if (e.key === 'Escape') {{
          closeUnifiedItemModal();
        }} else if (e.ctrlKey && e.key === 'Enter') {{
          e.preventDefault();
          submitUnifiedItem(e, true);
        }}
      }});

      async function submitUnifiedItem(event, andAddAnother = false) {{
        if (event) event.preventDefault();
        const f = document.getElementById('unified-item-form');
        const alertBox = document.getElementById('unified-form-alert');
        const btnSave = document.getElementById('btn-save-item');
        const btnAnother = document.getElementById('btn-save-another');

        document.querySelectorAll('.field-error').forEach(el => el.style.display = 'none');
        alertBox.style.display = 'none';

        btnSave.disabled = true;
        if (btnAnother) btnAnother.disabled = true;

        const formData = new FormData(f);
        const payload = Object.fromEntries(formData.entries());
        payload.request_id = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : 'REQ_' + Date.now();

        if (payload.item_type === 'PHONE') {{
          const vcards = document.querySelectorAll('#phone-variants-container .phone-vcard');
          const variantsArray = [];
          vcards.forEach(vc => {{
            const ram = (vc.querySelector('.v-ram') ? vc.querySelector('.v-ram').value : '').trim();
            const storage = (vc.querySelector('.v-storage') ? vc.querySelector('.v-storage').value : '').trim();
            const color = (vc.querySelector('.v-color') ? vc.querySelector('.v-color').value : '').trim();
            const retail = (vc.querySelector('.v-retail') ? vc.querySelector('.v-retail').value : '').trim();
            const cost = (vc.querySelector('.v-cost') ? vc.querySelector('.v-cost').value : '').trim();
            const qty = (vc.querySelector('.v-qty') ? vc.querySelector('.v-qty').value : '0').trim();
            const pta = (vc.querySelector('.v-pta') ? vc.querySelector('.v-pta').value : 'PTA_APPROVED');
            const cond = (vc.querySelector('.v-condition') ? vc.querySelector('.v-condition').value : 'NEW_BOX_PACK');
            const imeis = (vc.querySelector('.v-imeis') ? vc.querySelector('.v-imeis').value : '').trim();
            
            if (color || ram || storage || retail) {{
              variantsArray.push({{
                ram: ram,
                storage: storage,
                color: color || 'Standard',
                retail_price: retail,
                wholesale_price: cost,
                stock_quantity: qty,
                imeis: imeis,
                pta_status: pta,
                condition: cond,
                low_stock_level: 2
              }});
            }}
          }});
          if (variantsArray.length === 0) {{
            variantsArray.push({{
              ram: 'Standard',
              storage: 'Standard',
              color: 'Standard',
              retail_price: 0,
              wholesale_price: 0,
              stock_quantity: 0
            }});
          }}
          payload.variants = variantsArray;
        }}

        try {{
          const res = await fetch('/api/items/create', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();

          if (res.status === 201 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerHTML = '✅ ' + (data.message || 'Saved successfully!');

            if (andAddAnother) {{
              document.getElementById('u-name').value = '';
              const pvc = document.getElementById('phone-variants-container');
              if (pvc) {{
                pvc.innerHTML = '';
                addPhoneVariantCard();
              }}
              document.getElementById('u-name').focus();
            }} else {{
              setTimeout(() => {{
                if (payload.item_type === 'PHONE' && data.product_id) {{
                  window.location.href = '/inventory/product/' + data.product_id;
                }} else {{
                  window.location.reload();
                }}
              }}, 600);
            }}
          }} else if (res.status === 422 && data.errors) {{
            let firstField = null;
            data.errors.forEach(err => {{
              const errEl = document.getElementById('err-' + err.field.replace('_', '-'));
              if (errEl) {{
                errEl.innerText = err.message;
                errEl.style.display = 'block';
              }}
              if (!firstField) firstField = document.getElementById('u-' + err.field.replace('_', '-'));
            }});
            if (firstField) firstField.focus();
          }} else if (res.status === 409) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerHTML = '⚠️ ' + data.message;
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerHTML = '❌ ' + (data.message || 'Error creating item.');
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerHTML = 'Connection error: ' + err.message;
        }} finally {{
          btnSave.disabled = false;
          if (btnAnother) btnAnother.disabled = false;
        }}
      }}
    </script>

    <script>
      let currentFilterType = 'ALL';

      function setInitialQty(n) {{
        const el = document.getElementById('u-stock-qty');
        if (el) el.value = n;
      }}

      function filterInvTab(type) {{
        currentFilterType = type;
        document.querySelectorAll('.inv-tab-btn').forEach(b => {{
          b.className = 'btn btn-xs btn-secondary inv-tab-btn';
          b.style.background = '';
          b.style.color = '';
        }});
        const activeBtn = document.getElementById('tab-filter-' + type);
        if (activeBtn) {{
          activeBtn.className = 'btn btn-xs inv-tab-btn';
          activeBtn.style.background = 'var(--primary)';
          activeBtn.style.color = '#fff';
        }}
        applyInventoryFilters();
      }}

      function filterInventoryTable(q) {{
        applyInventoryFilters();
      }}

      function applyInventoryFilters() {{
        const searchInput = document.getElementById('inv-table-filter');
        let q = searchInput ? searchInput.value : '';
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();

        let visibleCount = 0;
        document.querySelectorAll('.inv-row').forEach(r => {{
          const rowType = r.getAttribute('data-type') || '';
          const matchesType = (currentFilterType === 'ALL' || rowType === currentFilterType || (currentFilterType === 'PHONE' && rowType === 'SERIAL'));
          
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          const matchesSearch = (!q || txt.includes(q));

          if (matchesType && matchesSearch) {{
            r.style.display = '';
            visibleCount++;
          }} else {{
            r.style.display = 'none';
          }}
        }});
        const countBadge = document.getElementById('visible-item-count');
        if (countBadge) countBadge.innerText = visibleCount;
      }}

      function openQuickStockFromBtn(btn) {{
        if (!btn) return;
        const vid = btn.getAttribute('data-vid') || 0;
        const title = btn.getAttribute('data-title') || 'Item';
        const cost = btn.getAttribute('data-cost') || '';
        openQuickStockModal(vid, title, cost);
      }}

      function openQuickStockModal(vid, title, currentCost) {{
        document.getElementById('qs-variant-id').value = vid;
        document.getElementById('qs-modal-title').innerText = '➕ Add Stock: ' + title;
        document.getElementById('qs-item-subtitle').innerText = 'Variant #' + vid;
        document.getElementById('qs-qty').value = '10';
        document.getElementById('qs-cost').value = currentCost || '';
        const alertBox = document.getElementById('qs-alert');
        if (alertBox) alertBox.style.display = 'none';
        const m = document.getElementById('quick-stock-modal');
        if (m) m.style.display = 'flex';
        setTimeout(() => {{
          const qInput = document.getElementById('qs-qty');
          if (qInput) qInput.focus();
        }}, 50);
      }}

      function closeQuickStockModal() {{
        const m = document.getElementById('quick-stock-modal');
        if (m) m.style.display = 'none';
      }}

      function addQsQty(n) {{
        const qInput = document.getElementById('qs-qty');
        if (qInput) qInput.value = (parseInt(qInput.value) || 0) + n;
      }}

      async function submitQuickStock(e) {{
        if (e) e.preventDefault();
        const vid = document.getElementById('qs-variant-id').value;
        const qty = document.getElementById('qs-qty').value;
        const cost = document.getElementById('qs-cost').value;
        const btn = document.getElementById('btn-submit-qs');
        const alertBox = document.getElementById('qs-alert');
        if (btn) btn.disabled = true;

        try {{
          const res = await fetch('/inventory/variant/add-stock', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ variant_id: vid, qty: qty, cost_price: cost }})
          }});
          const data = await res.json();
          if (res.status === 200 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ ' + (data.message || 'Stock added successfully!');
            setTimeout(() => window.location.reload(), 500);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || 'Failed to add stock');
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
        }} finally {{
          if (btn) btn.disabled = false;
        }}
      }}

      let currentPhoneVariants = [];
      function openPhoneStockFromBtn(btn) {{
        if (!btn) return;
        const pid = btn.getAttribute('data-pid') || 0;
        const title = btn.getAttribute('data-title') || 'Phone';
        openPhoneStockModal(pid, title);
      }}

      async function openPhoneStockModal(pid, title) {{
        document.getElementById('ps-product-id').value = pid;
        document.getElementById('ps-modal-title').innerText = '➕ Receive Phone Stock: ' + (title || 'Device');
        document.getElementById('ps-cost').value = '';
        document.getElementById('ps-qty').value = '1';
        document.getElementById('ps-imeis').value = '';
        updatePhoneStockImeiCount();
        const alertBox = document.getElementById('ps-alert');
        if (alertBox) alertBox.style.display = 'none';

        try {{
          const res = await fetch('/api/items/' + pid);
          const data = await res.json();
          if (!data.success) {{
            alert('Could not fetch phone variants');
            return;
          }}
          currentPhoneVariants = data.variants || [];
          const sel = document.getElementById('ps-variant-select');
          sel.innerHTML = '';
          currentPhoneVariants.forEach(v => {{
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.innerText = (v.ram ? v.ram + '/' + v.storage + ' ' : '') + (v.color || 'Standard') + ' (' + (v.units_in_stock || 0) + ' in stock) - Rs. ' + (v.retail_price || 0);
            sel.appendChild(opt);
          }});
          onPhoneStockVariantChanged();
          const m = document.getElementById('phone-stock-modal');
          if (m) m.style.display = 'flex';
        }} catch (err) {{
          alert('Error loading phone details: ' + err.message);
        }}
      }}

      function closePhoneStockModal() {{
        const m = document.getElementById('phone-stock-modal');
        if (m) m.style.display = 'none';
      }}

      function onPhoneStockVariantChanged() {{
        const sel = document.getElementById('ps-variant-select');
        const vid = parseInt(sel.value) || 0;
        const v = currentPhoneVariants.find(x => x.id === vid);
        if (v && v.wholesale_price) {{
          document.getElementById('ps-cost').value = v.wholesale_price;
        }}
      }}

      function updatePhoneStockImeiCount() {{
        const txt = document.getElementById('ps-imeis').value.trim();
        const badge = document.getElementById('ps-imei-badge');
        const qtyInput = document.getElementById('ps-qty');
        if (!txt) {{
          if (badge) {{ badge.innerText = '0 IMEIs'; badge.className = 'badge badge-info'; }}
          return;
        }}
        const lines = txt.replace(/,/g, '\\n').replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        if (badge) {{
          badge.innerText = lines.length + ' IMEI' + (lines.length > 1 ? 's' : '');
          badge.className = 'badge badge-success';
        }}
        if (lines.length > 0) {{
          qtyInput.value = lines.length;
        }}
      }}

      async function submitPhoneStock(e) {{
        if (e) e.preventDefault();
        const form = document.getElementById('phone-stock-form');
        const btn = document.getElementById('btn-submit-ps');
        const alertBox = document.getElementById('ps-alert');
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());

        if (btn) btn.disabled = true;
        try {{
          const res = await fetch('/inventory/variant/add-stock', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ ' + (data.message || 'Units received into stock successfully!');
            setTimeout(() => window.location.reload(), 500);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || 'Failed to receive stock');
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
        }} finally {{
          if (btn) btn.disabled = false;
        }}
      }}

      function openPhoneStockFromEdit() {{
        const pid = document.getElementById('edit-product-id').value;
        const brand = document.getElementById('edit-brand').value;
        const name = document.getElementById('edit-name').value;
        closeEditItemModal();
        openPhoneStockModal(pid, brand + ' ' + name);
      }}

      async function openEditItemModal(pid) {{
        const m = document.getElementById('edit-item-modal');
        const alertBox = document.getElementById('edit-form-alert');
        if (alertBox) alertBox.style.display = 'none';

        try {{
          const res = await fetch('/api/items/' + pid);
          const data = await res.json();
          if (!data.success) {{
            alert('Item not found');
            return;
          }}
          const p = data.product;
          const v = data.variant || {{}};
          document.getElementById('edit-product-id').value = p.id;
          document.getElementById('edit-variant-id').value = v.id || 0;
          document.getElementById('edit-brand').value = p.brand || '';
          document.getElementById('edit-category').value = p.category || '';
          document.getElementById('edit-name').value = p.name || '';
          document.getElementById('edit-retail-price').value = v.retail_price || 0;
          document.getElementById('edit-wholesale-price').value = v.wholesale_price || 0;
          document.getElementById('edit-stock-qty').value = v.stock_quantity || 0;
          document.getElementById('edit-barcode').value = v.barcode || v.sku || '';
          document.getElementById('edit-low-stock').value = v.low_stock_level || '';
          document.getElementById('edit-reorder-qty').value = v.reorder_qty || '';
          document.getElementById('edit-modal-title').innerText = '✏️ Edit: ' + p.brand + ' ' + p.name;

          const isPhone = (p.item_type === 'PHONE' || p.item_type === 'SERIAL');
          const phoneNotice = document.getElementById('edit-phone-notice');
          if (phoneNotice) phoneNotice.style.display = isPhone ? 'block' : 'none';
          const unitsLink = document.getElementById('edit-phone-units-link');
          if (unitsLink) unitsLink.href = '/inventory/product/' + p.id + '/units';
          const matrixLink = document.getElementById('edit-phone-matrix-link');
          if (matrixLink) matrixLink.href = '/inventory/matrix-create?product_id=' + p.id;

          const sqInput = document.getElementById('edit-stock-qty');
          const sqBadge = document.getElementById('edit-phone-stock-badge');
          if (sqInput) {{
            sqInput.readOnly = isPhone;
            sqInput.style.backgroundColor = isPhone ? 'rgba(255,255,255,0.06)' : '';
            sqInput.style.color = isPhone ? '#38bdf8' : '';
          }}
          if (sqBadge) {{
            sqBadge.style.display = isPhone ? 'block' : 'none';
          }}

          if (m) m.style.display = 'flex';
        }} catch (err) {{
          alert('Could not fetch item details: ' + err.message);
        }}
      }}

      function closeEditItemModal() {{
        const m = document.getElementById('edit-item-modal');
        if (m) m.style.display = 'none';
      }}

      async function submitEditItem(e) {{
        if (e) e.preventDefault();
        const f = document.getElementById('edit-item-form');
        const btn = document.getElementById('btn-save-edit');
        const alertBox = document.getElementById('edit-form-alert');
        const formData = new FormData(f);
        const payload = Object.fromEntries(formData.entries());

        if (btn) btn.disabled = true;
        try {{
          const res = await fetch('/api/items/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ Saved successfully!';
            setTimeout(() => window.location.reload(), 500);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || (data.errors ? data.errors[0].message : 'Save failed'));
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
        }} finally {{
          if (btn) btn.disabled = false;
        }}
      }}

      let undoTimer = null;
      async function confirmDeleteItem(pid, title) {{
        if (!confirm('Are you sure you want to delete/archive "' + title + '"?')) return;
        try {{
          const res = await fetch('/api/items/delete', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ product_id: pid }})
          }});
          const data = await res.json();
          if (data.success) {{
            const row = document.getElementById('prod-row-' + pid);
            if (row) row.style.opacity = '0.3';
            showInventoryUndoToast(data.message, pid, data.can_undo);
          }} else {{
            alert(data.message || 'Failed to delete item');
          }}
        }} catch(e) {{
          alert('Error deleting item: ' + e.message);
        }}
      }}

      function showInventoryUndoToast(msg, pid, canUndo) {{
        let toast = document.getElementById('inventory-undo-toast');
        if (!toast) {{
          toast = document.createElement('div');
          toast.id = 'inventory-undo-toast';
          toast.style.cssText = 'position:fixed; bottom:24px; right:24px; background:#1e293b; color:#fff; border:1px solid #f59e0b; padding:14px 20px; border-radius:10px; z-index:9999; box-shadow:0 10px 25px rgba(0,0,0,0.5); display:flex; align-items:center; gap:14px; font-size:13px;';
          document.body.appendChild(toast);
        }}
        clearTimeout(undoTimer);
        let sec = 10;
        let undoBtnHtml = canUndo ? '<button id="btn-undo-archive" onclick="undoArchiveItem(' + pid + ')" class="btn btn-warning btn-xs font-weight-bold" style="padding:4px 10px;">↩️ Undo (<span id="undo-countdown">10</span>s)</button>' : '';
        toast.innerHTML = '<span>' + msg + '</span>' + undoBtnHtml;
        toast.style.display = 'flex';
        
        if (canUndo) {{
          const interval = setInterval(() => {{
            sec--;
            const cd = document.getElementById('undo-countdown');
            if (cd) cd.innerText = sec;
            if (sec <= 0) clearInterval(interval);
          }}, 1000);
        }}

        undoTimer = setTimeout(() => {{
          toast.style.display = 'none';
          window.location.reload();
        }}, 10000);
      }}

      async function undoArchiveItem(pid) {{
        clearTimeout(undoTimer);
        const toast = document.getElementById('inventory-undo-toast');
        if (toast) toast.style.display = 'none';
        try {{
          const res = await fetch('/api/items/restore', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ product_id: pid }})
          }});
          const data = await res.json();
          alert(data.message || 'Restored successfully!');
          window.location.reload();
        }} catch(e) {{
          alert('Failed to restore item');
        }}
      }}
    </script>
    """
    return layout("Inventory", content, "inventory", user)

def render_phone_stock_modal_html():
    return """
    <!-- Phone Stock / IMEI Intake Modal (Admin Only) -->
    <div id="phone-stock-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.75); backdrop-filter:blur(4px); z-index:2100; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:520px; max-width:94vw; max-height:92vh; overflow-y:auto; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; border-bottom:1px solid var(--border); padding-bottom:10px;">
          <div>
            <h3 style="font-size:16px; font-weight:800; margin:0; color:var(--text);" id="ps-modal-title">➕ Receive Phone Stock / IMEIs</h3>
            <div style="font-size:11px; color:#94a3b8;" id="ps-modal-subtitle">Fast inventory intake with serial/IMEI validation</div>
          </div>
          <button type="button" onclick="closePhoneStockModal()" style="background:none; border:none; color:var(--text-muted); font-size:20px; cursor:pointer;">✕</button>
        </div>
        <form id="phone-stock-form" onsubmit="submitPhoneStock(event)">
          <input type="hidden" id="ps-product-id" name="product_id" value="">
          <div id="ps-alert" style="display:none; padding:8px 12px; border-radius:6px; margin-bottom:12px; font-size:12px;"></div>

          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">Variant / Specification *</label>
            <select id="ps-variant-select" name="variant_id" class="form-control" required onchange="onPhoneStockVariantChanged()"></select>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Unit Cost Price (Rs.)</label>
              <input type="text" id="ps-cost" name="cost_price" class="form-control form-control-sm" placeholder="e.g. 45000">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">PTA Status</label>
              <select id="ps-pta" name="pta_status" class="form-control form-control-sm">
                <option value="PTA_APPROVED">PTA Approved</option>
                <option value="NON_PTA">Non-PTA</option>
                <option value="JV">JV / Gevey</option>
                <option value="OFFICIAL">Official Warranty</option>
                <option value="FACTORY_UNLOCKED">Factory Unlocked</option>
              </select>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Condition</label>
              <select id="ps-condition" name="condition" class="form-control form-control-sm">
                <option value="NEW_BOX_PACK">New Box Pack</option>
                <option value="OPEN_BOX">Open Box (10/10)</option>
                <option value="USED">Used / Kit</option>
                <option value="REFURBISHED">Refurbished</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Quantity (If no IMEIs scanned)</label>
              <input type="number" id="ps-qty" name="qty" class="form-control form-control-sm" value="1" min="0">
            </div>
          </div>

          <div class="form-group" style="margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label class="form-label" style="font-size:12px; margin-bottom:0; font-weight:bold; color:#38bdf8;">Scan / Enter IMEIs</label>
              <span id="ps-imei-badge" class="badge badge-info" style="font-size:11px;">0 IMEIs</span>
            </div>
            <textarea id="ps-imeis" name="imeis" class="form-control" rows="3" style="font-family:monospace; font-size:12px;" placeholder="Scan barcode with scanner or enter 15-digit IMEIs (comma or new line separated)..." oninput="updatePhoneStockImeiCount()"></textarea>
            <small style="color:#94a3b8; font-size:11px;">Har device ka alag IMEI dakhil karein, ya box barcode scan karein.</small>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px; border-top:1px solid var(--border); padding-top:12px;">
            <button type="button" class="btn btn-secondary" onclick="closePhoneStockModal()">Cancel</button>
            <button type="submit" id="btn-submit-ps" class="btn btn-success font-weight-bold">➕ Add to Stock</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      let currentPhoneVariants = [];
      function openPhoneStockFromBtn(btn) {
        if (!btn) return;
        const pid = btn.getAttribute('data-pid') || 0;
        const title = btn.getAttribute('data-title') || 'Phone';
        openPhoneStockModal(pid, title);
      }

      async function openPhoneStockModal(pid, title) {
        document.getElementById('ps-product-id').value = pid;
        document.getElementById('ps-modal-title').innerText = '➕ Receive Phone Stock: ' + (title || 'Device');
        document.getElementById('ps-cost').value = '';
        document.getElementById('ps-qty').value = '1';
        document.getElementById('ps-imeis').value = '';
        updatePhoneStockImeiCount();
        const alertBox = document.getElementById('ps-alert');
        if (alertBox) alertBox.style.display = 'none';

        try {
          const res = await fetch('/api/items/' + pid);
          const data = await res.json();
          if (!data.success) {
            alert('Could not fetch phone variants');
            return;
          }
          currentPhoneVariants = data.variants || [];
          const sel = document.getElementById('ps-variant-select');
          sel.innerHTML = '';
          currentPhoneVariants.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.innerText = (v.ram ? v.ram + '/' + v.storage + ' ' : '') + (v.color || 'Standard') + ' (' + (v.units_in_stock || 0) + ' in stock) - Rs. ' + (v.retail_price || 0);
            sel.appendChild(opt);
          });
          onPhoneStockVariantChanged();
          const m = document.getElementById('phone-stock-modal');
          if (m) m.style.display = 'flex';
        } catch (err) {
          alert('Error loading phone details: ' + err.message);
        }
      }

      function closePhoneStockModal() {
        const m = document.getElementById('phone-stock-modal');
        if (m) m.style.display = 'none';
      }

      function onPhoneStockVariantChanged() {
        const sel = document.getElementById('ps-variant-select');
        const vid = parseInt(sel.value) || 0;
        const v = currentPhoneVariants.find(x => x.id === vid);
        if (v && v.wholesale_price) {
          document.getElementById('ps-cost').value = v.wholesale_price;
        }
      }

      function updatePhoneStockImeiCount() {
        const txt = document.getElementById('ps-imeis').value.trim();
        const badge = document.getElementById('ps-imei-badge');
        const qtyInput = document.getElementById('ps-qty');
        if (!txt) {
          if (badge) { badge.innerText = '0 IMEIs'; badge.className = 'badge badge-info'; }
          return;
        }
        const lines = txt.replace(/,/g, '\\n').replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        if (badge) {
          badge.innerText = lines.length + ' IMEI' + (lines.length > 1 ? 's' : '');
          badge.className = 'badge badge-success';
        }
        if (lines.length > 0) {
          qtyInput.value = lines.length;
        }
      }

      async function submitPhoneStock(e) {
        if (e) e.preventDefault();
        const form = document.getElementById('phone-stock-form');
        const btn = document.getElementById('btn-submit-ps');
        const alertBox = document.getElementById('ps-alert');
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());

        if (btn) btn.disabled = true;
        try {
          const res = await fetch('/inventory/variant/add-stock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.status === 200 || data.success) {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ ' + (data.message || 'Units received into stock successfully!');
            setTimeout(() => window.location.reload(), 500);
          } else {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || 'Failed to receive stock');
          }
        } catch (err) {
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
        } finally {
          if (btn) btn.disabled = false;
        }
      }
    </script>
    """

def render_edit_unit_modal_html():
    return """
    <!-- Edit Unit / IMEI Modal -->
    <div id="edit-unit-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(3px);">
      <div class="card" style="width:100%; max-width:540px; max-height:92vh; overflow-y:auto; margin:20px; border:1px solid #3b82f6; box-shadow:0 20px 40px rgba(0,0,0,0.7);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div class="card-title" id="edit-unit-modal-title" style="color:#60a5fa; font-size:16px;">✏️ Edit Phone Unit / IMEI</div>
            <div id="edit-unit-subtitle" style="font-size:12px; color:#94a3b8; margin-top:2px;"></div>
          </div>
          <button type="button" onclick="closeEditUnitModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="edit-unit-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        
        <div id="edit-u-sold-warning" style="display:none; margin:12px 16px 0 16px; padding:10px 12px; border-radius:6px; background:rgba(239, 68, 68, 0.15); border:1px solid #ef4444; color:#fca5a5; font-size:12px; line-height:1.4;">
          ⚠️ <strong>Warning:</strong> This unit is marked as <strong id="edit-u-sold-tag">SOLD</strong>. Changing the IMEI or Cost Price will affect historical sales invoices and profit reporting. Admin reason is strictly required.
        </div>

        <form id="form-edit-unit" onsubmit="submitEditUnit(event)" style="padding:16px;">
          <input type="hidden" id="edit-unit-id" name="unit_id" value="">

          <!-- Variant Selector (Move Unit) -->
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">Variant / Specification <small style="color:#60a5fa;">(Change to move unit to another variant)</small></label>
            <select id="edit-u-variant" name="variant_id" class="form-control"></select>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:8px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Primary IMEI 1 *</label>
              <input type="text" id="edit-u-imei1" name="imei1" class="form-control" required style="font-family:monospace; font-weight:bold;">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Secondary IMEI 2</label>
              <input type="text" id="edit-u-imei2" name="imei2" class="form-control" style="font-family:monospace;" placeholder="Optional">
            </div>
          </div>

          <!-- Luhn Override Checkbox -->
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
            <input type="checkbox" id="edit-u-override-luhn" name="override_luhn" value="1" style="width:16px; height:16px; cursor:pointer;">
            <label for="edit-u-override-luhn" style="font-size:12px; color:#cbd5e1; cursor:pointer; margin-bottom:0;">Override 15-digit Luhn Checksum (Non-standard / Demo IMEI)</label>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">PTA Status</label>
              <select id="edit-u-pta" name="pta_status" class="form-control">
                <option value="PTA Approved (Official)">PTA Approved (Official)</option>
                <option value="PTA Approved (CPID)">PTA Approved (CPID)</option>
                <option value="Non-PTA">Non-PTA</option>
                <option value="JV / Gevey">JV / Gevey</option>
                <option value="Official Warranty">Official Warranty</option>
                <option value="Factory Unlocked">Factory Unlocked</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Condition</label>
              <select id="edit-u-condition" name="condition" class="form-control">
                <option value="New Box Pack">New Box Pack</option>
                <option value="Open Box (10/10)">Open Box (10/10)</option>
                <option value="Used (Kit Only)">Used (Kit Only)</option>
                <option value="Used (Kit + Box)">Used (Kit + Box)</option>
                <option value="Refurbished">Refurbished</option>
              </select>
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Cost Price (Rs.)</label>
              <input type="number" id="edit-u-cost" name="cost_price" class="form-control" min="0" step="any">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Battery Health (%)</label>
              <input type="number" id="edit-u-battery" name="battery_health" class="form-control" min="1" max="100" value="100">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Unit Status</label>
              <select id="edit-u-status" name="status" class="form-control">
                <option value="IN_STOCK">IN_STOCK (Available)</option>
                <option value="SOLD">SOLD</option>
                <option value="IN_REPAIR">IN_REPAIR</option>
                <option value="DEFECTIVE">DEFECTIVE</option>
                <option value="RETURNED">RETURNED</option>
              </select>
            </div>
          </div>

          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px;">Admin Reason <small style="color:#94a3b8;">(Mandatory for Sold/In-Repair units or Luhn override)</small></label>
            <input type="text" id="edit-u-admin-reason" name="admin_reason" class="form-control" placeholder="Reason for updating unit...">
          </div>

          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px;">Notes / Remarks</label>
            <input type="text" id="edit-u-notes" name="notes" class="form-control" placeholder="e.g. Minor scratches, battery replaced...">
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeEditUnitModal()">Cancel</button>
            <button type="submit" id="btn-save-edit-unit" class="btn btn-primary font-weight-bold">💾 Update Unit</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      async function openEditUnitModal(uid) {
        const m = document.getElementById('edit-unit-modal');
        const alertBox = document.getElementById('edit-unit-alert');
        const warnBox = document.getElementById('edit-u-sold-warning');
        if (alertBox) alertBox.style.display = 'none';
        if (warnBox) warnBox.style.display = 'none';

        try {
          const res = await fetch('/api/units/' + uid);
          const data = await res.json();
          if (!data.success) {
            alert(data.error || 'Unit not found');
            return;
          }
          const u = data.unit;
          document.getElementById('edit-unit-id').value = u.id;
          document.getElementById('edit-u-imei1').value = u.imei1 || '';
          document.getElementById('edit-u-imei2').value = u.imei2 || '';

          // Populate variants
          const vSelect = document.getElementById('edit-u-variant');
          if (vSelect && data.available_variants) {
            vSelect.innerHTML = '';
            data.available_variants.forEach(v => {
              const opt = document.createElement('option');
              opt.value = v.id;
              opt.textContent = (v.ram || '') + '/' + (v.storage || '') + ' ' + (v.color || '') + (v.network ? ' (' + v.network + ')' : '');
              if (v.id === u.variant_id) opt.selected = true;
              vSelect.appendChild(opt);
            });
          }

          const ptaSelect = document.getElementById('edit-u-pta');
          let ptaFound = false;
          for (let i = 0; i < ptaSelect.options.length; i++) {
            if (ptaSelect.options[i].value.toLowerCase() === (u.pta_status || '').toLowerCase()) {
              ptaSelect.selectedIndex = i;
              ptaFound = true;
              break;
            }
          }
          if (!ptaFound && u.pta_status) {
            ptaSelect.add(new Option(u.pta_status, u.pta_status, true, true));
          }

          const condSelect = document.getElementById('edit-u-condition');
          let condFound = false;
          for (let i = 0; i < condSelect.options.length; i++) {
            if (condSelect.options[i].value.toLowerCase() === (u.condition || '').toLowerCase()) {
              condSelect.selectedIndex = i;
              condFound = true;
              break;
            }
          }
          if (!condFound && u.condition) {
            condSelect.add(new Option(u.condition, u.condition, true, true));
          }

          document.getElementById('edit-u-cost').value = u.cost_price || 0;
          document.getElementById('edit-u-battery').value = u.battery_health || 100;
          document.getElementById('edit-u-status').value = u.status || 'IN_STOCK';
          document.getElementById('edit-u-notes').value = u.notes || '';
          document.getElementById('edit-u-admin-reason').value = '';
          document.getElementById('edit-u-override-luhn').checked = false;
          document.getElementById('edit-unit-subtitle').innerText = (u.brand || '') + ' ' + (u.model_name || '') + ' (' + (u.ram || '') + '/' + (u.storage || '') + ' ' + (u.color || '') + ')';

          if (u.status === 'SOLD' || u.status === 'IN_REPAIR') {
            document.getElementById('edit-u-sold-tag').innerText = u.status;
            if (warnBox) warnBox.style.display = 'block';
          }

          if (m) m.style.display = 'flex';
        } catch (err) {
          alert('Failed to load unit: ' + err.message);
        }
      }

      function closeEditUnitModal() {
        const m = document.getElementById('edit-unit-modal');
        if (m) m.style.display = 'none';
      }

      async function submitEditUnit(e) {
        if (e) e.preventDefault();
        const btn = document.getElementById('btn-save-edit-unit');
        const alertBox = document.getElementById('edit-unit-alert');
        if (btn) btn.disabled = true;
        if (alertBox) alertBox.style.display = 'none';

        const form = document.getElementById('form-edit-unit');
        const payload = Object.fromEntries(new FormData(form).entries());

        try {
          const res = await fetch('/api/units/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.status === 200 && data.success) {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ Unit updated successfully!';
            setTimeout(() => window.location.reload(), 400);
          } else {
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.error || 'Failed to update unit');
            if (btn) btn.disabled = false;
          }
        } catch (err) {
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
          if (btn) btn.disabled = false;
        }
      }
    </script>
    """

@app.route("/inventory/models/<pid:int>")
@app.route("/inventory/models/<pid:int>/")
@app.route("/inventory/product/<pid:int>")
@app.route("/inventory/product/<pid:int>/")
def inventory_model_detail_screen(pid):
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    p = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    if not p:
        content = f"""
        <div class="card" style="max-width: 600px; margin: 40px auto; text-align: center; padding: 36px 24px;">
          <div style="font-size: 48px; margin-bottom: 12px;">📱</div>
          <h2 style="color: #f87171; margin-bottom: 8px;">Model #{pid} Not Found</h2>
          <p style="color: var(--text-muted); font-size: 14px; margin-bottom: 24px;">
            The requested phone model or product was not found or has been archived.
          </p>
          <a href="/inventory" class="btn btn-primary" style="padding: 10px 20px;">&larr; Back to Inventory Stock</a>
        </div>
        """
        return layout("Model Not Found", content, "inventory", user)

    variants = inventory.get_variants_for_product(pid)
    total_stock = sum(v["units_in_stock"] for v in variants)

    if p["item_type"] in ("ACCESSORY", "SPARE_PART"):
        v0 = variants[0] if variants else None
        v0_id = v0["id"] if v0 else 0
        v0_retail = v0["retail_price"] if v0 else 0
        v0_cost = v0["wholesale_price"] if v0 else 0
        v0_barcode = v0["barcode"] if v0 else (v0["sku"] if v0 else "")
        v0_low = v0["low_stock_level"] if v0 and v0["low_stock_level"] is not None else 5
        v0_reorder = v0["reorder_qty"] if v0 and v0["reorder_qty"] is not None else 20

        # Fetch recent ledger movements for this item
        movements = db.query_all("""
            SELECT * FROM stock_ledger 
            WHERE product_id = ? 
            ORDER BY id DESC LIMIT 20
        """, (pid,))

        m_rows = ""
        for m in movements:
            chg_sign = f"+{m['change_qty']}" if m['change_qty'] > 0 else str(m['change_qty'])
            chg_color = "#34d399" if m['change_qty'] > 0 else "#f87171"
            m_rows += f"""
            <tr>
              <td>{m['timestamp']}</td>
              <td><span class="badge badge-info">{m['action_type']}</span></td>
              <td style="font-weight:bold; color:{chg_color};">{chg_sign}</td>
              <td style="font-weight:bold;">{m['balance_qty']} Pcs</td>
              <td>{m['reference'] or '-'}</td>
              <td>{m['notes'] or '-'}</td>
            </tr>
            """

        type_icon = "🎧" if p["item_type"] == "ACCESSORY" else "🔧"
        stock_badge = "badge-success" if total_stock > 0 else "badge-danger"

        content = f"""
        <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
          <div>
            <div style="font-size: 12px; color: var(--text-muted);"><a href="/inventory" style="color: #60a5fa; text-decoration: none;">&larr; Back to Inventory</a></div>
            <h1 style="font-size: 22px; font-weight: 800; margin-top: 4px;">{type_icon} {p['brand']} {p['name']}</h1>
            <div style="font-size: 13px; color: #94a3b8;">Category: {p['category']} &bull; Type: {p['item_type']} &bull; Barcode: <code>{v0_barcode or 'N/A'}</code></div>
          </div>
          <div style="display: flex; gap: 8px;">
            <button type="button" class="btn btn-success btn-sm" onclick="openAddStockDirect()">➕ Add Stock Quantity</button>
            <a href="/print/barcode-label/{v0_id}" target="_blank" class="btn btn-secondary btn-sm">🖨️ Print Label</a>
            <a href="/inventory" class="btn btn-secondary btn-sm">Back to Inventory</a>
          </div>
        </div>

        <!-- Quick Stats -->
        <div class="grid-4" style="margin-bottom: 16px;">
          <div class="card" style="padding: 12px;">
            <div style="font-size: 11px; color: var(--text-muted);">PIECES IN STOCK</div>
            <div style="font-size: 24px; font-weight: 800; color: #34d399; margin-top: 4px;"><span class="badge {stock_badge}" style="font-size:18px;">{total_stock} Pieces</span></div>
          </div>
          <div class="card" style="padding: 12px;">
            <div style="font-size: 11px; color: var(--text-muted);">RETAIL SELLING PRICE</div>
            <div style="font-size: 20px; font-weight: 800; color: #38bdf8; margin-top: 4px;">Rs. {v0_retail:,.0f}</div>
          </div>
          <div class="card" style="padding: 12px;">
            <div style="font-size: 11px; color: var(--text-muted);">COST / WHOLESALE PRICE</div>
            <div style="font-size: 20px; font-weight: 800; color: #a78bfa; margin-top: 4px;">Rs. {v0_cost:,.0f}</div>
          </div>
          <div class="card" style="padding: 12px;">
            <div style="font-size: 11px; color: var(--text-muted);">ALERT THRESHOLD</div>
            <div style="font-size: 20px; font-weight: 800; color: #fbbf24; margin-top: 4px;">Alert at &le; {v0_low} pcs</div>
          </div>
        </div>

        <!-- Stock Movements History Table -->
        <div class="card" style="margin-bottom: 16px;">
          <div class="card-header">
            <div class="card-title">📜 Recent Stock Movements & Audits ({len(movements)})</div>
          </div>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr><th>Date & Time</th><th>Action</th><th>Change</th><th>Balance</th><th>Reference</th><th>Notes</th></tr>
              </thead>
              <tbody>
                {m_rows or '<tr><td colspan="6" style="text-align:center; color:#888;">No stock transactions recorded yet.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Direct Stock Add Modal -->
        <div id="direct-stock-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(2px);">
          <div class="card" style="width:100%; max-width:440px; margin:20px; border:1px solid #10b981; box-shadow:0 20px 40px rgba(0,0,0,0.6); padding:20px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:8px;">
              <h3 style="font-size:16px; font-weight:bold; margin:0; color:#34d399;">➕ Add Stock Quantity</h3>
              <button type="button" onclick="closeAddStockDirect()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
            </div>
            <form method="POST" action="/inventory/variant/add-stock">
              <input type="hidden" name="variant_id" value="{v0_id}">
              <div class="form-group">
                <label class="form-label" style="font-weight:bold; color:#38bdf8;">Quantity to Add *</label>
                <div style="display:flex; gap:6px; margin-bottom:6px;">
                  <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('dir-qty').value=(parseInt(document.getElementById('dir-qty').value)||0)+5">+5</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('dir-qty').value=(parseInt(document.getElementById('dir-qty').value)||0)+10">+10</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('dir-qty').value=(parseInt(document.getElementById('dir-qty').value)||0)+20">+20</button>
                  <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('dir-qty').value=(parseInt(document.getElementById('dir-qty').value)||0)+50">+50</button>
                </div>
                <input type="number" id="dir-qty" name="qty" class="form-control" value="10" min="1" required autofocus style="font-size:16px; font-weight:bold;">
              </div>
              <div class="form-group">
                <label class="form-label">Cost Price (Rs.)</label>
                <input type="text" name="cost_price" class="form-control" value="{v0_cost}">
              </div>
              <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
                <button type="button" class="btn btn-secondary" onclick="closeAddStockDirect()">Cancel</button>
                <button type="submit" class="btn btn-success">Add to Stock</button>
              </div>
            </form>
          </div>
        </div>

        <script>
          function openAddStockDirect() {{
            const m = document.getElementById('direct-stock-modal');
            if (m) m.style.display = 'flex';
          }}
          function closeAddStockDirect() {{
            const m = document.getElementById('direct-stock-modal');
            if (m) m.style.display = 'none';
          }}
        </script>
        """
        return layout(f"{p['name']} Details", content, "inventory", user)
    
    target_unit_id = request.query.get("unit")
    try:
        target_unit_id = int(target_unit_id) if target_unit_id else 0
    except (ValueError, TypeError):
        target_unit_id = 0

    units = db.query_all("""
        SELECT u.*, v.ram, v.storage, v.color, v.retail_price, v.sku
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        WHERE v.product_id = ?
        ORDER BY u.id DESC
    """, (pid,))

    v_rows = ""
    for v in variants:
        stock_badge = "badge-success" if v['units_in_stock'] > 0 else "badge-danger"
        edit_v_btn = f'''<button type="button" class="btn btn-xs btn-info" onclick="openEditVariantModal({v['id']})">✏️ Edit</button>''' if is_admin else ''
        clone_v_btn = f'''<button type="button" class="btn btn-xs btn-secondary" onclick="openCloneVariantModal({v['id']})">👯 Clone</button>''' if is_admin else ''
        arch_v_btn = f'''<button type="button" class="btn btn-xs btn-danger" onclick="archiveVariant({v['id']})">🗄️</button>''' if is_admin else ''
        v_rows += f"""
        <tr>
          <td><strong>{v['ram']}/{v['storage']}</strong></td>
          <td><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background-color:#38bdf8; margin-right:6px;"></span>{v['color']} {f'<small style="color:#94a3b8;">({v["network"]})</small>' if v.get('network') else ''}</td>
          <td><code>{v['barcode'] or 'N/A'}</code></td>
          <td style="font-weight:bold; color:#38bdf8;">Rs. {v['retail_price']:,.0f}</td>
          <td><span class="badge {stock_badge}">{v['units_in_stock']} in stock</span></td>
          <td style="white-space:nowrap; display:flex; gap:4px; align-items:center;">
            <button type="button" class="btn btn-xs btn-primary" onclick="openAddStockModal({v['id']}, '{v['ram']}/{v['storage']} {v['color']}', {v['wholesale_price']})">+ Stock</button>
            {edit_v_btn}
            {clone_v_btn}
            {arch_v_btn}
            <a href="/print/barcode-label/{v['id']}" target="_blank" class="btn btn-xs btn-secondary">Label</a>
          </td>
        </tr>
        """

    u_rows = ""
    for u in units:
        is_target = (u['id'] == target_unit_id)
        highlight_style = "background: rgba(59, 130, 246, 0.2); border-left: 4px solid #3b82f6;" if is_target else ""
        target_badge = '<span class="badge badge-warning" style="margin-left:6px;">Target Unit</span>' if is_target else ""
        status_badge = "badge-success" if u['status'] == 'IN_STOCK' else "badge-danger"
        edit_u_btn = f'''<button type="button" class="btn btn-sm btn-primary" onclick="openEditUnitModal({u['id']})">✏️ Edit</button>''' if is_admin else ''
        u_rows += f"""
        <tr style="{highlight_style}">
          <td><code>{u['imei1']}</code>{target_badge}<br><small style="color:#94a3b8;">{u['imei2'] or ''}</small></td>
          <td>{u['ram']}/{u['storage']} {u['color']}</td>
          <td>{u['condition']}</td>
          <td>{u['pta_status']}</td>
          <td style="font-weight:bold;">Rs. {u['retail_price']:,.0f}</td>
          <td><span class="badge {status_badge}">{u['status']}</span></td>
          <td style="white-space:nowrap; text-align:right;">
            {edit_u_btn}
            <a href="/print/barcode-label/{u['variant_id']}?unit_id={u['id']}" target="_blank" class="btn btn-sm btn-secondary" style="margin-left:4px;">Label</a>
          </td>
        </tr>
        """

    content = f"""
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="font-size: 12px; color: var(--text-muted);"><a href="/inventory" style="color: #60a5fa; text-decoration: none;">&larr; Back to All Inventory Models</a></div>
        <h1 style="font-size: 22px; font-weight: 800; margin-top: 4px;">📱 {p['brand']} {p['name']}</h1>
        <div style="font-size: 13px; color: #94a3b8;">Category: {p['category']} &bull; Type: {p['item_type']} &bull; Total Available Stock: <strong style="color: #34d399;">{total_stock}</strong></div>
      </div>
      <div style="display: flex; gap: 8px;">
        {f'<button type="button" class="btn btn-warning btn-sm" onclick="openEditModelModal()">✏️ Edit Model Details</button>' if is_admin else ''}
        <button type="button" class="btn btn-success btn-sm" onclick="openAddVariantModal()">+ Add Variant & Stock</button>
        <a href="/inventory/matrix-create?product_id={p['id']}" class="btn btn-primary btn-sm">⚡ Variant Matrix</a>
        <a href="/inventory/product/{p['id']}/units" class="btn btn-secondary btn-sm">Full Units View</a>
        <a href="/inventory" class="btn btn-secondary btn-sm">All Inventory</a>
      </div>
    </div>

    <!-- Quick Stats -->
    <div class="grid-4" style="margin-bottom: 16px;">
      <div class="card" style="padding: 12px;">
        <div style="font-size: 11px; color: var(--text-muted);">ACTIVE VARIANTS</div>
        <div style="font-size: 20px; font-weight: 800; color: #38bdf8; margin-top: 4px;">{len(variants)} Specifications</div>
      </div>
      <div class="card" style="padding: 12px;">
        <div style="font-size: 11px; color: var(--text-muted);">UNITS IN STOCK</div>
        <div style="font-size: 20px; font-weight: 800; color: #34d399; margin-top: 4px;">{total_stock} Devices</div>
      </div>
      <div class="card" style="padding: 12px;">
        <div style="font-size: 11px; color: var(--text-muted);">TOTAL UNITS RECORDED</div>
        <div style="font-size: 20px; font-weight: 800; color: #a78bfa; margin-top: 4px;">{len(units)} Units</div>
      </div>
      <div class="card" style="padding: 12px;">
        <div style="font-size: 11px; color: var(--text-muted);">WARRANTY PERIOD</div>
        <div style="font-size: 20px; font-weight: 800; color: #fbbf24; margin-top: 4px;">{p['default_warranty_months']} Months</div>
      </div>
    </div>

    <!-- Variants Table -->
    <div class="card" style="margin-bottom: 16px;">
      <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div class="card-title">RAM / Storage & Color Variants ({len(variants)})</div>
        <button type="button" class="btn btn-xs btn-success" onclick="openAddVariantModal()">+ Add Variant</button>
      </div>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr><th>Memory (RAM/Storage)</th><th>Color</th><th>Barcode</th><th>Retail Price</th><th>Stock Count</th><th>Action</th></tr>
          </thead>
          <tbody>
            {v_rows or '<tr><td colspan="6" style="text-align:center; color:#888;">No variants configured for this model.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Device Units Table (with targeted unit highlighted if applicable) -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">Physical IMEI Units ({len(units)})</div>
        <input type="text" placeholder="🔍 Filter IMEIs..." class="form-control" style="width: 200px; padding: 4px 8px; font-size: 12px;" oninput="filterModelUnits(this.value)">
      </div>
      <div class="table-responsive">
        <table class="data-table" id="model-units-table">
          <thead>
            <tr><th>IMEI 1 / 2</th><th>Specification</th><th>Condition</th><th>PTA Status</th><th>Retail Price</th><th>Status</th><th>Label</th></tr>
          </thead>
          <tbody>
            {u_rows or '<tr><td colspan="7" style="text-align:center; color:#888;">No device units recorded yet.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Add Variant Modal -->
    <div id="add-variant-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(2px);">
      <div class="card" style="width:100%; max-width:620px; max-height:90vh; overflow-y:auto; margin:20px; border:1px solid #38bdf8; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div class="card-title" style="color:#38bdf8; font-size:16px;">📱 Add New Variant: {p['brand']} {p['name']}</div>
          <button type="button" onclick="closeAddVariantModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="modal-variant-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        <form id="form-add-variant" onsubmit="submitModelVariant(event)" style="padding:16px;">
          <input type="hidden" name="product_id" value="{p['id']}">
          <div style="display:grid; grid-template-columns: 1fr 1fr 1.2fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">RAM</label>
              <input type="text" name="ram" class="form-control form-control-sm" placeholder="e.g. 8GB" value="8GB">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Storage</label>
              <input type="text" name="storage" class="form-control form-control-sm" placeholder="e.g. 128GB" value="128GB">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Color *</label>
              <input type="text" name="color" class="form-control form-control-sm" placeholder="e.g. Black" required>
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Retail Price (Rs.) *</label>
              <input type="text" name="retail_price" class="form-control form-control-sm" placeholder="e.g. 45000" required>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Cost Price (Rs.)</label>
              <input type="text" name="wholesale_price" class="form-control form-control-sm" placeholder="e.g. 40000">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Stock Qty</label>
              <input type="number" id="v-qty-input" name="stock_quantity" class="form-control form-control-sm" placeholder="0" min="0" value="0">
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">PTA Status</label>
              <select name="pta_status" class="form-control form-control-sm">
                <option value="PTA_APPROVED">PTA Approved</option>
                <option value="NON_PTA">Non-PTA</option>
                <option value="JV">JV / Gevey</option>
                <option value="OFFICIAL">Official Warranty</option>
                <option value="FACTORY_UNLOCKED">Factory Unlocked</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Condition</label>
              <select name="condition" class="form-control form-control-sm">
                <option value="NEW_BOX_PACK">New Box Pack</option>
                <option value="OPEN_BOX">Open Box (10/10)</option>
                <option value="USED">Used / Kit</option>
                <option value="REFURBISHED">Refurbished</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Low Stock Alert</label>
              <input type="number" name="low_stock_level" class="form-control form-control-sm" value="2" min="0">
            </div>
          </div>
          <div class="form-group" style="margin-bottom:12px; background:rgba(0,0,0,0.15); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label class="form-label" style="font-size:12px; font-weight:bold; color:#38bdf8; margin-bottom:0;">📱 Dual-IMEI Smartphone Intake (SIM 1 & SIM 2)</label>
              <span id="v-imei-count-badge" class="badge badge-info" style="font-size:11px;">0 Phones (0 IMEIs)</span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr auto; gap:6px; margin-bottom:6px;">
              <div>
                <input type="text" id="v-modal-quick-imei1" class="form-control form-control-sm" placeholder="Scan IMEI 1 (SIM 1)" style="font-family:monospace; font-size:11px;" onkeydown="handleModalVQuickImeiKey(event, 1)">
              </div>
              <div>
                <input type="text" id="v-modal-quick-imei2" class="form-control form-control-sm" placeholder="Scan IMEI 2 (SIM 2 / Dual SIM)" style="font-family:monospace; font-size:11px;" onkeydown="handleModalVQuickImeiKey(event, 2)">
              </div>
              <div>
                <button type="button" class="btn btn-xs btn-primary" style="padding:4px 8px; font-size:11px;" onclick="addModalVQuickImeiPair()">+ Add Phone</button>
              </div>
            </div>
            <textarea id="v-imei-textarea" name="imeis" class="form-control" rows="3" style="font-family:monospace; font-size:12px;" placeholder="IMEI 1 / IMEI 2 (1 phone per line, or scan above)..." oninput="updateNewVariantImeiCount()"></textarea>
            <small style="color:#94a3b8; font-size:11px;">Har device ke 2 IMEIs (SIM 1 & SIM 2) darj karein. Qty automatically count ho jayegi.</small>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeAddVariantModal()">Cancel</button>
            <button type="submit" id="btn-save-vmodal" class="btn btn-success font-weight-bold">Save Variant & Stock</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Add Stock to Existing Variant Modal -->
    <div id="add-stock-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(2px);">
      <div class="card" style="width:100%; max-width:540px; max-height:90vh; overflow-y:auto; margin:20px; border:1px solid #10b981; box-shadow:0 20px 40px rgba(0,0,0,0.6);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div class="card-title" style="color:#34d399; font-size:16px;">📦 Receive Stock / IMEIs</div>
            <div id="stock-variant-title" style="font-size:12px; color:#cbd5e1; margin-top:2px;"></div>
          </div>
          <button type="button" onclick="closeAddStockModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="modal-stock-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        <form id="form-add-stock" onsubmit="submitVariantStock(event)" style="padding:16px;">
          <input type="hidden" id="stock-vid-input" name="variant_id" value="">
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Unit Cost Price (Rs.)</label>
              <input type="text" id="stock-cost-input" name="cost_price" class="form-control form-control-sm" placeholder="e.g. 40000">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Quantity (If no IMEIs)</label>
              <input type="number" id="stock-qty-input" name="qty" class="form-control form-control-sm" placeholder="0" min="0" value="0">
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">PTA Status</label>
              <select name="pta_status" class="form-control form-control-sm">
                <option value="PTA_APPROVED">PTA Approved</option>
                <option value="NON_PTA">Non-PTA</option>
                <option value="JV">JV / Gevey</option>
                <option value="OFFICIAL">Official Warranty</option>
                <option value="FACTORY_UNLOCKED">Factory Unlocked</option>
              </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Condition</label>
              <select name="condition" class="form-control form-control-sm">
                <option value="NEW_BOX_PACK">New Box Pack</option>
                <option value="OPEN_BOX">Open Box (10/10)</option>
                <option value="USED">Used / Kit</option>
                <option value="REFURBISHED">Refurbished</option>
              </select>
            </div>
          </div>
          <div class="form-group" style="margin-bottom:12px; background:rgba(0,0,0,0.15); padding:10px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <label class="form-label" style="font-size:12px; font-weight:bold; color:#38bdf8; margin-bottom:0;">📱 Dual-IMEI Smartphone Stock Intake (SIM 1 & SIM 2)</label>
              <span id="stock-imei-count-badge" class="badge badge-info" style="font-size:11px;">0 Phones (0 IMEIs)</span>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr auto; gap:6px; margin-bottom:6px;">
              <div>
                <input type="text" id="stock-modal-quick-imei1" class="form-control form-control-sm" placeholder="Scan IMEI 1 (SIM 1)" style="font-family:monospace; font-size:11px;" onkeydown="handleModalStockQuickImeiKey(event, 1)">
              </div>
              <div>
                <input type="text" id="stock-modal-quick-imei2" class="form-control form-control-sm" placeholder="Scan IMEI 2 (SIM 2 / Dual SIM)" style="font-family:monospace; font-size:11px;" onkeydown="handleModalStockQuickImeiKey(event, 2)">
              </div>
              <div>
                <button type="button" class="btn btn-xs btn-primary" style="padding:4px 8px; font-size:11px;" onclick="addModalStockQuickImeiPair()">+ Add Phone</button>
              </div>
            </div>
            <textarea id="stock-imei-textarea" name="imeis" class="form-control" rows="4" style="font-family:monospace; font-size:12px;" placeholder="IMEI 1 / IMEI 2 (1 phone per line, or scan above)..." oninput="updateAddStockImeiCount()"></textarea>
            <small style="color:#94a3b8; font-size:11px;">Har device ka alag IMEI dakhil karein. 1 phone ke 2 IMEIs (SIM 1 / SIM 2) darj karein.</small>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeAddStockModal()">Cancel</button>
            <button type="submit" id="btn-save-smodal" class="btn btn-success font-weight-bold">Receive Units</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function filterModelUnits(q) {{
        q = q.toLowerCase().trim();
        document.querySelectorAll('#model-units-table tbody tr').forEach(r => {{
          r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
        }});
      }}

      function openAddVariantModal() {{
        const m = document.getElementById('add-variant-modal');
        if (m) {{
          m.style.display = 'flex';
          const a = document.getElementById('modal-variant-alert');
          if (a) a.style.display = 'none';
        }}
      }}

      function closeAddVariantModal() {{
        const m = document.getElementById('add-variant-modal');
        if (m) m.style.display = 'none';
      }}

      function handleModalVQuickImeiKey(e, fieldNum) {{
        if (e.key === 'Enter') {{
          e.preventDefault();
          if (fieldNum === 1) {{
            const f2 = document.getElementById('v-modal-quick-imei2');
            if (f2) f2.focus();
          }} else {{
            addModalVQuickImeiPair();
          }}
        }}
      }}

      function addModalVQuickImeiPair() {{
        const im1Input = document.getElementById('v-modal-quick-imei1');
        const im2Input = document.getElementById('v-modal-quick-imei2');
        if (!im1Input) return;
        const im1 = im1Input.value.trim();
        const im2 = im2Input ? im2Input.value.trim() : '';
        if (!im1 && !im2) return;
        const pair = im1 && im2 ? (im1 + ' / ' + im2) : (im1 || im2);
        const txtarea = document.getElementById('v-imei-textarea');
        if (txtarea) {{
          txtarea.value = txtarea.value.trim() ? (txtarea.value.trim() + '\\n' + pair) : pair;
        }}
        im1Input.value = '';
        if (im2Input) im2Input.value = '';
        im1Input.focus();
        updateNewVariantImeiCount();
      }}

      function updateNewVariantImeiCount() {{
        const txt = document.getElementById('v-imei-textarea').value.trim();
        const badge = document.getElementById('v-imei-count-badge');
        const qtyInput = document.getElementById('v-qty-input');
        if (!txt) {{
          if (badge) {{ badge.innerText = '0 Phones (0 IMEIs)'; badge.className = 'badge badge-info'; }}
          return;
        }}
        const lines = txt.replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        let phoneCount = lines.length;
        let imeiCount = 0;
        lines.forEach(l => {{
          if (l.includes('/') || l.includes('|') || l.includes('\\t') || l.includes(',')) {{
            imeiCount += 2;
          }} else {{
            imeiCount += 1;
          }}
        }});
        if (badge) {{
          badge.innerText = phoneCount + (phoneCount === 1 ? ' Phone' : ' Phones') + ' (' + imeiCount + ' IMEIs)';
          badge.className = phoneCount > 0 ? 'badge badge-success' : 'badge badge-info';
        }}
        if (phoneCount > 0 && qtyInput && (!qtyInput.value || parseInt(qtyInput.value) < phoneCount)) {{
          qtyInput.value = phoneCount;
        }}
      }}

      async function submitModelVariant(e) {{
        e.preventDefault();
        const btn = document.getElementById('btn-save-vmodal');
        const alertBox = document.getElementById('modal-variant-alert');
        btn.disabled = true;
        alertBox.style.display = 'none';
        const form = document.getElementById('form-add-variant');
        const payload = Object.fromEntries(new FormData(form).entries());

        try {{
          const res = await fetch('/inventory/variant/add', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 || res.status === 201 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ ' + (data.message || 'Variant created successfully!');
            setTimeout(() => window.location.reload(), 500);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || 'Failed to create variant');
            btn.disabled = false;
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
          btn.disabled = false;
        }}
      }}

      function openAddStockModal(vid, title, cost) {{
        document.getElementById('stock-vid-input').value = vid;
        document.getElementById('stock-variant-title').innerText = title;
        document.getElementById('stock-cost-input').value = cost || '';
        document.getElementById('stock-qty-input').value = '0';
        document.getElementById('stock-imei-textarea').value = '';
        const badge = document.getElementById('stock-imei-count-badge');
        if (badge) {{ badge.innerText = '0 Phones (0 IMEIs)'; badge.className = 'badge badge-info'; }}
        const alertBox = document.getElementById('modal-stock-alert');
        if (alertBox) alertBox.style.display = 'none';
        const m = document.getElementById('add-stock-modal');
        if (m) m.style.display = 'flex';
      }}

      function closeAddStockModal() {{
        const m = document.getElementById('add-stock-modal');
        if (m) m.style.display = 'none';
      }}

      function handleModalStockQuickImeiKey(e, fieldNum) {{
        if (e.key === 'Enter') {{
          e.preventDefault();
          if (fieldNum === 1) {{
            const f2 = document.getElementById('stock-modal-quick-imei2');
            if (f2) f2.focus();
          }} else {{
            addModalStockQuickImeiPair();
          }}
        }}
      }}

      function addModalStockQuickImeiPair() {{
        const im1Input = document.getElementById('stock-modal-quick-imei1');
        const im2Input = document.getElementById('stock-modal-quick-imei2');
        if (!im1Input) return;
        const im1 = im1Input.value.trim();
        const im2 = im2Input ? im2Input.value.trim() : '';
        if (!im1 && !im2) return;
        const pair = im1 && im2 ? (im1 + ' / ' + im2) : (im1 || im2);
        const txtarea = document.getElementById('stock-imei-textarea');
        if (txtarea) {{
          txtarea.value = txtarea.value.trim() ? (txtarea.value.trim() + '\\n' + pair) : pair;
        }}
        im1Input.value = '';
        if (im2Input) im2Input.value = '';
        im1Input.focus();
        updateAddStockImeiCount();
      }}

      function updateAddStockImeiCount() {{
        const txt = document.getElementById('stock-imei-textarea').value.trim();
        const badge = document.getElementById('stock-imei-count-badge');
        const qtyInput = document.getElementById('stock-qty-input');
        if (!txt) {{
          if (badge) {{ badge.innerText = '0 Phones (0 IMEIs)'; badge.className = 'badge badge-info'; }}
          return;
        }}
        const lines = txt.replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        let phoneCount = lines.length;
        let imeiCount = 0;
        lines.forEach(l => {{
          if (l.includes('/') || l.includes('|') || l.includes('\\t') || l.includes(',')) {{
            imeiCount += 2;
          }} else {{
            imeiCount += 1;
          }}
        }});
        if (badge) {{
          badge.innerText = phoneCount + (phoneCount === 1 ? ' Phone' : ' Phones') + ' (' + imeiCount + ' IMEIs)';
          badge.className = phoneCount > 0 ? 'badge badge-success' : 'badge badge-info';
        }}
        if (phoneCount > 0 && (!qtyInput.value || parseInt(qtyInput.value) < phoneCount)) {{
          qtyInput.value = phoneCount;
        }}
      }}

      async function submitVariantStock(e) {{
        e.preventDefault();
        const btn = document.getElementById('btn-save-smodal');
        const alertBox = document.getElementById('modal-stock-alert');
        btn.disabled = true;
        alertBox.style.display = 'none';
        const form = document.getElementById('form-add-stock');
        const payload = Object.fromEntries(new FormData(form).entries());

        try {{
          const res = await fetch('/inventory/variant/add-stock', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 || res.status === 201 || data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ ' + (data.message || 'Stock added successfully!');
            setTimeout(() => window.location.reload(), 500);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.message || 'Failed to add stock');
            btn.disabled = false;
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Connection error: ' + err.message;
          btn.disabled = false;
        }}
      }}
    </script>

    <!-- Edit Model Modal -->
    <div id="edit-model-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(3px);">
      <div class="card" style="width:100%; max-width:520px; max-height:92vh; overflow-y:auto; margin:20px; border:1px solid #f59e0b; box-shadow:0 20px 40px rgba(0,0,0,0.7);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div class="card-title" style="color:#fbbf24; font-size:16px;">✏️ Edit Phone Model Details</div>
          <button type="button" onclick="closeEditModelModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="edit-model-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        <form id="form-edit-model" onsubmit="submitEditModel(event)" style="padding:16px;">
          <input type="hidden" name="product_id" value="{p['id']}">
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Brand *</label>
              <input type="text" name="brand" class="form-control" value="{p['brand']}" required>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Category *</label>
              <input type="text" name="category" class="form-control" value="{p['category']}" required>
            </div>
          </div>
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">Model Name *</label>
            <input type="text" name="name" class="form-control" value="{p['name']}" required>
          </div>
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px;">Default Warranty (Months)</label>
            <input type="number" name="warranty_months" class="form-control" value="{p['default_warranty_months']}" min="0">
          </div>
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px;">Notes / Description</label>
            <textarea name="notes" class="form-control" rows="2">{p['notes'] or ''}</textarea>
          </div>
          <div class="form-group" style="margin-bottom:16px;">
            <label class="form-label" style="font-size:12px;">Photo / Image URL</label>
            <input type="text" name="image_url" class="form-control" value="{p.get('image_url') or ''}" placeholder="e.g. /static/phones/s23.jpg">
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button type="button" class="btn btn-secondary" onclick="closeEditModelModal()">Cancel</button>
            <button type="submit" id="btn-save-edit-model" class="btn btn-warning font-weight-bold">💾 Save Model Details</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Edit Variant Modal -->
    <div id="edit-variant-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(3px);">
      <div class="card" style="width:100%; max-width:540px; max-height:92vh; overflow-y:auto; margin:20px; border:1px solid #38bdf8; box-shadow:0 20px 40px rgba(0,0,0,0.7);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div class="card-title" style="color:#38bdf8; font-size:16px;">✏️ Edit Variant Specifications</div>
          <button type="button" onclick="closeEditVariantModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="edit-variant-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        <form id="form-edit-variant" onsubmit="submitEditVariant(event)" style="padding:16px;">
          <input type="hidden" id="edit-var-id" name="variant_id" value="">
          <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">RAM</label>
              <input type="text" id="edit-var-ram" name="ram" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Storage</label>
              <input type="text" id="edit-var-storage" name="storage" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Network</label>
              <input type="text" id="edit-var-network" name="network" class="form-control" placeholder="4G/5G">
            </div>
          </div>
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">Color *</label>
            <input type="text" id="edit-var-color" name="color" class="form-control" required>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px; font-weight:bold;">Retail Price *</label>
              <input type="text" id="edit-var-retail" name="retail_price" class="form-control" required>
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Cost Price</label>
              <input type="text" id="edit-var-wholesale" name="wholesale_price" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Min Price</label>
              <input type="text" id="edit-var-min" name="min_selling_price" class="form-control">
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Barcode</label>
              <input type="text" id="edit-var-barcode" name="barcode" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">SKU</label>
              <input type="text" id="edit-var-sku" name="sku" class="form-control">
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Low Stock Alert</label>
              <input type="number" id="edit-var-low" name="low_stock_level" class="form-control" min="0">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Reorder Qty</label>
              <input type="number" id="edit-var-reorder" name="reorder_qty" class="form-control" min="0">
            </div>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button type="button" class="btn btn-secondary" onclick="closeEditVariantModal()">Cancel</button>
            <button type="submit" id="btn-save-edit-var" class="btn btn-primary font-weight-bold">💾 Update Variant</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Clone Variant Modal -->
    <div id="clone-variant-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:9999; align-items:center; justify-content:center; backdrop-filter:blur(3px);">
      <div class="card" style="width:100%; max-width:480px; margin:20px; border:1px solid #a855f7; box-shadow:0 20px 40px rgba(0,0,0,0.7);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div class="card-title" style="color:#c084fc; font-size:16px;">👯 Clone Variant (2-Click Duplicate)</div>
          <button type="button" onclick="closeCloneVariantModal()" style="background:none; border:none; font-size:20px; color:#cbd5e1; cursor:pointer;">&times;</button>
        </div>
        <div id="clone-variant-alert" style="display:none; margin:12px; padding:10px; border-radius:6px; font-size:13px;"></div>
        <form id="form-clone-variant" onsubmit="submitCloneVariant(event)" style="padding:16px;">
          <input type="hidden" id="clone-var-id" name="variant_id" value="">
          <p style="font-size:12px; color:#94a3b8; margin-top:0; margin-bottom:12px;">
            Create a duplicate variant (e.g. new color or RAM/storage) with matching prices and alert thresholds copied automatically.
          </p>
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-size:12px; font-weight:bold;">New Color *</label>
            <input type="text" id="clone-var-color" name="new_color" class="form-control" placeholder="e.g. Silver, Purple, Navy Blue" required>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">RAM</label>
              <input type="text" id="clone-var-ram" name="new_ram" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Storage</label>
              <input type="text" id="clone-var-storage" name="new_storage" class="form-control">
            </div>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:16px;">
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Retail Price (Rs.)</label>
              <input type="text" id="clone-var-retail" name="retail_price" class="form-control">
            </div>
            <div class="form-group" style="margin-bottom:0;">
              <label class="form-label" style="font-size:12px;">Cost Price (Rs.)</label>
              <input type="text" id="clone-var-wholesale" name="wholesale_price" class="form-control">
            </div>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px;">
            <button type="button" class="btn btn-secondary" onclick="closeCloneVariantModal()">Cancel</button>
            <button type="submit" id="btn-submit-clone-var" class="btn btn-primary font-weight-bold" style="background:#a855f7; border-color:#9333ea;">👯 Clone Variant Now</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function openEditModelModal() {{
        const m = document.getElementById('edit-model-modal');
        if (m) m.style.display = 'flex';
      }}
      function closeEditModelModal() {{
        const m = document.getElementById('edit-model-modal');
        if (m) m.style.display = 'none';
      }}
      async function submitEditModel(e) {{
        e.preventDefault();
        const btn = document.getElementById('btn-save-edit-model');
        const alertBox = document.getElementById('edit-model-alert');
        btn.disabled = true;
        if (alertBox) alertBox.style.display = 'none';
        const form = document.getElementById('form-edit-model');
        const payload = Object.fromEntries(new FormData(form).entries());
        try {{
          const res = await fetch('/api/products/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 && data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ Model updated successfully!';
            setTimeout(() => window.location.reload(), 400);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.error || 'Failed to update model');
            btn.disabled = false;
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Error: ' + err.message;
          btn.disabled = false;
        }}
      }}

      async function openEditVariantModal(vid) {{
        const m = document.getElementById('edit-variant-modal');
        const alertBox = document.getElementById('edit-variant-alert');
        if (alertBox) alertBox.style.display = 'none';
        try {{
          const res = await fetch('/api/variants/' + vid);
          const data = await res.json();
          if (!data.success) {{ alert(data.error || 'Variant not found'); return; }}
          const v = data.variant;
          document.getElementById('edit-var-id').value = v.id;
          document.getElementById('edit-var-ram').value = v.ram || '';
          document.getElementById('edit-var-storage').value = v.storage || '';
          document.getElementById('edit-var-color').value = v.color || '';
          document.getElementById('edit-var-network').value = v.network || '';
          document.getElementById('edit-var-retail').value = v.retail_price || 0;
          document.getElementById('edit-var-wholesale').value = v.wholesale_price || 0;
          document.getElementById('edit-var-min').value = v.min_selling_price || 0;
          document.getElementById('edit-var-barcode').value = v.barcode || '';
          document.getElementById('edit-var-sku').value = v.sku || '';
          document.getElementById('edit-var-low').value = v.low_stock_level || 5;
          document.getElementById('edit-var-reorder').value = v.reorder_qty || 10;
          if (m) m.style.display = 'flex';
        }} catch (err) {{
          alert('Could not fetch variant: ' + err.message);
        }}
      }}
      function closeEditVariantModal() {{
        const m = document.getElementById('edit-variant-modal');
        if (m) m.style.display = 'none';
      }}
      async function submitEditVariant(e) {{
        e.preventDefault();
        const btn = document.getElementById('btn-save-edit-var');
        const alertBox = document.getElementById('edit-variant-alert');
        btn.disabled = true;
        if (alertBox) alertBox.style.display = 'none';
        const form = document.getElementById('form-edit-variant');
        const payload = Object.fromEntries(new FormData(form).entries());
        try {{
          const res = await fetch('/api/variants/update', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 && data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ Variant updated successfully!';
            setTimeout(() => window.location.reload(), 400);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.error || 'Failed to update variant');
            btn.disabled = false;
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Error: ' + err.message;
          btn.disabled = false;
        }}
      }}

      async function openCloneVariantModal(vid) {{
        const m = document.getElementById('clone-variant-modal');
        const alertBox = document.getElementById('clone-variant-alert');
        if (alertBox) alertBox.style.display = 'none';
        try {{
          const res = await fetch('/api/variants/' + vid);
          const data = await res.json();
          if (!data.success) {{ alert(data.error || 'Variant not found'); return; }}
          const v = data.variant;
          document.getElementById('clone-var-id').value = v.id;
          document.getElementById('clone-var-color').value = '';
          document.getElementById('clone-var-ram').value = v.ram || '';
          document.getElementById('clone-var-storage').value = v.storage || '';
          document.getElementById('clone-var-retail').value = v.retail_price || 0;
          document.getElementById('clone-var-wholesale').value = v.wholesale_price || 0;
          if (m) m.style.display = 'flex';
        }} catch (err) {{
          alert('Could not fetch variant: ' + err.message);
        }}
      }}
      function closeCloneVariantModal() {{
        const m = document.getElementById('clone-variant-modal');
        if (m) m.style.display = 'none';
      }}
      async function submitCloneVariant(e) {{
        e.preventDefault();
        const btn = document.getElementById('btn-submit-clone-var');
        const alertBox = document.getElementById('clone-variant-alert');
        btn.disabled = true;
        if (alertBox) alertBox.style.display = 'none';
        const form = document.getElementById('form-clone-variant');
        const payload = Object.fromEntries(new FormData(form).entries());
        try {{
          const res = await fetch('/api/variants/clone', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 && data.success) {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(16, 185, 129, 0.2)';
            alertBox.style.border = '1px solid #10b981';
            alertBox.style.color = '#34d399';
            alertBox.innerText = '✅ Variant cloned successfully!';
            setTimeout(() => window.location.reload(), 400);
          }} else {{
            alertBox.style.display = 'block';
            alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
            alertBox.style.border = '1px solid #ef4444';
            alertBox.style.color = '#f87171';
            alertBox.innerText = '❌ ' + (data.error || 'Failed to clone variant');
            btn.disabled = false;
          }}
        }} catch (err) {{
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(239, 68, 68, 0.2)';
          alertBox.style.border = '1px solid #ef4444';
          alertBox.style.color = '#f87171';
          alertBox.innerText = 'Error: ' + err.message;
          btn.disabled = false;
        }}
      }}

      async function archiveVariant(vid) {{
        if (!confirm('Are you sure you want to archive this variant?')) return;
        try {{
          const res = await fetch('/api/variants/archive', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ variant_id: vid }})
          }});
          const data = await res.json();
          if (res.status === 200 && data.success) {{
            window.location.reload();
          }} else {{
            alert('Failed to archive variant: ' + (data.error || 'Unknown error'));
          }}
        }} catch (err) {{
          alert('Network error: ' + err.message);
        }}
      }}
    </script>
    """
    content += render_edit_unit_modal_html()
    return layout(f"{p['brand']} {p['name']} — Inventory Details", content, "inventory", user)

@app.route("/inventory/create-product", method="POST")
def create_product_route():
    user = require_admin()
    payload = dict(request.forms)
    itype = str(payload.get("item_type") or "PHONE").strip().upper()
    if itype in ("ACCESSORY", "SPARE_PART"):
        res = inventory.create_item_unified(payload, user_id=user["id"], username=user["username"])
        if not res.get("success"):
            err_msg = res.get("message") or (res.get("errors", [{}])[0].get("message") if res.get("errors") else "Failed to add item")
            return redirect(f"/inventory?error={urllib.parse.quote(err_msg)}")
        return redirect("/inventory")

    b = payload.get("brand", "").strip()
    n = payload.get("name", "").strip()
    cat = payload.get("category", "Smartphone").strip()
    pid = inventory.create_product(b, n, category=cat, item_type=itype, user_id=user["id"], username=user["username"])
    return redirect(f"/inventory/matrix-create?product_id={pid}")

@app.route("/inventory/variant/add", method="POST")
def variant_add_route():
    user = require_admin()
    if request.json:
        payload = request.json
    else:
        payload = dict(request.forms)
    
    pid = int(payload.get("product_id") or 0)
    p = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    if not p:
        if request.json:
            return HTTPResponse(status=404, body=json.dumps({"success": False, "message": "Product not found"}), content_type="application/json")
        return redirect("/inventory?error=Product+not+found")

    res = inventory.create_item_unified({
        "product_id": pid,
        "brand": p["brand"],
        "name": p["name"],
        "category": p["category"],
        "item_type": p["item_type"],
        "variants": [{
            "ram": (payload.get("ram") or "").strip(),
            "storage": (payload.get("storage") or "").strip(),
            "color": (payload.get("color") or "").strip() or "Standard",
            "retail_price": payload.get("retail_price", 0),
            "wholesale_price": payload.get("wholesale_price") or payload.get("cost_price", 0),
            "stock_quantity": payload.get("stock_quantity") or payload.get("qty", 0),
            "imeis": payload.get("imeis", ""),
            "pta_status": payload.get("pta_status", "PTA_APPROVED"),
            "condition": payload.get("condition", "NEW_BOX_PACK"),
            "low_stock_level": payload.get("low_stock_level", 2)
        }]
    }, user_id=user["id"], username=user["username"])

    if request.json:
        status_code = res.get("status", 200 if res.get("success") else 400)
        return HTTPResponse(status=status_code, body=json.dumps(res), content_type="application/json")
    
    if not res.get("success"):
        err = res.get("message") or "Failed to add variant"
        return redirect(f"/inventory/product/{pid}?error={urllib.parse.quote(err)}")
    return redirect(f"/inventory/product/{pid}?success=Variant+added+successfully")

@app.route("/inventory/variant/add-stock", method="POST")
def variant_add_stock_route():
    user = require_perm("manage_stock")
    if request.json:
        payload = request.json
    else:
        payload = dict(request.forms)

    vid = int(payload.get("variant_id") or 0)
    cost = payload.get("cost_price", 0)
    imeis = payload.get("imeis", "")
    qty = payload.get("qty", 0)
    condition = payload.get("condition", "NEW_BOX_PACK")
    pta_status = payload.get("pta_status", "PTA_APPROVED")
    mode = payload.get("mode", "PURCHASE")
    supplier_id = int(payload.get("supplier_id") or 0)
    payment_method = payload.get("payment_method", "CASH")
    paid_amount = payload.get("paid_amount")
    request_id = str(payload.get("request_id") or "").strip()
    notes = str(payload.get("notes") or "").strip()

    res = inventory.add_stock(
        variant_id=vid,
        cost_price=cost,
        imeis=imeis,
        qty=qty,
        condition=condition,
        pta_status=pta_status,
        mode=mode,
        supplier_id=supplier_id,
        payment_method=payment_method,
        paid_amount=paid_amount,
        request_id=request_id,
        notes=notes,
        user_id=user["id"],
        username=user["username"]
    )

    if request.json:
        status_code = res.get("status", 200 if res.get("success") else 400)
        return HTTPResponse(status=status_code, body=json.dumps(res), content_type="application/json")

    v = db.query_one("SELECT product_id FROM variants WHERE id = ?", (vid,))
    pid = v["product_id"] if v else 0
    if not res.get("success"):
        err = res.get("message") or "Failed to add stock"
        return redirect(f"/inventory/product/{pid}?error={urllib.parse.quote(err)}")
    return redirect(f"/inventory/product/{pid}?success=Stock+added+successfully")

@app.route("/inventory/matrix-create")
def matrix_creator_screen():
    user = require_admin()
    pid = safe_int(request.query.get("product_id", 0))
    products = db.query_all("SELECT * FROM products WHERE item_type = 'PHONE' ORDER BY brand ASC, name ASC")

    options = ""
    for p in products:
        sel = "selected" if p["id"] == pid else ""
        options += f'<option value="{p["id"]}" {sel}>{p["brand"]} {p["name"]}</option>'

    err_param = request.query.get("error", "")
    succ_param = request.query.get("success", "")
    err_banner = f'<div id="matrix-top-error" style="background:rgba(239,68,68,0.2); border:1px solid #ef4444; color:#f87171; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-weight:bold;">⚠️ {err_param}</div>' if err_param else '<div id="matrix-top-error" style="display:none; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-weight:bold;"></div>'
    succ_banner = f'<div id="matrix-top-success" style="background:rgba(16,185,129,0.2); border:1px solid #10b981; color:#34d399; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-weight:bold;">✅ {succ_param}</div>' if succ_param else '<div id="matrix-top-success" style="display:none; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-weight:bold;"></div>'

    has_products = len(products) > 0
    show_new_fields = "block" if not has_products or pid == 0 else "none"

    content = f"""
    <div class="card" style="max-width: 900px; margin: 0 auto;">
      <div class="card-header">
        <div class="card-title">⚡ Variant Matrix Creator (Color & RAM/Storage Combos)</div>
        <a href="/inventory" class="btn btn-sm btn-secondary">Back to Inventory</a>
      </div>
      <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">
        Ek saath tamaam Memory aur Colors ke variants banayein, aur har variant ka alag stock aur Dual-IMEIs (SIM 1 & SIM 2) darj karein.
      </p>

      {err_banner}
      {succ_banner}

      <form id="matrix-form" method="POST" action="/inventory/matrix-create-submit">
        <input type="hidden" id="matrix-variants-json" name="variants_json" value="">
        
        <div class="form-group">
          <label class="form-label">Phone Model</label>
          <select id="matrix-product-id" name="product_id" class="form-control" onchange="toggleMatrixNewModel(this.value)" required>
            <option value="NEW" {"selected" if not has_products or pid == 0 else ""}>➕ [ Create New Phone Model ]</option>
            {options}
          </select>

          <div id="matrix-new-model-box" style="display:{show_new_fields}; padding:12px; background:rgba(255,255,255,0.03); border:1px dashed var(--border); border-radius:6px; margin-top:8px;">
            <div style="font-size:12px; font-weight:bold; color:#38bdf8; margin-bottom:6px;">📱 New Phone Model Setup</div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px;">
              <div>
                <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Brand *</label>
                <input type="text" id="matrix-new-brand" name="new_brand" class="form-control form-control-sm" placeholder="e.g. Samsung, Apple, Xiaomi, Vivo, Infinix">
              </div>
              <div>
                <label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Model Name *</label>
                <input type="text" id="matrix-new-model" name="new_model" class="form-control form-control-sm" placeholder="e.g. Galaxy S24 Ultra, Redmi Note 13">
              </div>
            </div>
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">RAM / Storage Combinations (Comma-separated)</label>
          <input type="text" id="matrix-combos" name="combos" class="form-control" value="4GB/64GB, 4GB/128GB, 6GB/128GB, 8GB/128GB, 8GB/256GB" required>
          <small style="color:#94a3b8;">Format: RAM/Storage (e.g. 4GB/128GB)</small>
        </div>

        <div class="form-group">
          <label class="form-label">Colors (Comma-separated)</label>
          <input type="text" id="matrix-colors" name="colors" class="form-control" value="Black, Blue, Green, Silver, Gold" required>
        </div>

        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div class="form-group">
            <label class="form-label">Base Retail Price (Rs.)</label>
            <input type="text" id="matrix-retail" name="retail_price" class="form-control" value="55000" required>
          </div>
          <div class="form-group">
            <label class="form-label">Base Wholesale / Cost Price (Rs.)</label>
            <input type="text" id="matrix-wholesale" name="wholesale_price" class="form-control" value="50000" required>
          </div>
        </div>

        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top:8px; padding:12px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px;">
          <div class="form-group">
            <label class="form-label">Low Stock Alert Threshold</label>
            <div style="display:flex; gap:6px; margin-bottom:4px;">
              <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('input-matrix-alert-level').value=1">1</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('input-matrix-alert-level').value=2">2</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('input-matrix-alert-level').value=3">3</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('input-matrix-alert-level').value=5">5</button>
              <button type="button" class="btn btn-xs btn-secondary" onclick="document.getElementById('input-matrix-alert-level').value=10">10</button>
            </div>
            <input type="number" id="input-matrix-alert-level" name="low_stock_level" class="form-control" placeholder="Inherit category default (leave blank)">
            <small style="color:#94a3b8;">When stock drops to or below this qty, alert fires.</small>
          </div>
          <div class="form-group">
            <label class="form-label">Default Reorder Qty</label>
            <input type="number" id="matrix-reorder-qty" name="reorder_qty" class="form-control" placeholder="Default (e.g. 10)">
            <div style="margin-top:10px;">
              <label style="font-size:12px; color:#cbd5e1; cursor:pointer;">
                <input type="checkbox" name="alert_off" value="1"> 🔕 Don't alert for these variants
              </label>
            </div>
          </div>
        </div>

        <div style="display:flex; gap:10px; margin-top:16px;">
          <button type="button" class="btn btn-primary" style="flex:1; padding:12px; font-weight:bold;" onclick="renderMatrixPreview()">
            📋 Preview Combinations & Add Stock / Dual IMEIs
          </button>
          <button type="submit" class="btn btn-secondary" style="padding:12px; font-weight:bold;">
            ⚡ 1-Click Fast Generate (0 Stock)
          </button>
        </div>

        <!-- Interactive Combinations Preview & Stock Section -->
        <div id="matrix-preview-section" style="display:none; margin-top:24px; border-top:1px solid var(--border); padding-top:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <div>
              <strong style="font-size:15px; color:#38bdf8;">📱 Variant Combinations & Stock Intake Grid</strong>
              <div style="font-size:12px; color:#94a3b8;">Har combination ki qeemat, stock aur Dual IMEIs (SIM 1 & SIM 2) set karein.</div>
            </div>
            <span id="matrix-combo-count" class="badge badge-info">0 Combinations</span>
          </div>

          <div id="matrix-preview-cards">
            <!-- Dynamic cards rendered here -->
          </div>

          <div style="margin-top:16px; padding-top:12px; border-top:1px solid var(--border);">
            <button type="button" id="btn-matrix-save-all" class="btn btn-success" style="width:100%; padding:14px; font-size:15px; font-weight:bold;" onclick="submitMatrixWithStock()">
              💾 Save All Variants with Configured Stock & IMEIs
            </button>
          </div>
        </div>
      </form>
    </div>

    <script>
      function toggleMatrixNewModel(val) {{
        const box = document.getElementById('matrix-new-model-box');
        if (box) {{
          box.style.display = (val === 'NEW') ? 'block' : 'none';
        }}
      }}

      function renderMatrixPreview() {{
        const combosStr = document.getElementById('matrix-combos').value.trim();
        const colorsStr = document.getElementById('matrix-colors').value.trim();
        const baseRetail = document.getElementById('matrix-retail').value.trim() || '0';
        const baseCost = document.getElementById('matrix-wholesale').value.trim() || '0';
        const baseAlert = document.getElementById('input-matrix-alert-level').value.trim() || '2';

        const combos = combosStr.split(',').map(s => s.trim()).filter(Boolean);
        const colors = colorsStr.split(',').map(s => s.trim()).filter(Boolean);

        if (combos.length === 0 || colors.length === 0) {{
          alert('Please enter at least one RAM/Storage combo and one Color.');
          return;
        }}

        const container = document.getElementById('matrix-preview-cards');
        container.innerHTML = '';
        let cardIdx = 0;

        combos.forEach(c => {{
          let ram = '', storage = c;
          if (c.includes('/')) {{
            const parts = c.split('/');
            ram = parts[0].trim();
            storage = parts[1].trim();
          }}
          colors.forEach(col => {{
            cardIdx++;
            const idx = cardIdx;
            const card = document.createElement('div');
            card.className = 'matrix-row-card';
            card.style.cssText = 'background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:12px;';
            const comboLabel = (ram ? ram + '/' : '') + storage + ' — ' + col;
            card.innerHTML = 
              '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid rgba(255,255,255,0.06); padding-bottom:6px;">' +
                '<span style="font-weight:bold; color:#38bdf8;">📱 ' + comboLabel + '</span>' +
                '<span class="badge badge-info" id="m-count-' + idx + '" style="font-size:10px;">0 Phones (0 IMEIs)</span>' +
              '</div>' +
              '<input type="hidden" class="m-ram" value="' + ram + '">' +
              '<input type="hidden" class="m-storage" value="' + storage + '">' +
              '<input type="hidden" class="m-color" value="' + col + '">' +
              '<div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:8px; margin-bottom:8px;">' +
                '<div>' +
                  '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Retail Price (Rs.) *</label>' +
                  '<input type="text" class="form-control form-control-sm m-retail" value="' + baseRetail + '" required>' +
                '</div>' +
                '<div>' +
                  '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Cost Price (Rs.)</label>' +
                  '<input type="text" class="form-control form-control-sm m-cost" value="' + baseCost + '">' +
                '</div>' +
                '<div>' +
                  '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Stock Qty</label>' +
                  '<input type="number" class="form-control form-control-sm m-qty" value="0" min="0">' +
                '</div>' +
              '</div>' +
              '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin-bottom:8px;">' +
                '<div>' +
                  '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">PTA Status</label>' +
                  '<select class="form-control form-control-sm m-pta">' +
                    '<option value="PTA_APPROVED">PTA Approved</option>' +
                    '<option value="NON_PTA">Non-PTA</option>' +
                    '<option value="JV">JV / Gevey</option>' +
                    '<option value="OFFICIAL">Official Warranty</option>' +
                    '<option value="FACTORY_UNLOCKED">Factory Unlocked</option>' +
                  '</select>' +
                '</div>' +
                '<div>' +
                  '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Condition</label>' +
                  '<select class="form-control form-control-sm m-cond">' +
                    '<option value="NEW_BOX_PACK">New Box Pack</option>' +
                    '<option value="OPEN_BOX">Open Box (10/10)</option>' +
                    '<option value="USED">Used / Kit</option>' +
                    '<option value="REFURBISHED">Refurbished</option>' +
                  '</select>' +
                '</div>' +
              '</div>' +
              '<div style="background:rgba(0,0,0,0.15); padding:8px; border-radius:6px; border:1px solid rgba(255,255,255,0.06);">' +
                '<div style="display:grid; grid-template-columns: 1fr 1fr auto; gap:6px; margin-bottom:6px;">' +
                  '<input type="text" id="m-quick-imei1-' + idx + '" class="form-control form-control-sm" placeholder="Scan IMEI 1 (SIM 1)" style="font-family:monospace; font-size:11px;" onkeydown="handleMatrixQuickImeiKey(event, ' + idx + ', 1)">' +
                  '<input type="text" id="m-quick-imei2-' + idx + '" class="form-control form-control-sm" placeholder="Scan IMEI 2 (SIM 2 / Dual SIM)" style="font-family:monospace; font-size:11px;" onkeydown="handleMatrixQuickImeiKey(event, ' + idx + ', 2)">' +
                  '<button type="button" class="btn btn-xs btn-primary" style="padding:3px 8px; font-size:11px;" onclick="addMatrixQuickImeiPair(' + idx + ')">+ Add Phone</button>' +
                '</div>' +
                '<label style="font-size:11px; color:#cbd5e1; display:block; margin-bottom:2px;">Physical IMEIs (IMEI 1 / IMEI 2 per phone):</label>' +
                '<textarea class="form-control form-control-sm m-imeis" rows="2" style="font-family:monospace; font-size:11px;" placeholder="IMEI 1 / IMEI 2 (1 phone per line, or scan above)..." oninput="updateMatrixImeiCounter(' + idx + ')"></textarea>' +
                '<small style="color:#94a3b8; font-size:10px;">Har phone ke 2 IMEIs (SIM 1 & SIM 2) darj karein.</small>' +
              '</div>';
            container.appendChild(card);
          }});
        }});

        document.getElementById('matrix-combo-count').innerText = cardIdx + ' Combinations';
        const section = document.getElementById('matrix-preview-section');
        section.style.display = 'block';
        section.scrollIntoView({{ behavior: 'smooth' }});
      }}

      function handleMatrixQuickImeiKey(e, idx, fieldNum) {{
        if (e.key === 'Enter') {{
          e.preventDefault();
          if (fieldNum === 1) {{
            const f2 = document.getElementById('m-quick-imei2-' + idx);
            if (f2) f2.focus();
          }} else {{
            addMatrixQuickImeiPair(idx);
          }}
        }}
      }}

      function addMatrixQuickImeiPair(idx) {{
        const im1Input = document.getElementById('m-quick-imei1-' + idx);
        const im2Input = document.getElementById('m-quick-imei2-' + idx);
        if (!im1Input) return;
        const im1 = im1Input.value.trim();
        const im2 = im2Input ? im2Input.value.trim() : '';
        if (!im1 && !im2) return;
        const pair = im1 && im2 ? (im1 + ' / ' + im2) : (im1 || im2);
        const cards = document.querySelectorAll('.matrix-row-card');
        const card = cards[idx - 1];
        if (card) {{
          const txtarea = card.querySelector('.m-imeis');
          if (txtarea) {{
            txtarea.value = txtarea.value.trim() ? (txtarea.value.trim() + '\\n' + pair) : pair;
          }}
        }}
        im1Input.value = '';
        if (im2Input) im2Input.value = '';
        im1Input.focus();
        updateMatrixImeiCounter(idx);
      }}

      function updateMatrixImeiCounter(idx) {{
        const cards = document.querySelectorAll('.matrix-row-card');
        const card = cards[idx - 1];
        if (!card) return;
        const txt = card.querySelector('.m-imeis').value.trim();
        const badge = card.querySelector('#m-count-' + idx);
        const qtyInput = card.querySelector('.m-qty');

        if (!txt) {{
          if (badge) {{ badge.innerText = '0 Phones (0 IMEIs)'; badge.className = 'badge badge-info'; }}
          return;
        }}
        const lines = txt.replace(/;/g, '\\n').split('\\n').map(s => s.trim()).filter(Boolean);
        let phoneCount = lines.length;
        let imeiCount = 0;
        lines.forEach(l => {{
          if (l.includes('/') || l.includes('|') || l.includes('\\t') || l.includes(',')) {{
            imeiCount += 2;
          }} else {{
            imeiCount += 1;
          }}
        }});
        if (badge) {{
          badge.innerText = phoneCount + (phoneCount === 1 ? ' Phone' : ' Phones') + ' (' + imeiCount + ' IMEIs)';
          badge.className = phoneCount > 0 ? 'badge badge-success' : 'badge badge-info';
        }}
        if (phoneCount > 0 && (!qtyInput.value || parseInt(qtyInput.value) < phoneCount)) {{
          qtyInput.value = phoneCount;
        }}
      }}

      async function submitMatrixWithStock() {{
        const saveBtn = document.getElementById('btn-matrix-save-all');
        const errBox = document.getElementById('matrix-top-error');
        const succBox = document.getElementById('matrix-top-success');
        if (errBox) errBox.style.display = 'none';
        if (succBox) succBox.style.display = 'none';

        const cards = document.querySelectorAll('.matrix-row-card');
        if (cards.length === 0) {{
          alert('Please click Preview Combinations first.');
          return;
        }}

        const prodSelect = document.getElementById('matrix-product-id');
        const pidVal = prodSelect ? prodSelect.value : '0';
        const newBrand = document.getElementById('matrix-new-brand') ? document.getElementById('matrix-new-brand').value.trim() : '';
        const newModel = document.getElementById('matrix-new-model') ? document.getElementById('matrix-new-model').value.trim() : '';

        if (pidVal === 'NEW' && (!newBrand || !newModel)) {{
          if (errBox) {{
            errBox.style.display = 'block';
            errBox.style.background = 'rgba(239,68,68,0.2)';
            errBox.style.border = '1px solid #ef4444';
            errBox.style.color = '#f87171';
            errBox.innerText = '⚠️ Please enter Brand and Model Name for the new phone model.';
            errBox.scrollIntoView({{ behavior: 'smooth' }});
          }} else {{
            alert('Please enter Brand and Model Name for the new phone model.');
          }}
          return;
        }}

        const variantsArray = [];
        cards.forEach(card => {{
          const ram = card.querySelector('.m-ram').value;
          const storage = card.querySelector('.m-storage').value;
          const color = card.querySelector('.m-color').value;
          const retail = card.querySelector('.m-retail').value;
          const cost = card.querySelector('.m-cost').value;
          const qty = card.querySelector('.m-qty').value;
          const pta = card.querySelector('.m-pta').value;
          const cond = card.querySelector('.m-cond').value;
          const imeis = card.querySelector('.m-imeis').value.trim();

          variantsArray.push({{
            ram: ram,
            storage: storage,
            color: color,
            retail_price: retail,
            wholesale_price: cost,
            stock_quantity: qty,
            imeis: imeis,
            pta_status: pta,
            condition: cond,
            low_stock_level: 2
          }});
        }});

        if (saveBtn) {{
          saveBtn.disabled = true;
          saveBtn.innerText = '⏳ Saving Variants & Stock...';
        }}

        try {{
          const payload = {{
            product_id: pidVal,
            new_brand: newBrand,
            new_model: newModel,
            variants: variantsArray
          }};
          const res = await fetch('/inventory/matrix-create-submit', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          if (res.status === 200 || res.status === 201 || data.success) {{
            if (succBox) {{
              succBox.style.display = 'block';
              succBox.style.background = 'rgba(16,185,129,0.2)';
              succBox.style.border = '1px solid #10b981';
              succBox.style.color = '#34d399';
              succBox.innerText = '✅ ' + (data.message || 'Variants and stock created successfully! Redirecting...');
              succBox.scrollIntoView({{ behavior: 'smooth' }});
            }}
            const targetPid = data.product_id || (data.data && data.data.product_id) || pidVal;
            setTimeout(() => {{
              window.location.href = '/inventory/product/' + targetPid + '?success=Variants+and+stock+created+successfully';
            }}, 400);
          }} else {{
            if (saveBtn) {{
              saveBtn.disabled = false;
              saveBtn.innerText = '💾 Save All Variants with Configured Stock & IMEIs';
            }}
            if (errBox) {{
              errBox.style.display = 'block';
              errBox.style.background = 'rgba(239,68,68,0.2)';
              errBox.style.border = '1px solid #ef4444';
              errBox.style.color = '#f87171';
              errBox.innerText = '❌ ' + (data.message || 'Failed to create variants');
              errBox.scrollIntoView({{ behavior: 'smooth' }});
            }} else {{
              alert('Failed to save variants: ' + (data.message || 'Unknown error'));
            }}
          }}
        }} catch (err) {{
          if (saveBtn) {{
            saveBtn.disabled = false;
            saveBtn.innerText = '💾 Save All Variants with Configured Stock & IMEIs';
          }}
          if (errBox) {{
            errBox.style.display = 'block';
            errBox.style.background = 'rgba(239,68,68,0.2)';
            errBox.style.border = '1px solid #ef4444';
            errBox.style.color = '#f87171';
            errBox.innerText = '❌ Network error: ' + err.message;
            errBox.scrollIntoView({{ behavior: 'smooth' }});
          }} else {{
            alert('Network error: ' + err.message);
          }}
        }}
      }}
    </script>
    """
    return layout("Variant Matrix Creator", content, "inventory", user)

@app.route("/inventory/matrix-create-submit", method="POST")
def matrix_create_submit():
    user = require_admin()
    if request.json:
        payload = request.json
        raw_pid = payload.get("product_id", 0)
        new_brand = str(payload.get("new_brand") or "").strip()
        new_model = str(payload.get("new_model") or "").strip()
        variants_raw = payload.get("variants")
    else:
        raw_pid = request.forms.get("product_id", 0)
        new_brand = str(request.forms.get("new_brand") or "").strip()
        new_model = str(request.forms.get("new_model") or "").strip()
        variants_json = request.forms.get("variants_json", "").strip()
        variants_raw = None
        if variants_json:
            try:
                variants_raw = json.loads(variants_json)
            except Exception:
                variants_raw = None

    try:
        pid = int(raw_pid) if str(raw_pid).isdigit() else 0
    except Exception:
        pid = 0

    if (pid <= 0 or str(raw_pid).upper() == "NEW") and new_brand and new_model:
        existing_p = db.query_one("SELECT * FROM products WHERE brand = ? AND name = ? AND item_type = 'PHONE'", (new_brand, new_model))
        if existing_p:
            pid = existing_p["id"]
        else:
            pid = inventory.create_product(new_brand, new_model, category="Mobile Phone", item_type="PHONE", user_id=user["id"], username=user["username"])

    if pid <= 0:
        if request.json:
            return HTTPResponse(status=400, body=json.dumps({"success": False, "message": "Please select an existing Phone Model or provide Brand & Model Name."}), content_type="application/json")
        return redirect("/inventory/matrix-create?error=" + urllib.parse.quote("Please select an existing Phone Model or provide Brand & Model Name."))

    if variants_raw and isinstance(variants_raw, list) and len(variants_raw) > 0:
        prod = inventory.get_product(pid)
        if not prod:
            if request.json:
                return HTTPResponse(status=404, body=json.dumps({"success": False, "message": "Product not found"}), content_type="application/json")
            return redirect("/inventory?error=Product+not+found")
        
        res = inventory.create_item_unified({
            "product_id": pid,
            "brand": prod["brand"],
            "name": prod["name"],
            "category": prod["category"],
            "item_type": prod["item_type"],
            "variants": variants_raw
        }, user_id=user["id"], username=user["username"])

        if request.json:
            status_code = res.get("status", 200 if res.get("success") else 400)
            res["product_id"] = pid
            return HTTPResponse(status=status_code, body=json.dumps(res), content_type="application/json")
        
        if not res.get("success"):
            err = res.get("message") or "Failed to create variants"
            return redirect(f"/inventory/matrix-create?product_id={pid}&error={urllib.parse.quote(err)}")
        return redirect(f"/inventory/product/{pid}?success=Variants+and+stock+created+successfully")

    combos_str = request.forms.get("combos", "")
    colors_str = request.forms.get("colors", "")
    rp = inventory.parse_money(request.forms.get("retail_price", 0))
    wp = inventory.parse_money(request.forms.get("wholesale_price", 0))
    lev_str = request.forms.get("low_stock_level", "").strip()
    low_level = int(lev_str) if lev_str else None
    reorder_str = request.forms.get("reorder_qty", "").strip()
    reorder_qty = int(reorder_str) if reorder_str else None
    alert_off = 1 if request.forms.get("alert_off") else 0

    combos = []
    for c in combos_str.split(","):
        c = c.strip()
        if "/" in c:
            parts = c.split("/")
            combos.append({"ram": parts[0].strip(), "storage": parts[1].strip()})
        elif c:
            combos.append({"ram": "", "storage": c})

    colors = [col.strip() for col in colors_str.split(",") if col.strip()]

    try:
        inventory.generate_variant_matrix(
            pid, combos, colors, rp, wp,
            base_low_stock_level=low_level,
            base_reorder_qty=reorder_qty,
            user_id=user["id"], username=user["username"]
        )
        if alert_off:
            db.execute("UPDATE variants SET alert_off = 1 WHERE product_id = ?", (pid,))
            db.execute("UPDATE stock_alert_state SET state = 'OFF' WHERE variant_id IN (SELECT id FROM variants WHERE product_id = ?)", (pid,))
        return redirect(f"/inventory/product/{pid}?success=Variants+created+successfully")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return redirect(f"/inventory/matrix-create?product_id={pid}&error={urllib.parse.quote(str(e))}")

@app.route("/inventory/product/<pid:int>/units")
def product_units_screen(pid):
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    p = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    if not p: return redirect("/inventory")

    units = db.query_all("""
        SELECT u.*, v.ram, v.storage, v.color, v.retail_price
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        WHERE v.product_id = ?
        ORDER BY u.id DESC
    """, (pid,))

    u_rows = ""
    for u in units:
        status_badge = "badge-success" if u['status'] == 'IN_STOCK' else "badge-danger"
        s_corp = f"{u['imei1']} {u['imei2'] or ''} {u['ram'].lower()} {u['storage'].lower()} {u['color'].lower()} {u['condition'].lower()} {u['pta_status'].lower()} {u['status'].lower()}"
        u_rows += f"""
        <tr class="unit-row" data-search="{s_corp}">
          <td><code>{u['imei1']}</code><br><small style="color:#94a3b8;">{u['imei2'] or ''}</small></td>
          <td>{u['ram']}/{u['storage']} {u['color']}</td>
          <td>{u['condition']}</td>
          <td>{u['pta_status']}</td>
          <td>Rs. {u['retail_price']:,.0f}</td>
          <td><span class="badge {status_badge}">{u['status']}</span></td>
          <td style="white-space:nowrap; text-align:right;">
            <button type="button" class="btn btn-sm btn-primary" onclick="openEditUnitModal({u['id']})">✏️ Edit</button>
            <a href="/print/barcode-label/{u['variant_id']}?unit_id={u['id']}" target="_blank" class="btn btn-sm btn-secondary" style="margin-left:4px;">Label</a>
          </td>
        </tr>
        """

    safe_title = html.escape(f"{p['brand']} {p['name']}")
    content = f"""
    <div class="card">
      <div class="card-header">
        <div class="card-title">📱 {p['brand']} {p['name']} — Device Units ({len(units)} total)</div>
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" placeholder="🔍 Live filter IMEIs..." class="form-control" style="width:220px; padding:6px 10px; font-size:12px;" oninput="filterUnitsTable(this.value)">
          {f'<button type="button" class="btn btn-sm btn-success" data-pid="{p["id"]}" data-title="{safe_title}" onclick="openPhoneStockFromBtn(this)">➕ Add Stock / IMEIs</button>' if is_admin else ''}
          <a href="/inventory/product/{p['id']}" class="btn btn-sm btn-info">Product Details</a>
          <a href="/inventory" class="btn btn-sm btn-secondary">Back to Inventory</a>
        </div>
      </div>

      <div class="table-responsive">
        <table class="data-table" id="units-table">
          <thead>
            <tr>
              <th>IMEI 1 / 2</th>
              <th>Variant</th>
              <th>Condition</th>
              <th>PTA Status</th>
              <th>Retail Price</th>
              <th>Status</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {u_rows or '<tr><td colspan="7" style="text-align:center; color:#888;">No units registered yet. Receive stock in Purchases (F3).</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <script>
      function filterUnitsTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.unit-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    content += render_edit_unit_modal_html()
    if is_admin:
        content += render_phone_stock_modal_html()
    return layout(f"{p['name']} Units", content, "inventory", user)

# ═══════════════════════════════════════════════════════════
# SMART LOW-STOCK ALERTS & REORDER INTELLIGENCE SCREEN
# ═══════════════════════════════════════════════════════════

@app.route("/inventory/low-stock")
@app.route("/inventory/reorder")
def low_stock_screen():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    shop = printing.get_shop_info()

    status_filter = request.query.get("status", "all").strip().lower()
    cat_filter = request.query.get("category", "").strip()

    sql = """
        SELECT v.*, p.name AS model_name, p.brand, p.category, p.item_type,
               s.state, s.snoozed_until, s.on_order_qty, s.on_order_date, s.on_order_notes,
               s.last_transition_at, s.last_notified_at
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN stock_alert_state s ON v.id = s.variant_id
        WHERE v.is_archived = 0 AND p.is_archived = 0
    """
    params = []
    if cat_filter and cat_filter.lower() != "all":
        sql += " AND p.category = ?"
        params.append(cat_filter)

    sql += " ORDER BY CASE WHEN s.state = 'OUT' THEN 0 WHEN s.state = 'LOW' THEN 1 ELSE 2 END ASC, p.brand ASC, p.name ASC"
    rows = db.query_all(sql, params)

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    items = []
    out_count = 0
    low_count = 0
    ordered_count = 0
    healthy_count = 0
    est_capital_total = 0.0

    for r in rows:
        vid = r["id"]
        cfg = alert_engine.get_effective_alert_config(r, r)
        stock = alert_engine.compute_variant_stock(None, vid, r["item_type"])

        if cfg["alert_off"]:
            st = "OFF"
        elif stock == 0:
            st = "OUT"
        elif stock <= cfg["effective_level"]:
            st = "LOW"
        else:
            st = "OK"

        is_snoozed = bool(r["snoozed_until"] and r["snoozed_until"] > now_iso)
        is_on_order = bool(r["on_order_qty"] and r["on_order_qty"] > 0)

        if st == "OUT": out_count += 1
        elif st == "LOW": low_count += 1
        elif st == "OK": healthy_count += 1
        if is_on_order: ordered_count += 1

        reorder_info = alert_engine.get_reorder_intelligence(vid)
        suggested = reorder_info["suggested_reorder_qty"] if reorder_info else (cfg["reorder_qty"] or 10)
        last_cost = reorder_info["last_cost"] if reorder_info else (r["wholesale_price"] or 0)
        days_left = reorder_info["days_stock_left"] if reorder_info else None
        last_sup_name = reorder_info["last_supplier_name"] if reorder_info else ""
        last_sup_phone = reorder_info["last_supplier_phone"] if reorder_info else ""

        if st in ("OUT", "LOW"):
            est_capital_total += (suggested * last_cost)

        # Filtering logic
        if status_filter == "out" and st != "OUT": continue
        if status_filter == "low" and st != "LOW": continue
        if status_filter == "ordered" and not is_on_order: continue
        if status_filter == "ok" and st != "OK": continue

        specs = f"{r['ram']} {r['storage']} {r['color']}".strip()
        items.append({
            "variant_id": vid,
            "product_id": r["product_id"],
            "model_name": r["model_name"],
            "brand": r["brand"],
            "category": r["category"],
            "item_type": r["item_type"],
            "specs": specs,
            "barcode": r["barcode"] or "",
            "sku": r["sku"] or "",
            "retail_price": r["retail_price"],
            "wholesale_price": last_cost,
            "current_stock": stock,
            "effective_level": cfg["effective_level"],
            "reorder_qty": cfg["reorder_qty"],
            "inherited_from": cfg["inherited_from"],
            "alert_off": cfg["alert_off"],
            "state": st,
            "is_snoozed": is_snoozed,
            "snoozed_until": r["snoozed_until"],
            "is_on_order": is_on_order,
            "on_order_qty": r["on_order_qty"] or 0,
            "on_order_date": r["on_order_date"] or "",
            "on_order_notes": r["on_order_notes"] or "",
            "days_left": days_left,
            "suggested_reorder_qty": suggested,
            "last_supplier_name": last_sup_name,
            "last_supplier_phone": last_sup_phone,
            "last_cost": last_cost
        })

    # Available categories
    cats = db.query_all("SELECT DISTINCT category FROM products WHERE is_archived = 0 ORDER BY category ASC")
    cat_chips = f'<a href="/inventory/low-stock?status={status_filter}" class="btn btn-sm {"btn-primary" if not cat_filter else "btn-secondary"}" style="border-radius:16px;">All Categories</a> '
    for c in cats:
        if not c["category"]: continue
        act = "btn-primary" if cat_filter == c["category"] else "btn-secondary"
        cat_chips += f'<a href="/inventory/low-stock?status={status_filter}&category={urllib.parse.quote(c["category"])}" class="btn btn-sm {act}" style="border-radius:16px;">{c["category"]}</a> '

    table_rows = ""
    for it in items:
        st_color = "#ef4444" if it["state"] == "OUT" else ("#f59e0b" if it["state"] == "LOW" else "#10b981")
        st_badge = "badge-danger" if it["state"] == "OUT" else ("badge-warning" if it["state"] == "LOW" else "badge-success")
        st_label = "OUT OF STOCK" if it["state"] == "OUT" else (f"LOW ({it['current_stock']} left)" if it["state"] == "LOW" else "HEALTHY (OK)")

        order_badge = ""
        if it["is_on_order"]:
            order_badge = f'<span class="badge badge-purple" style="margin-left:4px;" title="Expected {it["on_order_date"]}">📦 On Order: {it["on_order_qty"]}</span>'

        snooze_badge = ""
        if it["is_snoozed"]:
            snooze_badge = f'<span class="badge badge-secondary" style="margin-left:4px;" title="Snoozed until {it["snoozed_until"]}">⏰ Snoozed</span>'

        # Velocity text
        if it["days_left"] is not None:
            vel_text = f"<span style='color:#f59e0b; font-weight:bold;'>~{it['days_left']} days</span>"
        elif it["state"] == "OUT":
            vel_text = "<span style='color:#ef4444; font-weight:bold;'>Depleted</span>"
        else:
            vel_text = "<span style='color:#94a3b8;'>Low velocity</span>"

        # WhatsApp link
        phone_raw = it["last_supplier_phone"] or shop["whatsapp"]
        clean_phone = "".join(filter(str.isdigit, str(phone_raw)))
        if clean_phone.startswith("0"): clean_phone = "92" + clean_phone[1:]
        wa_msg = f"Assalam-o-Alaikum! Please quote/supply: {it['brand']} {it['model_name']} ({it['specs']}) - Required Qty: {it['suggested_reorder_qty']} pcs. Shop: {shop['name']}"
        wa_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(wa_msg)}"

        s_corpus = f"{it['brand'].lower()} {it['model_name'].lower()} {it['specs'].lower()} {it['category'].lower()} {it['state'].lower()} {it['barcode']}"

        inh_hint = "Category Default" if "category" in it['inherited_from'] else ("Global Default" if "global" in it['inherited_from'] else "Custom Item Level")

        table_rows += f"""
        <tr class="alert-row" data-search="{s_corpus}">
          <td style="width:30px; text-align:center;">
            <input type="checkbox" class="alert-check" value="{it['variant_id']}">
          </td>
          <td>
            <strong>{it['brand']} {it['model_name']}</strong>
            <br><small style="color:#94a3b8;">{it['specs'] or 'Standard'} &bull; Barcode: <code>{it['barcode'] or 'N/A'}</code></small>
          </td>
          <td>{it['category']}</td>
          <td style="text-align:center; font-weight:bold; font-size:14px; color:{st_color};">
            {it['current_stock']}
          </td>
          <td style="text-align:center;">
            <span style="font-weight:bold;">{it['effective_level']}</span>
            <br><small style="color:#64748b; font-size:10px;">{inh_hint}</small>
          </td>
          <td style="text-align:center;">
            <span class="badge {st_badge}">{st_label}</span>
            {order_badge}
            {snooze_badge}
          </td>
          <td style="text-align:center;">{vel_text}</td>
          <td style="text-align:center; font-weight:800; font-size:14px; color:#10b981; background:rgba(16,185,129,0.06);">
            {it['suggested_reorder_qty']}
          </td>
          <td>
            {it['last_supplier_name'] or 'Wholesale Market' if is_admin else 'Hidden'}
            <br><small style="color:#94a3b8;">{f"Cost: Rs. {it['last_cost']:,.0f}" if is_admin else ""}</small>
          </td>
          <td style="text-align:right; white-space:nowrap;">
            <a href="/purchasing?variant_id={it['variant_id']}&reorder_qty={it['suggested_reorder_qty']}" class="btn btn-sm btn-primary" title="Draft Purchase Order">📥 PO</a>
            <a href="{wa_url}" target="_blank" class="btn btn-sm btn-success" title="Send WhatsApp Order to Supplier">💬 WA</a>
            <button type="button" class="btn btn-sm btn-secondary" onclick="openSnoozePrompt({it['variant_id']})" title="Snooze Alert">⏰</button>
            <button type="button" class="btn btn-sm btn-secondary" onclick="openMarkOrderedModal({it['variant_id']}, '{it['brand']} {it['model_name']}', {it['suggested_reorder_qty']})" title="Mark as On Order">📦</button>
            <button type="button" class="btn btn-sm btn-secondary" onclick="openEditLevelModal({it['variant_id']}, '{it['brand']} {it['model_name']}', {it['effective_level']}, {it['reorder_qty'] or 10}, {1 if it['alert_off'] else 0})" title="Edit Alert Level">✏️</button>
          </td>
        </tr>
        """

    content = f"""
    <!-- Top Summary KPI Cards -->
    <div style="display:grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 16px;">
      <div class="card" style="border-left: 4px solid #ef4444; padding:14px;">
        <div style="font-size: 11px; color: var(--text-muted); font-weight:bold;">🚨 OUT OF STOCK</div>
        <div style="font-size: 22px; font-weight: 800; color: #ef4444; margin-top: 4px;">{out_count} Items</div>
        <div style="font-size: 11px; color: #94a3b8;">Lost sales risk</div>
      </div>
      <div class="card" style="border-left: 4px solid #f59e0b; padding:14px;">
        <div style="font-size: 11px; color: var(--text-muted); font-weight:bold;">⚠️ LOW STOCK ALERT</div>
        <div style="font-size: 22px; font-weight: 800; color: #f59e0b; margin-top: 4px;">{low_count} Items</div>
        <div style="font-size: 11px; color: #94a3b8;">At or below threshold</div>
      </div>
      <div class="card" style="border-left: 4px solid #8b5cf6; padding:14px;">
        <div style="font-size: 11px; color: var(--text-muted); font-weight:bold;">📦 ON ORDER</div>
        <div style="font-size: 22px; font-weight: 800; color: #a78bfa; margin-top: 4px;">{ordered_count} Items</div>
        <div style="font-size: 11px; color: #94a3b8;">Pending inward shipment</div>
      </div>
      <div class="card" style="border-left: 4px solid #10b981; padding:14px;">
        <div style="font-size: 11px; color: var(--text-muted); font-weight:bold;">✅ HEALTHY STOCK</div>
        <div style="font-size: 22px; font-weight: 800; color: #34d399; margin-top: 4px;">{healthy_count} Items</div>
        <div style="font-size: 11px; color: #94a3b8;">Well above thresholds</div>
      </div>
      <div class="card" style="border-left: 4px solid #3b82f6; padding:14px;">
        <div style="font-size: 11px; color: var(--text-muted); font-weight:bold;">💰 EST. REORDER CAPITAL</div>
        <div style="font-size: 22px; font-weight: 800; color: #60a5fa; margin-top: 4px;">Rs. {est_capital_total:,.0f}</div>
        <div style="font-size: 11px; color: #94a3b8;">To restore optimal stock</div>
      </div>
    </div>

    <!-- Toolbar & Filter Bar -->
    <div class="card" style="margin-bottom: 16px; padding:12px 16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
        <!-- Status Filter Pills -->
        <div style="display:flex; gap:6px; align-items:center;">
          <a href="/inventory/low-stock?status=all{f'&category={urllib.parse.quote(cat_filter)}' if cat_filter else ''}" class="btn btn-sm {'btn-primary' if status_filter == 'all' else 'btn-secondary'}" style="border-radius:16px;">All ({len(rows)})</a>
          <a href="/inventory/low-stock?status=out{f'&category={urllib.parse.quote(cat_filter)}' if cat_filter else ''}" class="btn btn-sm {'btn-danger' if status_filter == 'out' else 'btn-secondary'}" style="border-radius:16px;">🚨 Out ({out_count})</a>
          <a href="/inventory/low-stock?status=low{f'&category={urllib.parse.quote(cat_filter)}' if cat_filter else ''}" class="btn btn-sm {'btn-warning' if status_filter == 'low' else 'btn-secondary'}" style="border-radius:16px;">⚠️ Low ({low_count})</a>
          <a href="/inventory/low-stock?status=ordered{f'&category={urllib.parse.quote(cat_filter)}' if cat_filter else ''}" class="btn btn-sm {'btn-primary' if status_filter == 'ordered' else 'btn-secondary'}" style="border-radius:16px;">📦 On Order ({ordered_count})</a>
          <a href="/inventory/low-stock?status=ok{f'&category={urllib.parse.quote(cat_filter)}' if cat_filter else ''}" class="btn btn-sm {'btn-success' if status_filter == 'ok' else 'btn-secondary'}" style="border-radius:16px;">✅ OK ({healthy_count})</a>
        </div>

        <!-- Action Buttons -->
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" id="alert-search-input" placeholder="🔍 Live search item or specs..." class="form-control" style="width:200px; padding:5px 10px; font-size:12px;" oninput="filterAlertsTable(this.value)">
          <button type="button" class="btn btn-secondary btn-sm" onclick="openBulkLevelModal()">⚡ Bulk Set Level</button>
          <a href="/print/reorder-sheet" target="_blank" class="btn btn-secondary btn-sm">🖨️ Print A4 Advice</a>
          <a href="/inventory/low-stock/export.csv" class="btn btn-success btn-sm">📥 Export Excel/CSV</a>
        </div>
      </div>

      <!-- Category Filter Chips -->
      <div style="margin-top:10px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.06); display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
        <span style="font-size:11px; color:var(--text-muted); font-weight:bold;">Categories:</span>
        {cat_chips}
      </div>
    </div>

    <!-- Data Table -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">📦 Inventory Reorder Intelligence & Stock Status ({len(items)} items)</div>
        <div style="font-size:11.5px; color:var(--text-muted);">
          Suggested reorder quantities calculated based on past 30-day velocity and lead time target.
        </div>
      </div>

      <div class="table-responsive">
        <table class="data-table" id="alerts-table">
          <thead>
            <tr>
              <th style="width:30px; text-align:center;"><input type="checkbox" id="check-all" onclick="toggleSelectAllAlerts(this)"></th>
              <th>Product Model & Specs</th>
              <th>Category</th>
              <th style="text-align:center;">In Stock</th>
              <th style="text-align:center;">Threshold</th>
              <th style="text-align:center;">Status</th>
              <th style="text-align:center;">Days Left</th>
              <th style="text-align:center;">Suggested Qty</th>
              <th>Last Supplier</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            {table_rows or '<tr><td colspan="10" style="text-align:center; padding:24px; color:#10b981;">✅ No items match the current stock filter. All inventory healthy!</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal: Mark as Ordered -->
    <div id="mark-ordered-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:20000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:440px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:800; color:var(--text);">📦 Mark Goods as Ordered</h3>
          <button type="button" onclick="closeMarkOrderedModal()" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form onsubmit="submitMarkOrdered(event)">
          <input type="hidden" id="mo-variant-id">
          <p style="font-size:13px; margin-bottom:12px;">Item: <strong id="mo-item-name" style="color:#38bdf8;"></strong></p>
          <div class="form-group">
            <label class="form-label">Ordered Quantity</label>
            <input type="number" id="mo-qty" class="form-control" style="font-size:16px; font-weight:bold;" required>
          </div>
          <div class="form-group">
            <label class="form-label">Expected Arrival Date</label>
            <input type="date" id="mo-date" class="form-control">
          </div>
          <div class="form-group">
            <label class="form-label">Supplier / Order Notes</label>
            <input type="text" id="mo-notes" class="form-control" placeholder="e.g. Bill promised by Hafeez Center Hub">
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="closeMarkOrderedModal()">Cancel</button>
            <button type="submit" class="btn btn-success" style="font-weight:bold;">Save Order Tracking</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: Edit Variant Alert Level -->
    <div id="edit-level-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:20000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:460px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:800; color:var(--text);">🔔 Configure Item Alert Level</h3>
          <button type="button" onclick="closeEditLevelModal()" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form method="POST" action="/api/alerts/set-level">
          <input type="hidden" name="variant_id" id="el-variant-id">
          <p style="font-size:13px; margin-bottom:12px;">Item: <strong id="el-item-name" style="color:#38bdf8;"></strong></p>
          
          <div class="form-group">
            <label class="form-label">Custom Low-Stock Alert Threshold</label>
            <div style="display:flex; gap:6px; align-items:center;">
              <input type="number" name="level" id="el-level-input" class="form-control" placeholder="Blank for Category Default" style="font-size:14px; font-weight:bold;">
              <div style="display:flex; gap:4px;">
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('el-level-input').value=1">1</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('el-level-input').value=2">2</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('el-level-input').value=3">3</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('el-level-input').value=5">5</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('el-level-input').value=10">10</button>
              </div>
            </div>
            <small style="color:#94a3b8;">Leave empty to inherit category default automatically.</small>
          </div>

          <div class="form-group">
            <label class="form-label">Default Reorder Quantity</label>
            <input type="number" name="reorder_qty" id="el-reorder-input" class="form-control" placeholder="e.g. 10">
          </div>

          <div class="form-group" style="margin-top:10px;">
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" name="alert_off" id="el-off-input" value="1">
              <span>🔕 Don't Alert for this item (Turn Off Alerts)</span>
            </label>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:18px;">
            <button type="button" class="btn btn-secondary" onclick="closeEditLevelModal()">Cancel</button>
            <button type="submit" class="btn btn-primary" style="font-weight:bold;">Save Alert Config</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: Bulk Set Alert Level -->
    <div id="bulk-level-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:20000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:460px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:800; color:var(--text);">⚡ Bulk Set Alert Levels</h3>
          <button type="button" onclick="closeBulkLevelModal()" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form onsubmit="submitBulkSetLevel(event)">
          <p style="font-size:13px; margin-bottom:12px;">Applying to <strong id="bulk-selected-count" style="color:#38bdf8;">0</strong> selected item(s).</p>
          
          <div class="form-group">
            <label class="form-label">New Alert Threshold</label>
            <div style="display:flex; gap:6px; align-items:center;">
              <input type="number" id="bulk-level-input" class="form-control" placeholder="Leave empty for category default">
              <div style="display:flex; gap:4px;">
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('bulk-level-input').value=1">1</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('bulk-level-input').value=2">2</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('bulk-level-input').value=3">3</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('bulk-level-input').value=5">5</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('bulk-level-input').value=10">10</button>
              </div>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Reorder Suggestion Quantity</label>
            <input type="number" id="bulk-reorder-input" class="form-control" placeholder="e.g. 10">
          </div>

          <div class="form-group" style="margin-top:10px;">
            <label style="display:flex; align-items:center; gap:8px; font-size:13px; cursor:pointer;">
              <input type="checkbox" id="bulk-off-input" value="1">
              <span>🔕 Mute / Turn Off Alerts for selected items</span>
            </label>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:18px;">
            <button type="button" class="btn btn-secondary" onclick="closeBulkLevelModal()">Cancel</button>
            <button type="submit" class="btn btn-success" style="font-weight:bold;">Apply Bulk Update</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function filterAlertsTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.alert-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}

      function toggleSelectAllAlerts(el) {{
        document.querySelectorAll('.alert-check').forEach(c => c.checked = el.checked);
      }}

      function getSelectedVariantIds() {{
        const ids = [];
        document.querySelectorAll('.alert-check:checked').forEach(c => ids.push(parseInt(c.value)));
        return ids;
      }}

      function openMarkOrderedModal(vid, name, suggested) {{
        document.getElementById('mo-variant-id').value = vid;
        document.getElementById('mo-item-name').innerText = name;
        document.getElementById('mo-qty').value = suggested || 10;
        document.getElementById('mark-ordered-modal').style.display = 'flex';
      }}

      function closeMarkOrderedModal() {{
        document.getElementById('mark-ordered-modal').style.display = 'none';
      }}

      function submitMarkOrdered(e) {{
        e.preventDefault();
        const vid = document.getElementById('mo-variant-id').value;
        const qty = document.getElementById('mo-qty').value;
        const dt = document.getElementById('mo-date').value;
        const notes = document.getElementById('mo-notes').value;
        
        const fd = new FormData();
        fd.append('variant_id', vid);
        fd.append('qty', qty);
        fd.append('expected_date', dt);
        fd.append('notes', notes);

        fetch('/api/alerts/mark-ordered', {{ method: 'POST', body: fd }})
          .then(r => r.json())
          .then(res => {{
            if (res.success) window.location.reload();
            else alert('Error: ' + res.error);
          }});
      }}

      function openEditLevelModal(vid, name, level, reorder, isOff) {{
        document.getElementById('el-variant-id').value = vid;
        document.getElementById('el-item-name').innerText = name;
        document.getElementById('el-level-input').value = level;
        document.getElementById('el-reorder-input').value = reorder;
        document.getElementById('el-off-input').checked = (isOff === 1);
        document.getElementById('edit-level-modal').style.display = 'flex';
      }}

      function closeEditLevelModal() {{
        document.getElementById('edit-level-modal').style.display = 'none';
      }}

      function openBulkLevelModal() {{
        const ids = getSelectedVariantIds();
        if (!ids.length) {{ alert('Please select at least 1 item using checkboxes.'); return; }}
        document.getElementById('bulk-selected-count').innerText = ids.length;
        document.getElementById('bulk-level-modal').style.display = 'flex';
      }}

      function closeBulkLevelModal() {{
        document.getElementById('bulk-level-modal').style.display = 'none';
      }}

      function submitBulkSetLevel(e) {{
        e.preventDefault();
        const ids = getSelectedVariantIds();
        const levVal = document.getElementById('bulk-level-input').value.trim();
        const reorderVal = document.getElementById('bulk-reorder-input').value.trim();
        const isOff = document.getElementById('bulk-off-input').checked ? 1 : 0;

        const payload = {{
          variant_ids: ids,
          level: levVal ? parseInt(levVal) : null,
          reorder_qty: reorderVal ? parseInt(reorderVal) : null,
          alert_off: isOff
        }};

        fetch('/api/alerts/bulk-set', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }})
        .then(r => r.json())
        .then(res => {{
          if (res.success) window.location.reload();
          else alert('Bulk update error');
        }});
      }}

      function openSnoozePrompt(vid) {{
        const days = prompt('Snooze this alert for how many days? (e.g. 1, 3, 7)', '3');
        if (!days) return;
        const fd = new FormData();
        fd.append('variant_id', vid);
        fd.append('days', days);

        fetch('/api/alerts/snooze', {{ method: 'POST', body: fd }})
          .then(r => r.json())
          .then(res => {{
            if (res.success) window.location.reload();
            else alert('Error snoozing alert');
          }});
      }}
    </script>
    """
    return layout("Low-Stock Alerts & Reorder Advice", content, "low_stock", user)

@app.route("/inventory/low-stock/export.csv")
def low_stock_export_csv():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")

    rows = db.query_all("""
        SELECT v.*, p.name AS model_name, p.brand, p.category, p.item_type,
               s.state, s.snoozed_until, s.on_order_qty, s.on_order_date
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN stock_alert_state s ON v.id = s.variant_id
        WHERE v.is_archived = 0 AND p.is_archived = 0
        ORDER BY CASE WHEN s.state = 'OUT' THEN 0 WHEN s.state = 'LOW' THEN 1 ELSE 2 END ASC, p.brand ASC, p.name ASC
    """)

    output = io.StringIO()
    # Excel-compatible UTF-8 BOM
    output.write("\ufeff")
    writer = csv.writer(output)

    header = ["Variant ID", "Brand", "Model Name", "Category", "Item Type", "Specs", "Barcode", "Current Stock", "Alert Level", "Inherited From", "Status", "On Order Qty", "Days Left", "Suggested Reorder Qty"]
    if is_admin:
        header.extend(["Last Supplier", "Last Unit Cost (Rs)"])
    writer.writerow(header)

    for r in rows:
        cfg = alert_engine.get_effective_alert_config(r, r)
        stock = alert_engine.compute_variant_stock(None, r["id"], r["item_type"])
        reorder_info = alert_engine.get_reorder_intelligence(r["id"]) if is_admin else None

        st = "OFF" if cfg["alert_off"] else ("OUT" if stock == 0 else ("LOW" if stock <= cfg["effective_level"] else "OK"))
        specs = f"{r['ram']} {r['storage']} {r['color']}".strip()

        row_data = [
            r["id"], r["brand"], r["model_name"], r["category"], r["item_type"], specs, r["barcode"] or "",
            stock, cfg["effective_level"], cfg["inherited_from"], st, r["on_order_qty"] or 0,
            reorder_info["days_stock_left"] if reorder_info else "",
            reorder_info["suggested_reorder_qty"] if reorder_info else (cfg["reorder_qty"] or 10)
        ]
        if is_admin:
            row_data.extend([
                reorder_info["last_supplier_name"] if reorder_info else "",
                reorder_info["last_cost"] if reorder_info else 0
            ])
        writer.writerow(row_data)

    csv_data = output.getvalue()
    response.content_type = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="low_stock_reorder.csv"'
    return csv_data

@app.route("/print/reorder-sheet")
def print_reorder_sheet():
    user = require_login()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = db.query_all("""
        SELECT v.*, p.name AS model_name, p.brand, p.category, p.item_type,
               s.state, s.snoozed_until, s.on_order_qty, s.on_order_date
        FROM variants v
        JOIN products p ON v.product_id = p.id
        LEFT JOIN stock_alert_state s ON v.id = s.variant_id
        WHERE v.is_archived = 0 AND p.is_archived = 0
        ORDER BY CASE WHEN s.state = 'OUT' THEN 0 WHEN s.state = 'LOW' THEN 1 ELSE 2 END ASC, p.brand ASC, p.name ASC
    """)

    urgent_items = []
    for r in rows:
        cfg = alert_engine.get_effective_alert_config(r, r)
        stock = alert_engine.compute_variant_stock(None, r["id"], r["item_type"])
        st = "OFF" if cfg["alert_off"] else ("OUT" if stock == 0 else ("LOW" if stock <= cfg["effective_level"] else "OK"))

        if st in ("OUT", "LOW"):
            reorder_info = alert_engine.get_reorder_intelligence(r["id"])
            urgent_items.append({
                "variant_id": r["id"],
                "brand": r["brand"],
                "model_name": r["model_name"],
                "category": r["category"],
                "specs": f"{r['ram']} {r['storage']} {r['color']}".strip(),
                "current_stock": stock,
                "effective_level": cfg["effective_level"],
                "state": st,
                "suggested_reorder_qty": reorder_info["suggested_reorder_qty"] if reorder_info else (cfg["reorder_qty"] or 10),
                "last_supplier_name": reorder_info["last_supplier_name"] if reorder_info else "",
                "last_supplier_phone": reorder_info["last_supplier_phone"] if reorder_info else "",
                "last_cost": reorder_info["last_cost"] if reorder_info else (r["wholesale_price"] or 0)
            })

    return printing.render_a4_reorder_sheet(urgent_items)

@app.route("/api/alerts/snooze", method="POST")
def api_alerts_snooze():
    user = require_admin()
    vid = int(request.forms.get("variant_id", 0))
    days = int(request.forms.get("days", 1))
    return alert_engine.snooze_alert(vid, days, user_id=user["id"], username=user["username"])

@app.route("/api/alerts/cancel-snooze", method="POST")
def api_alerts_cancel_snooze():
    user = require_admin()
    vid = int(request.forms.get("variant_id", 0))
    return alert_engine.cancel_snooze(vid, user_id=user["id"], username=user["username"])

@app.route("/api/alerts/mark-ordered", method="POST")
def api_alerts_mark_ordered():
    user = require_admin()
    vid = int(request.forms.get("variant_id", 0))
    qty = int(request.forms.get("qty", 1))
    date_str = request.forms.get("expected_date", "")
    notes = request.forms.get("notes", "")
    return alert_engine.mark_as_ordered(vid, qty, date_str, notes, user_id=user["id"], username=user["username"])

@app.route("/api/alerts/bulk-set", method="POST")
def api_alerts_bulk_set():
    user = require_admin()
    data = request.json or {}
    vids = data.get("variant_ids", [])
    lev = data.get("level")
    reorder = data.get("reorder_qty")
    alert_off = data.get("alert_off", 0)
    return alert_engine.bulk_set_alert_level(vids, level=lev, reorder_qty=reorder, alert_off=alert_off, user_id=user["id"], username=user["username"])

@app.route("/api/alerts/set-level", method="POST")
def api_alerts_set_single_level():
    user = require_admin()
    vid = int(request.forms.get("variant_id", 0))
    lev_val = request.forms.get("level", "").strip()
    lev = int(lev_val) if lev_val else None
    reorder_val = request.forms.get("reorder_qty", "").strip()
    reorder = int(reorder_val) if reorder_val else None
    alert_off = int(request.forms.get("alert_off", 0))
    alert_engine.bulk_set_alert_level([vid], level=lev, reorder_qty=reorder, alert_off=alert_off, user_id=user["id"], username=user["username"])
    return redirect("/inventory/low-stock")

# ═══════════════════════════════════════════════════════════
# PURCHASES & SUPPLIER LEDGER
# ═══════════════════════════════════════════════════════════

@app.route("/purchasing")
def purchasing_screen():
    user = require_admin()
    suppliers = purchasing.list_suppliers()
    purchases = purchasing.list_purchases(limit=30)
    variants = db.query_all("""
        SELECT v.id, v.color, v.ram, v.storage, p.name AS product_name, p.brand, p.item_type
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.is_archived = 0
        ORDER BY p.brand ASC, p.name ASC
    """)

    sup_options = "".join(f'<option value="{s["id"]}">{s["name"]} ({s["phone"]}) - Bal: Rs. {s["balance"]:,.0f}</option>' for s in suppliers)
    var_options = "".join(f'<option value="{v["id"]}">{v["brand"]} {v["product_name"]} ({v["ram"]}/{v["storage"]} {v["color"]}) [{v["item_type"]}]</option>' for v in variants)

    sup_table_rows = ""
    for s in suppliers:
        s_corp = f"{s['name'].lower()} {s['phone']} {(s['company'] or '').lower()}"
        sup_table_rows += f"""
        <tr class="sup-row" data-search="{s_corp}">
          <td><strong>{s['name']}</strong><br><small style="color:#94a3b8;">{s['company'] or ''}</small></td>
          <td>{s['phone']}</td>
          <td style='color:#f87171; font-weight:bold;'>Rs. {s['balance']:,.0f}</td>
          <td><button class='btn btn-sm btn-secondary' onclick="promptPaySupplier({s['id']}, '{s['name']}')">Pay</button></td>
        </tr>
        """

    purch_rows = ""
    for p in purchases:
        purch_rows += f"""
        <tr>
          <td><strong>{p['invoice_no']}</strong></td>
          <td>{p['purchase_date']}</td>
          <td>{p['supplier_name']}</td>
          <td style="font-weight:bold;">Rs. {p['total_amount']:,.0f}</td>
          <td style="color:#34d399;">Rs. {p['paid_amount']:,.0f}</td>
          <td style="color:#f87171;">Rs. {p['balance_amount']:,.0f}</td>
        </tr>
        """

    content = f"""
    <div class="grid-2">
      <!-- Fast Receiving Card -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📥 Fast Inward Receiving (Bulk Phone IMEI / Accessories)</div>
          <button type="button" class="btn btn-sm btn-primary" onclick="QuickAdd.open('supplier', {{ triggerSelect: document.getElementById('purch-supplier-select') }})">+ Add Supplier</button>
        </div>
        <form method="POST" action="/purchasing/receive" id="purch-receive-form">
          <div class="form-group">
            <label class="form-label">Select Supplier</label>
            <select name="supplier_id" id="purch-supplier-select" class="form-control smart-select" data-entity-name="Supplier" data-quickadd="supplier" required>
              {sup_options}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Variant to Receive</label>
            <select name="variant_id" id="purch-variant-select" class="form-control smart-select" data-entity-name="Model Variant" data-quickadd="product_model" required>
              {var_options}
            </select>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 8px;">
            <div class="form-group">
              <label class="form-label">Unit Cost Price (Rs.)</label>
              <input type="number" name="unit_cost" class="form-control" placeholder="0" required>
            </div>
            <div class="form-group">
              <label class="form-label">Paid Amount (Rs.)</label>
              <input type="number" name="paid_amount" class="form-control" value="0">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Phone IMEIs (Scan box sticker — 1 IMEI per line)</label>
            <textarea name="imei_list" id="purch-imei-list" class="form-control" rows="5" placeholder="Scan phone box barcode/IMEI sticker here directly..."></textarea>
            <small style="color:#94a3b8;">Scans from your USB scanner automatically paste here one per line.</small>
          </div>

          <div class="form-group">
            <label class="form-label">Accessory Quantity (Only if receiving accessories)</label>
            <input type="number" name="qty" class="form-control" value="1">
          </div>

          <button type="submit" class="btn btn-success" style="width: 100%; padding: 12px; font-weight: bold; font-size:14px;">
            Receive Goods into Inventory
          </button>
        </form>
      </div>

      <!-- Suppliers & Balances -->
      <div>
        <div class="card" style="margin-bottom:12px;">
          <div class="card-header">
            <div class="card-title">🏢 Supplier Ledgers & Balances</div>
            <input type="text" placeholder="🔍 Filter suppliers..." class="form-control" style="width:160px; padding:4px 8px; font-size:12px;" oninput="filterSuppliersTable(this.value)">
          </div>
          <div class="table-responsive" style="max-height:280px; overflow-y:auto;">
            <table class="data-table" id="suppliers-table">
              <thead>
                <tr><th>Supplier</th><th>Phone</th><th>Outstanding Balance</th><th>Action</th></tr>
              </thead>
              <tbody>
                {sup_table_rows or '<tr><td colspan="4" style="text-align:center; color:#888;">No suppliers found</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-title" style="margin-bottom:8px;">Recent Purchase Invoices</div>
          <div class="table-responsive" style="max-height:240px; overflow-y:auto;">
            <table class="data-table">
              <thead>
                <tr><th>Bill #</th><th>Date</th><th>Supplier</th><th>Total</th><th>Paid</th><th>Due</th></tr>
              </thead>
              <tbody>
                {purch_rows or '<tr><td colspan="6" style="text-align:center; color:#888;">No purchases yet</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <script>
      // Universal Scanner Routing: Auto-paste scanned IMEI into purchasing list
      window.purchaseAddScannedImei = function(code) {{
        const area = document.getElementById('purch-imei-list');
        if (area) {{
          const clean = code.trim();
          if (clean) {{
            area.value = (area.value ? area.value.trim() + '\\n' : '') + clean;
            ScannerEngine.playSuccessBeep();
            ScannerEngine.flashScreen('rgba(16, 185, 129, 0.4)');
            ScannerEngine.showToast('IMEI Added: ' + clean, true);
          }}
        }}
      }};

      function filterSuppliersTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.sup-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}

      function promptPaySupplier(sid, name) {{
        var amt = prompt('Enter payment amount to ' + name + ' (Rs.):');
        if (amt && parseFloat(amt) > 0) {{
          window.location.href = '/purchasing/pay-supplier?supplier_id=' + sid + '&amount=' + amt;
        }}
      }}
    </script>
    """
    return layout("Purchases", content, "purchasing", user)

@app.route("/purchasing/supplier/<sid:int>")
@app.route("/purchasing/supplier/<sid:int>/")
def purchasing_supplier_ledger_screen(sid):
    user = require_admin()
    s = db.query_one("SELECT * FROM suppliers WHERE id = ?", (sid,))
    if not s:
        return redirect("/purchasing")
    
    purchases = db.query_all("SELECT * FROM purchases WHERE supplier_id = ? ORDER BY id DESC LIMIT 20", (sid,))
    payments = db.query_all("SELECT * FROM supplier_ledger WHERE supplier_id = ? ORDER BY id DESC LIMIT 20", (sid,))

    purch_rows = ""
    for p in purchases:
        purch_rows += f"""
        <tr>
          <td><strong>{p['invoice_no']}</strong></td>
          <td>{p['purchase_date']}</td>
          <td style="font-weight:bold;">Rs. {p['total_amount']:,.0f}</td>
          <td style="color:#34d399;">Rs. {p['paid_amount']:,.0f}</td>
          <td style="color:#f87171;">Rs. {p['balance_amount']:,.0f}</td>
        </tr>
        """

    pay_rows = ""
    for pay in payments:
        pay_rows += f"""
        <tr>
          <td>{pay['timestamp'][:16]}</td>
          <td>{pay['transaction_type']}</td>
          <td>Rs. {pay['amount']:,.0f}</td>
          <td>{pay['payment_method']}</td>
          <td style="font-weight:bold;">Rs. {pay['balance_after']:,.0f}</td>
        </tr>
        """

    content = f"""
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="font-size: 12px; color: var(--text-muted);"><a href="/purchasing" style="color: #60a5fa; text-decoration: none;">&larr; Back to All Suppliers & Inward</a></div>
        <h1 style="font-size: 22px; font-weight: 800; margin-top: 4px;">🏢 {s['name']} — Supplier Ledger</h1>
        <div style="font-size: 13px; color: #94a3b8;">Company: <strong>{s['company'] or 'N/A'}</strong> &bull; Phone: {s['phone']} &bull; Address: {s['address'] or 'N/A'}</div>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn btn-secondary btn-sm" onclick="promptPaySupplier({s['id']}, '{s['name']}')">Pay Supplier</button>
        <a href="/purchasing" class="btn btn-secondary btn-sm">All Purchases</a>
      </div>
    </div>

    <div class="grid-3" style="margin-bottom: 16px;">
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">OUTSTANDING PAYABLE BALANCE</div>
        <div style="font-size: 24px; font-weight: 800; color: #f87171; margin-top: 4px;">
          Rs. {s['balance']:,.0f}
        </div>
      </div>
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">PURCHASE ORDERS</div>
        <div style="font-size: 24px; font-weight: 800; color: #38bdf8; margin-top: 4px;">
          {len(purchases)} Bills
        </div>
      </div>
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">LEDGER ENTRIES</div>
        <div style="font-size: 24px; font-weight: 800; color: #a78bfa; margin-top: 4px;">
          {len(payments)} Records
        </div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header"><div class="card-title">📦 Purchase Bills ({len(purchases)})</div></div>
        <div class="table-responsive">
          <table class="data-table">
            <thead><tr><th>Bill #</th><th>Date</th><th>Total</th><th>Paid</th><th>Due</th></tr></thead>
            <tbody>
              {purch_rows or '<tr><td colspan="5" style="text-align:center; color:#888;">No bills recorded</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><div class="card-title">💵 Payment Ledger ({len(payments)})</div></div>
        <div class="table-responsive">
          <table class="data-table">
            <thead><tr><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
            <tbody>
              {pay_rows or '<tr><td colspan="5" style="text-align:center; color:#888;">No ledger entries</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      function promptPaySupplier(sid, name) {{
        var amt = prompt('Enter payment amount to ' + name + ' (Rs.):');
        if (amt && parseFloat(amt) > 0) {{
          window.location.href = '/purchasing/pay-supplier?supplier_id=' + sid + '&amount=' + amt;
        }}
      }}
    </script>
    """
    return layout(f"{s['name']} — Supplier Ledger", content, "purchasing", user)

@app.route("/purchasing/create-supplier", method="POST")
def create_supplier_route():
    user = require_admin()
    name = request.forms.get("name", "").strip()
    phone = request.forms.get("phone", "").strip()
    comp = request.forms.get("company", "").strip()
    purchasing.create_supplier(name, phone=phone, company=comp, user_id=user["id"], username=user["username"])
    return redirect("/purchasing")

@app.route("/purchasing/receive", method="POST")
def receive_goods_route():
    user = require_admin()
    sid = int(request.forms.get("supplier_id"))
    vid = int(request.forms.get("variant_id"))
    cost = float(request.forms.get("unit_cost", 0))
    paid = float(request.forms.get("paid_amount", 0))
    imei_text = request.forms.get("imei_list", "").strip()
    qty = int(request.forms.get("qty", 1))

    v = db.query_one("SELECT p.item_type FROM variants v JOIN products p ON v.product_id = p.id WHERE v.id = ?", (vid,))
    
    if v and v["item_type"] == "PHONE":
        imeis = []
        for line in imei_text.splitlines():
            line = line.strip()
            if line:
                imeis.append({"imei1": line, "condition": "NEW_BOX_PACK", "pta_status": "PTA_APPROVED", "battery_health": 100})
        items = [{"item_type": "PHONE", "variant_id": vid, "unit_cost": cost, "imeis": imeis}]
    else:
        items = [{"item_type": "ACCESSORY", "variant_id": vid, "unit_cost": cost, "qty": qty}]

    purchasing.create_purchase(sid, items, paid_amount=paid, user_id=user["id"], username=user["username"])
    return redirect("/purchasing")

@app.route("/purchasing/pay-supplier")
def pay_supplier_route():
    user = require_admin()
    sid = safe_int(request.query.get("supplier_id"))
    if not sid:
        return redirect("/purchasing")
    amt = float(request.query.get("amount", 0))
    pm = request.query.get("payment_method") or request.query.get("account") or "Cash Drawer"
    res = purchasing.record_supplier_payment(sid, amt, payment_method=pm, user_id=user["id"], username=user["username"])
    if res["success"]:
        return redirect(f"/print/supplier-payment/{res['ledger_id']}")
    return redirect("/purchasing")

# ═══════════════════════════════════════════════════════════
# RETURNS & TRADE-IN / BUYBACK
# ═══════════════════════════════════════════════════════════

@app.route("/returns")
def returns_screen():
    user = require_login()
    recent_returns = db.query_all("SELECT * FROM returns ORDER BY id DESC LIMIT 40")
    recent_trade_ins = db.query_all("SELECT * FROM trade_ins ORDER BY id DESC LIMIT 40")

    reason_items = lookups.get_lookup_list("return_reason")
    reason_opts = "".join(f'<option value="{r["label"]}">{r["label"]}</option>' for r in reason_items)

    condition_items = lookups.get_lookup_list("trade_in_condition")
    condition_opts = "".join(f'<option value="{c["label"]}">{c["label"]}</option>' for c in condition_items)

    brand_items = lookups.get_lookup_list("brand")
    brand_opts = "".join(f'<option value="{b["label"]}">{b["label"]}</option>' for b in brand_items)

    color_items = lookups.get_lookup_list("color")
    color_opts = "".join(f'<option value="{c["label"]}">{c["label"]}</option>' for c in color_items)

    pta_items = lookups.get_lookup_list("pta_status")
    pta_opts = "".join(f'<option value="{p["label"]}">{p["label"]}</option>' for p in pta_items)

    # Returns rows
    ret_rows = ""
    for r in recent_returns:
        ret_rows += f"""
        <tr class="return-row" data-search="{r['return_no'].lower()} {r['invoice_no'].lower()} {(r['customer_name'] or '').lower()} {r['refund_type'].lower()} {r['reason'].lower()}">
          <td><a href="/print/return/{r['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">{r['return_no']}</a></td>
          <td>{r['invoice_no']}</td>
          <td>{r['customer_name'] or 'Walk-in'}</td>
          <td><span class="badge badge-info">{r['refund_type']}</span></td>
          <td>{r['reason']}</td>
          <td style="color:#f87171; font-weight:bold;">Rs. {r['refund_amount']:,.0f}</td>
          <td>{r['created_at'][:16]}</td>
          <td><a href="/print/return/{r['id']}" target="_blank" class="btn btn-sm btn-secondary">Print</a></td>
        </tr>
        """

    # Trade-in rows
    trade_rows = ""
    for t in recent_trade_ins:
        trade_rows += f"""
        <tr class="trade-row" data-search="{t['trade_in_no'].lower()} {t['customer_name'].lower()} {t['brand'].lower()} {t['model'].lower()} {t['imei1'].lower()} {t['condition'].lower()}">
          <td><a href="/print/trade-in/{t['id']}" target="_blank" style="color:#c084fc; font-weight:bold;">{t['trade_in_no']}</a></td>
          <td><strong>{t['customer_name']}</strong><br><small style="color:#94a3b8;">{t['customer_phone']}</small></td>
          <td>{t['brand']} {t['model']}</td>
          <td><code>{t['imei1']}</code></td>
          <td><span class="badge badge-warning">{t['condition']}</span> ({t['battery_health']}%)</td>
          <td style="color:#34d399; font-weight:bold;">Rs. {t['purchase_price']:,.0f}</td>
          <td>{t['created_at'][:16]}</td>
          <td><a href="/print/trade-in/{t['id']}" target="_blank" class="btn btn-sm btn-secondary">Agreement</a></td>
        </tr>
        """

    content = f"""
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <div style="display:flex; gap:8px;">
        <button type="button" class="btn btn-primary" id="tab-btn-returns" onclick="switchReturnsTab('returns')">🔄 Sale Returns & Exchange</button>
        <button type="button" class="btn btn-secondary" id="tab-btn-tradein" onclick="switchReturnsTab('tradein')">🔁 Device Buyback / Trade-In</button>
      </div>
      <div>
        <span style="font-size:12px; color:var(--text-muted);">Quick Action: Scan Invoice or IMEI anywhere</span>
      </div>
    </div>

    <!-- TAB 1: SALE RETURNS & EXCHANGE -->
    <div id="section-returns-tab">
      <div class="card" style="margin-bottom:16px; border:2px solid var(--primary);">
        <div class="card-title" style="margin-bottom:6px;">🔍 Lookup Sale to Return / Exchange</div>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:10px;">
          Agar invoice number yaad na ho, to Customer Name, Phone Number, Item Name (e.g. <b>Cable, Charger</b>), ya Phone IMEI likh kar search karein:
        </p>
        <div style="display:flex; gap:8px;">
          <input type="text" id="ret-search-input" class="form-control" placeholder="Search by Invoice #, Customer Name, Phone #, Item Name (e.g. Cable), or IMEI..." style="font-size:14px; font-weight:bold;" autofocus>
          <button type="button" class="btn btn-primary" onclick="lookupSaleForReturn()">🔍 Search Sale</button>
        </div>
      </div>

      <!-- Multiple Matches Found Selection Box -->
      <div id="ret-multi-match-card" class="card" style="display:none; margin-bottom:16px; background:rgba(30,41,59,0.95); border:1px solid #38bdf8;">
        <div class="card-header" style="border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:8px; margin-bottom:10px;">
          <div style="font-weight:bold; color:#38bdf8; font-size:14px;">📋 Multiple Sales Found — Select Sale to Return:</div>
          <span id="ret-multi-count-badge" class="badge badge-info">0 Sales</span>
        </div>
        <div class="table-responsive">
          <table class="data-table" id="ret-multi-table">
            <thead>
              <tr>
                <th>Date & Time</th>
                <th>Invoice #</th>
                <th>Customer</th>
                <th>Items Sold</th>
                <th>Total (Rs.)</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="ret-multi-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Loaded Sale Details Box -->
      <div id="ret-sale-card" class="card" style="display:none; margin-bottom:16px; background:rgba(30,41,59,0.9); border:1px solid #3b82f6;">
        <form method="POST" action="/returns/process" onsubmit="return validateReturnSubmit(this)">
          <input type="hidden" name="sale_id" id="ret-sale-id" value="">
          <div class="card-header" style="margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid var(--card-border);">
            <div>
              <h3 style="font-size:16px; font-weight:800; color:#38bdf8;" id="ret-disp-inv">Invoice #</h3>
              <p style="font-size:12px; color:var(--text-muted);" id="ret-disp-cust">Customer: Walk-in</p>
            </div>
            <div style="text-align:right;">
              <div style="font-size:16px; font-weight:bold; color:#34d399;" id="ret-disp-total">Rs. 0</div>
              <span class="badge badge-info" id="ret-disp-paymethod">CASH</span>
            </div>
          </div>

          <h4 style="font-size:13px; font-weight:bold; margin-bottom:8px;">Select Item(s) to Return:</h4>
          <div class="table-responsive" style="margin-bottom:14px;">
            <table class="data-table">
              <thead>
                <tr>
                  <th style="width:40px;"><input type="checkbox" id="ret-select-all" checked onchange="toggleSelectAllReturns(this)" title="Toggle Select All"></th>
                  <th>Item & Specifications</th>
                  <th>IMEI / Serial</th>
                  <th>Unit Price</th>
                  <th>Qty to Return</th>
                </tr>
              </thead>
              <tbody id="ret-items-tbody"></tbody>
            </table>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px; margin-top:12px;">
            <div class="form-group">
              <label class="form-label">Return Reason</label>
              <select name="reason" class="form-control smart-select" data-list-key="return_reason" data-entity-name="Return Reason" data-quickadd="lookup">
                {reason_opts}
              </select>
            </div>

            <div class="form-group">
              <label class="form-label">Stock Action</label>
              <select name="action" class="form-control">
                <option value="RESTOCK">Restock (Put back in Inventory)</option>
                <option value="DEFECTIVE">Defective (Mark Faulty / Supplier Claim)</option>
              </select>
            </div>

            <div class="form-group">
              <label class="form-label">Refund Method</label>
              <select name="refund_type" class="form-control">
                <option value="CASH">💵 Cash Refund (Drawer Cash)</option>
                <option value="CREDIT_NOTE">📝 Customer Khata Credit Note</option>
                <option value="EXCHANGE">🔄 Exchange / Replacement</option>
              </select>
            </div>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('ret-sale-card').style.display='none'">Cancel</button>
            <button type="submit" class="btn btn-danger" style="font-weight:bold; padding:10px 20px;">🔄 Confirm Return & Print Voucher</button>
          </div>
        </form>
      </div>

      <!-- Recent Returns Table -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📜 Recent Sale Returns History ({len(recent_returns)})</div>
          <input type="text" placeholder="🔍 Live filter returns..." class="form-control" style="width:220px; padding:6px 10px; font-size:12px;" oninput="filterReturnsTable(this.value)">
        </div>
        <div class="table-responsive">
          <table class="data-table" id="returns-table">
            <thead>
              <tr>
                <th>Voucher #</th>
                <th>Original Invoice</th>
                <th>Customer</th>
                <th>Refund Type</th>
                <th>Reason</th>
                <th>Refund Amount</th>
                <th>Date</th>
                <th>Receipt</th>
              </tr>
            </thead>
            <tbody>
              {ret_rows or '<tr><td colspan="8" style="text-align:center; color:#888;">No sale returns recorded yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 2: DEVICE BUYBACK / TRADE-IN -->
    <div id="section-tradein-tab" style="display:none;">
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title" style="margin-bottom:12px;">🔁 Record Device Buyback / Customer Trade-In</div>
        <form method="POST" action="/returns/trade-in">
          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Customer Name</label>
              <input type="text" name="customer_name" class="form-control" placeholder="Full name of seller" required>
            </div>
            <div class="form-group">
              <label class="form-label">Customer Phone</label>
              <input type="text" name="customer_phone" class="form-control" placeholder="03001234567" required>
            </div>
            <div class="form-group">
              <label class="form-label">Customer CNIC (ID Card)</label>
              <input type="text" name="customer_cnic" class="form-control" placeholder="35202-xxxxxxx-x" required>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Brand</label>
              <select name="brand" class="form-control smart-select" data-list-key="brand" data-entity-name="Brand" data-quickadd="lookup" required>
                {brand_opts}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Model Name</label>
              <input type="text" name="model" class="form-control" placeholder="e.g. iPhone 13, A15, Spark 10" required>
            </div>
            <div class="form-group">
              <label class="form-label">Color</label>
              <select name="color" class="form-control smart-select" data-list-key="color" data-entity-name="Color" data-quickadd="lookup">
                {color_opts}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Condition</label>
              <select name="condition" class="form-control smart-select" data-list-key="trade_in_condition" data-entity-name="Condition" data-quickadd="lookup">
                {condition_opts}
              </select>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 2fr 1fr 1fr 1.5fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Device Primary IMEI (IMEI 1)</label>
              <input type="text" name="imei1" id="tradein-imei-input" class="form-control" placeholder="15-digit IMEI number" required>
            </div>
            <div class="form-group">
              <label class="form-label">Battery Health %</label>
              <input type="number" name="battery_health" class="form-control" value="85" min="1" max="100">
            </div>
            <div class="form-group">
              <label class="form-label">PTA Status</label>
              <select name="pta_status" class="form-control smart-select" data-list-key="pta_status" data-entity-name="PTA Status" data-quickadd="lookup">
                {pta_opts}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Agreed Purchase Price (Rs.)</label>
              <input type="number" name="purchase_price" class="form-control" style="font-size:16px; font-weight:bold; color:#34d399;" placeholder="Amount paid (Rs.)" required>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Condition Notes / Accessories Included</label>
            <input type="text" name="notes" class="form-control" placeholder="e.g. Original box + cable included, minor scratch on bezel">
          </div>

          <button type="submit" class="btn btn-success" style="width:100%; padding:14px; font-size:15px; font-weight:800; margin-top:8px;">
            🖨️ Purchase Device & Print Legal Agreement Voucher
          </button>
        </form>
      </div>

      <!-- Recent Trade-ins Table -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📜 Recent Buyback / Trade-In History ({len(recent_trade_ins)})</div>
          <input type="text" placeholder="🔍 Live filter buybacks..." class="form-control" style="width:220px; padding:6px 10px; font-size:12px;" oninput="filterTradeTable(this.value)">
        </div>
        <div class="table-responsive">
          <table class="data-table" id="tradeins-table">
            <thead>
              <tr>
                <th>Voucher #</th>
                <th>Seller Customer</th>
                <th>Device</th>
                <th>IMEI</th>
                <th>Condition</th>
                <th>Purchase Price</th>
                <th>Date</th>
                <th>Agreement</th>
              </tr>
            </thead>
            <tbody>
              {trade_rows or '<tr><td colspan="8" style="text-align:center; color:#888;">No device trade-ins recorded yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      function switchReturnsTab(tab) {{
        const btnRet = document.getElementById('tab-btn-returns');
        const btnTrd = document.getElementById('tab-btn-tradein');
        const secRet = document.getElementById('section-returns-tab');
        const secTrd = document.getElementById('section-tradein-tab');
        if (tab === 'returns') {{
          btnRet.className = 'btn btn-primary';
          btnTrd.className = 'btn btn-secondary';
          secRet.style.display = 'block';
          secTrd.style.display = 'none';
        }} else {{
          btnRet.className = 'btn btn-secondary';
          btnTrd.className = 'btn btn-primary';
          secRet.style.display = 'none';
          secTrd.style.display = 'block';
        }}
      }}

      async function lookupSaleForReturn() {{
        const q = document.getElementById('ret-search-input').value.trim();
        const multiCard = document.getElementById('ret-multi-match-card');
        const saleCard = document.getElementById('ret-sale-card');
        if (multiCard) multiCard.style.display = 'none';
        if (saleCard) saleCard.style.display = 'none';
        if (!q) return;

        try {{
          const res = await fetch('/api/sales/lookup?q=' + encodeURIComponent(q));
          const data = await res.json();
          if (!data.success) {{
            alert('Lookup Alert: ' + (data.error || 'Sale not found'));
            return;
          }}
          if (data.multiple) {{
            renderMultiSalesMatches(data.sales);
          }} else {{
            renderSingleSaleDetails(data.sale, data.items);
          }}
        }} catch (e) {{
          alert('Network/API error: ' + e.message);
        }}
      }}

      function renderMultiSalesMatches(sales) {{
        const multiCard = document.getElementById('ret-multi-match-card');
        const tbody = document.getElementById('ret-multi-tbody');
        const countBadge = document.getElementById('ret-multi-count-badge');
        if (!multiCard || !tbody) return;

        countBadge.innerText = sales.length + ' Sales Found';
        let rows = '';
        sales.forEach(s => {{
          const cust = (s.customer_name || 'Walk-in') + (s.customer_phone ? ' (' + s.customer_phone + ')' : '');
          rows += `
            <tr>
              <td>${{s.created_at ? s.created_at.substring(0, 16) : '-'}}</td>
              <td><strong style="color:#38bdf8;">${{s.invoice_no}}</strong></td>
              <td>${{cust}}</td>
              <td><small style="color:#cbd5e1;">${{s.items_summary || '-'}}</small></td>
              <td style="color:#34d399; font-weight:bold;">Rs. ${{Number(s.grand_total).toLocaleString()}}</td>
              <td>
                <button type="button" class="btn btn-xs btn-success font-weight-bold" onclick="loadSaleById(${{s.id}})">
                  ↩️ Select for Return
                </button>
              </td>
            </tr>
          `;
        }});
        tbody.innerHTML = rows;
        multiCard.style.display = 'block';
        multiCard.scrollIntoView({{ behavior: 'smooth' }});
      }}

      async function loadSaleById(sid) {{
        try {{
          const res = await fetch('/api/sales/details/' + sid);
          const data = await res.json();
          if (!data.success) {{
            alert('Failed to load sale: ' + (data.error || 'Not found'));
            return;
          }}
          const multiCard = document.getElementById('ret-multi-match-card');
          if (multiCard) multiCard.style.display = 'none';
          renderSingleSaleDetails(data.sale, data.items);
        }} catch (e) {{
          alert('Error loading sale details: ' + e.message);
        }}
      }}

      // RB3: Unified function for selecting a sale for return
      function selectSaleForReturn(sid) {{
        return loadSaleById(sid);
      }}
      window.selectSaleForReturn = selectSaleForReturn;
      window.loadSaleById = loadSaleById;

      function renderSingleSaleDetails(s, items) {{
        document.getElementById('ret-sale-id').value = s.id;
        document.getElementById('ret-disp-inv').innerText = 'Invoice #' + s.invoice_no + ' (' + s.created_at.substring(0, 16) + ')';
        document.getElementById('ret-disp-cust').innerText = 'Customer: ' + (s.customer_name || 'Walk-in') + (s.customer_phone ? ' (' + s.customer_phone + ')' : '');
        document.getElementById('ret-disp-total').innerText = 'Rs. ' + Number(s.grand_total).toLocaleString();
        document.getElementById('ret-disp-paymethod').innerText = s.payment_method;

        let rows = '';
        items.forEach(it => {{
          const spec = it.variant_details ? `<br><small style="color:#94a3b8;">${{it.variant_details}}</small>` : '';
          const imei = it.imei1 ? `<code>${{it.imei1}}${{it.imei2 ? ' / ' + it.imei2 : ''}}</code>` : '-';
          const disabled = it.is_returned ? 'disabled' : '';
          const badge = it.is_returned ? '<span class="badge badge-danger">Already Returned</span>' : '';
          const isChecked = !it.is_returned ? 'checked' : '';
          rows += `
            <tr>
              <td><input type="checkbox" name="sale_item_id" value="${{it.id}}" ${{disabled}} ${{isChecked}}></td>
              <td><strong>${{it.item_name}}</strong>${{spec}} ${{badge}}</td>
              <td>${{imei}}</td>
              <td>Rs. ${{Number(it.unit_price).toLocaleString()}}</td>
              <td><input type="number" name="qty_${{it.id}}" value="${{it.qty}}" min="1" max="${{it.qty}}" class="form-control" style="width:70px; padding:4px;" ${{disabled}}></td>
            </tr>
          `;
        }});
        document.getElementById('ret-items-tbody').innerHTML = rows;
        document.getElementById('ret-sale-card').style.display = 'block';
        document.getElementById('ret-sale-card').scrollIntoView({{ behavior: 'smooth' }});
      }}

      function toggleSelectAllReturns(master) {{
        document.querySelectorAll('#ret-items-tbody input[type="checkbox"][name="sale_item_id"]').forEach(cb => {{
          if (!cb.disabled) cb.checked = master.checked;
        }});
      }}

      function validateReturnSubmit(form) {{
        const checked = form.querySelectorAll('input[name="sale_item_id"]:checked');
        if (checked.length === 0) {{
          alert('⚠️ Please select at least one item checkbox to return.');
          return false;
        }}
        return confirm('Are you sure you want to process this return and restock selected item(s)?');
      }}

      window.addEventListener('DOMContentLoaded', function() {{
        const params = new URLSearchParams(window.location.search);
        const inv = params.get('invoice');
        if (inv) {{
          const inp = document.getElementById('ret-search-input');
          if (inp) {{
            inp.value = inv;
            lookupSaleForReturn();
          }}
        }}
      }});

      document.getElementById('ret-search-input').addEventListener('keydown', function(e) {{
        if (e.key === 'Enter') {{
          e.preventDefault();
          lookupSaleForReturn();
        }}
      }});

      function filterReturnsTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.return-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}

      function filterTradeTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.trade-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Returns & Trade-In", content, "returns", user)

@app.route("/api/sales/lookup")
def api_sales_lookup():
    user = require_login()
    q = request.query.get("q", "").strip()
    if not q:
        response.status = 400
        response.content_type = "application/json"
        return json.dumps({"success": False, "error": "Search query is required (Invoice #, Name, Phone, Item, or IMEI)"})

    # 1. Search sales table directly
    matching_sales = db.query_all("""
        SELECT s.*, 
          (SELECT GROUP_CONCAT(item_name, ', ') FROM sale_items WHERE sale_id = s.id) as items_summary
        FROM sales s 
        WHERE s.invoice_no = ? 
           OR s.invoice_no LIKE ? 
           OR s.customer_name LIKE ? 
           OR s.customer_phone LIKE ?
        ORDER BY s.id DESC
        LIMIT 30
    """, (q, f"%{q}%", f"%{q}%", f"%{q}%"))

    found_ids = {s["id"] for s in matching_sales}

    # 2. Search by sale_items (item name, IMEI 1, IMEI 2)
    item_sales = db.query_all("""
        SELECT DISTINCT s.*,
          (SELECT GROUP_CONCAT(item_name, ', ') FROM sale_items WHERE sale_id = s.id) as items_summary
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        WHERE si.item_name LIKE ? 
           OR si.imei1 = ? OR si.imei1 LIKE ? 
           OR (si.imei2 IS NOT NULL AND (si.imei2 = ? OR si.imei2 LIKE ?))
        ORDER BY s.id DESC
        LIMIT 30
    """, (f"%{q}%", q, f"%{q}%", q, f"%{q}%"))

    for s in item_sales:
        if s["id"] not in found_ids:
            matching_sales.append(s)
            found_ids.add(s["id"])

    response.content_type = "application/json"

    if not matching_sales:
        response.status = 404
        return json.dumps({"success": False, "error": f"No sale invoice found matching '{q}'"})

    if len(matching_sales) == 1:
        sale = matching_sales[0]
        items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale["id"],))
        return json.dumps({"success": True, "multiple": False, "sale": dict(sale), "items": items})

    # Multiple sales found
    results = []
    for s in matching_sales:
        results.append({
            "id": s["id"],
            "invoice_no": s["invoice_no"],
            "customer_name": s["customer_name"] or "Walk-in",
            "customer_phone": s["customer_phone"] or "",
            "grand_total": s["grand_total"],
            "created_at": s["created_at"],
            "items_summary": s.get("items_summary") or ""
        })
    return json.dumps({"success": True, "multiple": True, "sales": results})

@app.route("/api/sales/details/<sid:int>")
def api_sales_details(sid):
    user = require_login()
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sid,))
    if not sale:
        response.status = 404
        response.content_type = "application/json"
        return json.dumps({"success": False, "error": "Sale not found"})

    items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sid,))
    response.content_type = "application/json"
    return json.dumps({"success": True, "multiple": False, "sale": dict(sale), "items": items})

@app.route("/returns/process", method="POST")
def returns_process_route():
    user = require_login()
    sale_id = int(request.forms.get("sale_id", 0))
    sale_item_ids = request.forms.getall("sale_item_id")
    refund_type = request.forms.get("refund_type", "CASH")
    reason = request.forms.get("reason", "Customer Return")
    action = request.forms.get("action", "RESTOCK")

    if not sale_id or not sale_item_ids:
        return redirect("/returns")

    return_items_data = []
    for si_id in sale_item_ids:
        qty = int(request.forms.get(f"qty_{si_id}", 1))
        return_items_data.append({"sale_item_id": int(si_id), "qty": qty, "action": action})

    res = pos.process_return(sale_id, return_items_data, refund_type=refund_type, reason=reason, user_id=user["id"], username=user["username"])
    if res.get("success") and res.get("return_id"):
        return redirect(f"/print/return/{res['return_id']}")
    return redirect("/returns")

@app.route("/returns/trade-in", method="POST")
def returns_trade_in_route():
    user = require_perm("trade_in")
    cname = request.forms.get("customer_name", "").strip()
    cphone = request.forms.get("customer_phone", "").strip()
    cnic = request.forms.get("customer_cnic", "").strip()
    brand = request.forms.get("brand", "").strip()
    model = request.forms.get("model", "").strip()
    imei1 = request.forms.get("imei1", "").strip()
    condition = request.forms.get("condition", "USED").strip()
    battery_health = int(request.forms.get("battery_health", 85) or 85)
    price = float(request.forms.get("purchase_price", 0) or 0)
    notes = request.forms.get("notes", "").strip()

    res = pos.record_trade_in(cname, cphone, cnic, brand, model, imei1, condition=condition, battery_health=battery_health, purchase_price=price, notes=notes, user_id=user["id"], username=user["username"])
    if res.get("success") and res.get("trade_in_id"):
        return redirect(f"/print/trade-in/{res['trade_in_id']}")
    return redirect("/returns")

# ═══════════════════════════════════════════════════════════
# HARDWARE REPAIR WORKSHOP
# ═══════════════════════════════════════════════════════════

@app.route("/repairs")
def repairs_screen():
    user = require_perm("repair_jobs")
    jobs = services.list_repair_jobs(limit=50)

    brand_items = lookups.get_lookup_list("brand")
    brand_opts = "".join(f'<option value="{b["label"]}">{b["label"]}</option>' for b in brand_items)

    complaint_items = lookups.get_lookup_list("repair_complaint")
    complaint_opts = "".join(f'<option value="{c["label"]}">{c["label"]}</option>' for c in complaint_items)

    rows_html = ""
    for j in jobs:
        status_color = {
            "RECEIVED": "badge-info",
            "DIAGNOSING": "badge-warning",
            "WAITING_PARTS": "badge-purple",
            "IN_REPAIR": "badge-warning",
            "READY": "badge-success",
            "DELIVERED": "badge-success",
            "CANCELLED": "badge-danger"
        }.get(j['status'], "badge-secondary")

        search_corpus = f"{j['job_no'].lower()} {j['customer_name'].lower()} {j['customer_phone'].lower()} {j['brand'].lower()} {j['model'].lower()} {(j['imei'] or '').lower()} {j['complaint'].lower()} {j['status'].lower()}"

        rows_html += f"""
        <tr class="repair-row" data-search="{search_corpus}">
          <td><a href="/print/repair/{j['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">{j['job_no']}</a></td>
          <td>{j['created_at'][:10]}</td>
          <td><strong>{j['customer_name']}</strong><br><small style="color:#94a3b8;">{j['customer_phone']}</small></td>
          <td>{j['brand']} {j['model']}<br><small style="color:#888;">IMEI: {j['imei'] or 'N/A'}</small></td>
          <td><span style="font-size:11.5px; color:#cbd5e1;">{j['complaint'][:32]}</span></td>
          <td>Rs. {j['estimate']:,.0f}</td>
          <td><span class="badge {status_color}">{j['status']}</span></td>
          <td style="text-align:right;">
            <a href="/repairs/manage/{j['id']}" class="btn btn-sm btn-primary">Manage</a>
            <a href="/print/repair/{j['id']}" target="_blank" class="btn btn-sm btn-secondary">Print</a>
          </td>
        </tr>
        """

    content = f"""
    <div class="card">
      <div class="card-header">
        <div class="card-title">🔧 Hardware Repair Workshop ({len(jobs)} jobs)</div>
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" placeholder="🔍 Live filter jobs..." class="form-control" style="width:200px; padding:6px 10px; font-size:12px;" oninput="filterRepairsTable(this.value)">
          <button class="btn btn-success btn-sm" onclick="document.getElementById('new-job-modal').style.display='flex'">+ New Repair Job Card</button>
        </div>
      </div>

      <div class="table-responsive">
        <table class="data-table" id="repairs-table">
          <thead>
            <tr>
              <th>Ticket #</th>
              <th>Date</th>
              <th>Customer</th>
              <th>Device</th>
              <th>Fault Description</th>
              <th>Estimate</th>
              <th>Status</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows_html or '<tr><td colspan="8" style="text-align:center; color:#888;">No repair jobs found</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal: New Repair Job -->
    <div id="new-job-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:2000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:520px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <h3 style="font-size:17px; font-weight:800; color:var(--text);">Create Repair Job Card</h3>
          <button type="button" onclick="document.getElementById('new-job-modal').style.display='none'" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form method="POST" action="/repairs/create">
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group"><label class="form-label">Customer Name</label><input type="text" name="customer_name" class="form-control" placeholder="Ali Khan" required></div>
            <div class="form-group"><label class="form-label">Customer Phone</label><input type="text" name="customer_phone" class="form-control" placeholder="03001234567" required></div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Brand</label>
              <select name="brand" class="form-control smart-select" data-list-key="brand" data-entity-name="Brand" data-quickadd="lookup" required>
                {brand_opts}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Model</label>
              <input type="text" name="model" class="form-control" placeholder="e.g. iPhone 13, Note 12" required>
            </div>
          </div>
          <div class="form-group"><label class="form-label">Device IMEI (Optional)</label><input type="text" name="imei" class="form-control" placeholder="15-digit IMEI"></div>
          <div class="form-group">
            <label class="form-label">Fault / Problem Description</label>
            <select name="complaint" class="form-control smart-select" data-list-key="repair_complaint" data-entity-name="Complaint" data-quickadd="lookup" required>
              {complaint_opts}
            </select>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group"><label class="form-label">Estimated Cost (Rs.)</label><input type="number" name="estimate" class="form-control" value="0"></div>
            <div class="form-group"><label class="form-label">Advance Paid (Rs.)</label><input type="number" name="advance_paid" class="form-control" value="0"></div>
          </div>
          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:14px;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('new-job-modal').style.display='none'">Cancel</button>
            <button type="submit" class="btn btn-success" style="font-weight:bold;">Generate Job Card</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function filterRepairsTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.repair-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Repair Workshop", content, "repairs", user)

@app.route("/repairs/create", method="POST")
def create_repair_route():
    user = require_perm("repair_jobs")
    cname = request.forms.get("customer_name")
    cphone = request.forms.get("customer_phone")
    b = request.forms.get("brand")
    m = request.forms.get("model")
    imei = request.forms.get("imei", "")
    comp = request.forms.get("complaint")
    est = float(request.forms.get("estimate", 0))
    adv = float(request.forms.get("advance_paid", 0))

    res = services.create_repair_job(cname, cphone, b, m, comp, imei=imei, estimate=est, advance_paid=adv, user_id=user["id"], username=user["username"])
    return redirect(f"/print/repair/{res['repair_id']}")

@app.route("/repairs/manage/<rid:int>")
def manage_repair_screen(rid):
    user = require_perm("repair_jobs")
    rep = services.get_repair_job(rid)
    if not rep: return redirect("/repairs")
    j = rep["job"]
    parts = rep["parts"]

    # Available spare parts
    spare_parts = db.query_all("""
        SELECT v.id, v.retail_price, v.color, p.name AS product_name, p.brand, v.stock_quantity
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE p.item_type = 'SPARE_PART' AND v.is_archived = 0
    """)
    part_opts = "".join(f'<option value="{p["id"]}">{p["brand"]} {p["product_name"]} ({p["color"]}) [Stock: {p["stock_quantity"]}]</option>' for p in spare_parts)

    parts_rows = "".join(f"<tr><td>{p['part_name']}</td><td>{p['qty']}</td><td>Rs. {p['charge_price']:,.0f}</td></tr>" for p in parts)

    content = f"""
    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div class="card-title">Job #{j['job_no']} — {j['brand']} {j['model']}</div>
          <span class="badge badge-warning">{j['status']}</span>
        </div>
        <p><strong>Customer:</strong> {j['customer_name']} ({j['customer_phone']})</p>
        <p><strong>Complaint:</strong> {j['complaint']}</p>
        <p><strong>Advance Paid:</strong> Rs. {j['advance_paid']:,.0f}</p>
        <hr style="margin:12px 0; border:0; border-top:1px solid #334155;">

        <h4 style="margin-bottom:8px;">Change Stage / Status</h4>
        <form method="POST" action="/repairs/update-status/{j['id']}" style="display:flex; gap:8px;">
          <select name="status" class="form-control">
            <option value="DIAGNOSING">Diagnosing</option>
            <option value="WAITING_PARTS">Waiting for Parts</option>
            <option value="IN_REPAIR">In Repair</option>
            <option value="READY">Ready for Collection</option>
            <option value="CANCELLED">Cancelled</option>
          </select>
          <button type="submit" class="btn btn-primary">Update</button>
        </form>

        <hr style="margin:12px 0; border:0; border-top:1px solid #334155;">
        <h4 style="margin-bottom:8px;">Deliver & Collect Payment</h4>
        <form method="POST" action="/repairs/deliver/{j['id']}">
          <div class="form-group"><label class="form-label">Final Labor Charge (Rs.)</label><input type="number" name="labor" class="form-control" value="1500" required></div>
          <div class="form-group"><label class="form-label">Payment Collected (Rs.)</label><input type="number" name="paid" class="form-control" value="{j['estimate'] - j['advance_paid']}" required></div>
          <button type="submit" class="btn btn-success" style="width:100%; font-weight:bold;">Finalize & Mark Delivered</button>
        </form>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom:12px;">🔩 Fitted Spare Parts</div>
        <form method="POST" action="/repairs/add-part/{j['id']}" style="margin-bottom:16px;">
          <div class="form-group"><label class="form-label">Select Part from Inventory</label><select name="part_id" class="form-control smart-select" data-entity-name="Spare Part">{part_opts}</select></div>
          <div style="display:flex; gap:8px;">
            <input type="number" name="charge_price" class="form-control" placeholder="Price to charge (Rs.)" required>
            <button type="submit" class="btn btn-primary">+ Attach Part</button>
          </div>
        </form>

        <table class="data-table">
          <thead><tr><th>Part Name</th><th>Qty</th><th>Charged</th></tr></thead>
          <tbody>
            {parts_rows or '<tr><td colspan="3" style="text-align:center; color:#888;">No parts fitted yet</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """
    return layout(f"Job {j['job_no']}", content, "repairs", user)

@app.route("/repairs/update-status/<rid:int>", method="POST")
def repair_update_status_route(rid):
    user = require_perm("repair_jobs")
    st = request.forms.get("status")
    services.update_repair_status(rid, st, user_id=user["id"], username=user["username"])
    return redirect(f"/repairs/manage/{rid}")

@app.route("/repairs/add-part/<rid:int>", method="POST")
def repair_add_part_route(rid):
    user = require_perm("repair_jobs")
    pid = int(request.forms.get("part_id"))
    charge = float(request.forms.get("charge_price", 0))
    services.add_repair_part(rid, pid, charge_price=charge, user_id=user["id"], username=user["username"])
    return redirect(f"/repairs/manage/{rid}")

@app.route("/repairs/deliver/<rid:int>", method="POST")
def repair_deliver_route(rid):
    user = require_perm("repair_jobs")
    labor = float(request.forms.get("labor", 0))
    paid = float(request.forms.get("paid", 0))
    res = services.complete_and_deliver_repair(rid, labor, paid, user_id=user["id"], username=user["username"])
    return redirect(f"/print/repair/{rid}")

# ═══════════════════════════════════════════════════════════
# SOFTWARE SERVICES LAB
# ═══════════════════════════════════════════════════════════

@app.route("/software")
def software_screen():
    user = require_perm("software_jobs")
    catalog = services.list_software_catalog()
    jobs = services.list_software_jobs(limit=50)

    cat_options = "".join(f'<option value="{c["id"]}" data-price="{c["default_price"]}" data-cost="{c["default_cost"]}">{c["name"]} (Rs. {c["default_price"]:,.0f})</option>' for c in catalog)

    brand_items = lookups.get_lookup_list("brand")
    brand_opts = "".join(f'<option value="{b["label"]}">{b["label"]}</option>' for b in brand_items)

    rows_html = ""
    for j in jobs:
        search_corpus = f"{j['ticket_no'].lower()} {j['service_name'].lower()} {j['brand_model'].lower()} {(j['customer_phone'] or '').lower()} {(j['imei'] or '').lower()}"
        rows_html += f"""
        <tr class="software-row" data-search="{search_corpus}">
          <td><a href="/print/software/{j['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">{j['ticket_no']}</a></td>
          <td>{j['created_at'][:16]}</td>
          <td><strong>{j['service_name']}</strong></td>
          <td>{j['brand_model']}</td>
          <td>Rs. {j['price_charged']:,.0f}</td>
          <td style="color:#34d399; font-weight:bold;">Rs. {j['profit']:,.0f}</td>
          <td><a href="/print/software/{j['id']}" target="_blank" class="btn btn-sm btn-secondary">Print</a></td>
        </tr>
        """

    content = f"""
    <div class="grid-2">
      <!-- Fast Ticket Entry Card (< 10 seconds) -->
      <div class="card">
        <div class="card-title" style="margin-bottom:12px;">⚡ Fast Software Ticket Entry (&lt; 10s)</div>
        <form method="POST" action="/software/create">
          <div class="form-group">
            <label class="form-label">Service Type</label>
            <select name="service_id" id="sft-service-sel" class="form-control smart-select" data-list-key="software_service" data-entity-name="Software Service" data-quickadd="lookup" onchange="updateSftDefaults()">
              {cat_options}
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Device Brand & Model</label>
            <div style="display:grid; grid-template-columns: 140px 1fr; gap:8px;">
              <select name="brand_prefix" id="sft-brand" class="form-control smart-select" data-list-key="brand" data-entity-name="Brand" data-quickadd="lookup" onchange="appendBrandToModel()">
                <option value="">Brand...</option>
                {brand_opts}
              </select>
              <input type="text" name="brand_model" id="sft-brand-model" class="form-control" placeholder="e.g. Samsung A54 / Infinix Hot 30" required>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Customer Phone</label>
              <input type="text" name="customer_phone" class="form-control" placeholder="0300...">
            </div>
            <div class="form-group">
              <label class="form-label">Device IMEI (Optional)</label>
              <input type="text" name="imei" class="form-control" placeholder="15-digit IMEI">
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Price Charged (Rs.)</label>
              <input type="number" name="price" id="sft-price" class="form-control" value="1500" required>
            </div>
            <div class="form-group">
              <label class="form-label">Tool / Server Cost (Rs.)</label>
              <input type="number" name="cost" id="sft-cost" class="form-control" value="200" required>
            </div>
          </div>

          <button type="submit" class="btn btn-success" style="width:100%; padding:12px; font-weight:bold; font-size:14px; margin-top:8px;">
            🖨️ Create Job & Print Ticket
          </button>
        </form>
      </div>

      <!-- Recent Jobs -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">💻 Recent Software Jobs ({len(jobs)})</div>
          <input type="text" placeholder="🔍 Live filter..." class="form-control" style="width:160px; padding:4px 8px; font-size:11.5px;" oninput="filterSoftwareTable(this.value)">
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr><th>Ticket</th><th>Date</th><th>Service</th><th>Device</th><th>Charged</th><th>Profit</th><th>Print</th></tr>
            </thead>
            <tbody>
              {rows_html or '<tr><td colspan="7" style="text-align:center; color:#888;">No software jobs recorded yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      function updateSftDefaults() {{
        var sel = document.getElementById('sft-service-sel');
        if (!sel) return;
        var opt = sel.options[sel.selectedIndex];
        if (opt) {{
          document.getElementById('sft-price').value = opt.dataset.price || 1500;
          document.getElementById('sft-cost').value = opt.dataset.cost || 0;
        }}
      }}

      function appendBrandToModel() {{
        var b = document.getElementById('sft-brand').value;
        var inp = document.getElementById('sft-brand-model');
        if (b && !inp.value.startsWith(b)) {{
          inp.value = b + ' ' + inp.value;
        }}
      }}

      function filterSoftwareTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.software-row').forEach(r => {{
          var txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Software Services", content, "software", user)

@app.route("/software/create", method="POST")
def create_software_route():
    user = require_perm("software_jobs")
    sid = int(request.forms.get("service_id", 0))
    bm = request.forms.get("brand_model", "")
    phone = request.forms.get("customer_phone", "")
    imei = request.forms.get("imei", "")
    price = float(request.forms.get("price", 0))
    if user["role"] == "ADMIN":
        cost = float(request.forms.get("cost", 0))
    else:
        srv = db.query_one("SELECT default_cost FROM software_catalog WHERE id = ?", (sid,))
        cost = float(srv["default_cost"] or 0) if srv else 0.0

    res = services.create_software_job(bm, service_id=sid, price_charged=price, tool_server_cost=cost, customer_phone=phone, imei=imei, user_id=user["id"], username=user["username"])
    return redirect(f"/print/software/{res['job_id']}")

# ═══════════════════════════════════════════════════════════
# QUICK SERVICES (LOAD, EASYPAISA, JAZZCASH, SIM)
# ═══════════════════════════════════════════════════════════

@app.route("/quick-services")
def quick_services_screen():
    user = require_perm("quick_services")
    today = datetime.now().strftime("%Y-%m-%d")
    today_records = db.query_all("SELECT * FROM quick_services WHERE timestamp LIKE ? AND (is_void IS NULL OR is_void = 0) ORDER BY id DESC", (f"{today}%",))
    all_records = db.query_all("SELECT * FROM quick_services WHERE (is_void IS NULL OR is_void = 0) ORDER BY id DESC LIMIT 50")

    today_vol = sum(r["amount"] for r in today_records)
    today_comm = sum(r["profit"] for r in today_records)
    today_send = sum(r["amount"] for r in today_records if (r.get("action_type") or "SEND").upper() != "RECEIVE")
    today_recv = sum(r["amount"] for r in today_records if (r.get("action_type") or "SEND").upper() == "RECEIVE")

    stype_items = lookups.get_lookup_list("quick_service_type")
    stype_opts = "".join(f'<option value="{s["label"]}">{s["label"]}</option>' for s in stype_items)

    net_items = lookups.get_lookup_list("telecom_network")
    net_opts = "".join(f'<option value="{n["label"]}">{n["label"]}</option>' for n in net_items)

    rows_html = ""
    for r in all_records:
        act = (r.get("action_type") or "SEND").strip().upper()
        if act == "RECEIVE":
            act_badge = '<span class="badge" style="background:#ef4444; color:#fff;">📥 Receive (Cash Given)</span>'
        elif act == "LOAD":
            act_badge = '<span class="badge" style="background:#a855f7; color:#fff;">📱 Load</span>'
        elif act == "BILL":
            act_badge = '<span class="badge" style="background:#0284c7; color:#fff;">💡 Bill</span>'
        else:
            act_badge = '<span class="badge" style="background:#10b981; color:#fff;">📤 Send (Cash In)</span>'

        rows_html += f"""
        <tr class="qs-row" data-search="{r['service_type'].lower()} {(r['network'] or '').lower()} {(r['customer_phone'] or '').lower()} {(r['notes'] or '').lower()}">
          <td>#QS-{r['id']:04d}</td>
          <td>{r['timestamp'][:16]}</td>
          <td><strong>{r['service_type']}</strong></td>
          <td>{act_badge}</td>
          <td><span class="badge badge-purple">{r['network'] or 'General'}</span></td>
          <td>{r['customer_phone'] or '-'}</td>
          <td>Rs. {r['amount']:,.0f}</td>
          <td style="color:#34d399; font-weight:bold;">+ Rs. {r['profit']:,.0f}</td>
          <td style="font-size:11.5px; color:#94a3b8;">{r['notes'] or '-'}</td>
        </tr>
        """

    content = f"""
    <div class="grid-3" style="margin-bottom:16px;">
      <div class="card">
        <div style="font-size:11px; color:var(--text-muted);">TODAY'S TRANSACTIONS</div>
        <div style="font-size:22px; font-weight:800; color:#38bdf8; margin-top:4px;">{len(today_records)} Operations</div>
        <div style="font-size:11px; color:#94a3b8;">EasyPaisa, JazzCash & Loads</div>
      </div>
      <div class="card">
        <div style="font-size:11px; color:var(--text-muted);">TODAY'S VOLUME HANDLED</div>
        <div style="font-size:22px; font-weight:800; color:#fbbf24; margin-top:4px;">Rs. {today_vol:,.0f}</div>
        <div style="font-size:11px; color:#94a3b8;">Sent: Rs. {today_send:,.0f} | Recv: Rs. {today_recv:,.0f}</div>
      </div>
      <div class="card">
        <div style="font-size:11px; color:var(--text-muted);">TODAY'S COMMISSION PROFIT</div>
        <div style="font-size:22px; font-weight:800; color:#34d399; margin-top:4px;">Rs. {today_comm:,.0f}</div>
        <div style="font-size:11px; color:#94a3b8;">Instant shop profit earned</div>
      </div>
    </div>

    <div class="grid-2">
      <!-- Quick Entry Card (< 10 seconds) -->
      <div class="card">
        <div class="card-title" style="margin-bottom:12px;">⚡ Record Quick Transaction (&lt; 10s)</div>
        <form method="POST" action="/quick-services/record">
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label" style="font-weight:bold; font-size:12px; color:#38bdf8;">Operation Type (Paisa Bhejna ya Nikalwana?)</label>
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:6px;">
              <label style="display:flex; align-items:center; gap:5px; background:rgba(255,255,255,0.05); padding:6px; border-radius:6px; cursor:pointer; border:1px solid var(--border); font-size:11px;">
                <input type="radio" name="action_type" value="SEND" checked onchange="updateQSHelper()">
                <span>📤 <strong>Send</strong><br><small style="color:var(--text-muted);">Cash-In</small></span>
              </label>
              <label style="display:flex; align-items:center; gap:5px; background:rgba(255,255,255,0.05); padding:6px; border-radius:6px; cursor:pointer; border:1px solid var(--border); font-size:11px;">
                <input type="radio" name="action_type" value="RECEIVE" onchange="updateQSHelper()">
                <span>📥 <strong>Receive</strong><br><small style="color:var(--text-muted);">Cash-Out</small></span>
              </label>
              <label style="display:flex; align-items:center; gap:5px; background:rgba(255,255,255,0.05); padding:6px; border-radius:6px; cursor:pointer; border:1px solid var(--border); font-size:11px;">
                <input type="radio" name="action_type" value="LOAD" onchange="updateQSHelper()">
                <span>📱 <strong>Load</strong><br><small style="color:var(--text-muted);">Topup</small></span>
              </label>
              <label style="display:flex; align-items:center; gap:5px; background:rgba(255,255,255,0.05); padding:6px; border-radius:6px; cursor:pointer; border:1px solid var(--border); font-size:11px;">
                <input type="radio" name="action_type" value="BILL" onchange="updateQSHelper()">
                <span>💡 <strong>Bill</strong><br><small style="color:var(--text-muted);">Pay</small></span>
              </label>
            </div>
          </div>
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Service Type</label>
              <select name="service_type" class="form-control smart-select" data-list-key="quick_service_type" data-entity-name="Service Type" data-quickadd="lookup" required>
                {stype_opts}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Telecom Network / Provider</label>
              <select name="network" class="form-control smart-select" data-list-key="telecom_network" data-entity-name="Network" data-quickadd="lookup">
                {net_opts}
              </select>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Customer Mobile Number</label>
              <input type="text" name="customer_phone" class="form-control" placeholder="03001234567" required>
            </div>
            <div class="form-group">
              <label class="form-label">Transaction Amount (Rs.)</label>
              <input type="number" name="amount" id="qs-amount" class="form-control" placeholder="e.g. 2000" required>
            </div>
          </div>

          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
            <div class="form-group">
              <label class="form-label">Fee / Commission Earned (Rs.)</label>
              <input type="number" name="fee_commission" id="qs-comm" class="form-control" value="0" placeholder="0" min="0" style="color:#34d399; font-weight:bold;" required>
            </div>
            <div class="form-group">
              <label class="form-label">Notes (Optional)</label>
              <input type="text" name="notes" class="form-control" placeholder="e.g. Cash-in TID #482910">
            </div>
          </div>

          <div id="qs-calc-preview" style="background:rgba(0,0,0,0.25); border:1px solid #38bdf8; border-radius:6px; padding:8px 12px; margin-top:8px; font-size:12px; line-height:1.4;">
            <div style="color:#38bdf8; font-weight:bold;">📤 Send (Cash-In) Summary:</div>
            <div>💵 Customer se Cash lena hai: <span style="color:#34d399; font-weight:bold;">Rs. 0</span></div>
            <div>💰 Aapka Pure Munafa: <span style="color:#34d399; font-weight:bold;">+Rs. 0</span></div>
          </div>

          <button type="submit" class="btn btn-success" style="width:100%; padding:12px; font-size:14px; font-weight:bold; margin-top:10px;">
            💾 Record Transaction & Add Profit to Drawer
          </button>
        </form>
      </div>

      <!-- Recent Transactions Table -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">📜 Recent Quick Earnings</div>
          <input type="text" placeholder="🔍 Live filter..." class="form-control" style="width:160px; padding:4px 8px; font-size:11.5px;" oninput="filterQSTable(this.value)">
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr><th>Ref</th><th>Time</th><th>Service</th><th>Type</th><th>Network</th><th>Phone</th><th>Amount</th><th>Profit</th><th>Notes</th></tr>
            </thead>
            <tbody>
              {rows_html or '<tr><td colspan="9" style="text-align:center; color:#888;">No quick service transactions recorded yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      function filterQSTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.qs-row').forEach(r => {{
          var txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
      function updateQSHelper() {{
        var actEl = document.querySelector('input[name="action_type"]:checked');
        var act = actEl ? actEl.value : 'SEND';
        var aEl = document.getElementById('qs-amount');
        var cEl = document.getElementById('qs-comm');
        var amt = parseFloat((aEl && aEl.value) || 0);
        var comm = parseFloat((cEl && cEl.value) || 0);
        var box = document.getElementById('qs-calc-preview');
        if (!box) return;

        if (act === 'SEND') {{
          var cashTaken = amt + comm;
          box.innerHTML = '<div style="color:#38bdf8; font-weight:bold;">📤 Send (Cash-In) Summary:</div>' +
            '<div>💵 <strong>Customer se Cash lena hai:</strong> <span style="color:#34d399; font-size:13px; font-weight:bold;">Rs. ' + cashTaken.toLocaleString() + '</span> (Raqam ' + amt.toLocaleString() + ' + Munafa ' + comm.toLocaleString() + ')</div>' +
            '<div>📲 <strong>Aapke App se transfer hoga:</strong> Rs. ' + amt.toLocaleString() + '</div>' +
            '<div>💰 <strong>Aapka Pure Profit (Munafa):</strong> <span style="color:#34d399; font-weight:bold;">+Rs. ' + comm.toLocaleString() + '</span></div>';
        }} else if (act === 'RECEIVE') {{
          var cashGiven = Math.max(0, amt - comm);
          box.innerHTML = '<div style="color:#f87171; font-weight:bold;">📥 Receive (Cash-Out) Summary:</div>' +
            '<div>📲 <strong>Customer aapke account me bhejega:</strong> Rs. ' + amt.toLocaleString() + '</div>' +
            '<div>💵 <strong>Customer ko Cash dena hai:</strong> <span style="color:#f87171; font-size:13px; font-weight:bold;">Rs. ' + cashGiven.toLocaleString() + '</span> (Raqam ' + amt.toLocaleString() + ' - Fee ' + comm.toLocaleString() + ')</div>' +
            '<div>💰 <strong>Aapka Pure Profit (Munafa):</strong> <span style="color:#34d399; font-weight:bold;">+Rs. ' + comm.toLocaleString() + '</span></div>';
        }} else if (act === 'LOAD') {{
          box.innerHTML = '<div style="color:#a855f7; font-weight:bold;">📱 EasyLoad Summary:</div>' +
            '<div>💵 <strong>Customer se Cash lena hai:</strong> Rs. ' + (amt + comm).toLocaleString() + '</div>' +
            '<div>💰 <strong>Aapka Munafa:</strong> <span style="color:#34d399; font-weight:bold;">+Rs. ' + comm.toLocaleString() + '</span></div>';
        }} else {{
          box.innerHTML = '<div style="color:#38bdf8; font-weight:bold;">💡 Bill Payment Summary:</div>' +
            '<div>💵 <strong>Customer se Cash lena hai:</strong> Rs. ' + (amt + comm).toLocaleString() + '</div>' +
            '<div>💰 <strong>Aapka Munafa:</strong> <span style="color:#34d399; font-weight:bold;">+Rs. ' + comm.toLocaleString() + '</span></div>';
        }}
      }}
      document.addEventListener('DOMContentLoaded', function() {{
        var a = document.getElementById('qs-amount');
        var c = document.getElementById('qs-comm');
        if (a) a.addEventListener('input', updateQSHelper);
        if (c) c.addEventListener('input', updateQSHelper);
        updateQSHelper();
      }});
    </script>
    """
    return layout("Quick Services", content, "quick_services", user)

@app.route("/quick-services/record", method="POST")
def quick_services_record():
    user = require_perm("quick_services")
    stype = request.forms.get("service_type", "").strip()
    act = request.forms.get("action_type", "SEND").strip()
    net = request.forms.get("network", "").strip()
    phone = request.forms.get("customer_phone", "").strip()
    amt = float(request.forms.get("amount", 0) or 0)
    comm = float(request.forms.get("fee_commission", 0) or 0)
    notes = request.forms.get("notes", "").strip()

    services.record_quick_service(stype, amt, comm, customer_phone=phone, network=net, notes=notes, user_id=user["id"], username=user["username"], action_type=act)
    return redirect("/quick-services")

# ═══════════════════════════════════════════════════════════
# UDHAAR & INSTALLMENTS
# ═══════════════════════════════════════════════════════════

@app.route("/credit")
def credit_screen():
    user = require_login()
    customers = credit.list_customers(limit=50)
    plans = credit.list_installments(limit=30)
    overdue = credit.get_overdue_installments()

    payment_accounts = lookups.get_lookup_list("payment_account")
    acc_opts = "".join(f'<option value="{a["label"]}">{a["label"]}</option>' for a in payment_accounts)

    cust_rows = ""
    for c in customers:
        cust_search = f"{c['name'].lower()} {c['phone'].lower()} {(c['cnic'] or '').lower()}"
        c_phone_disp = '<span style="color:#64748b;">-</span>' if not c['phone'] or c['phone'].startswith('NOP-') else c['phone']
        c_name_esc = html.escape(c['name'], quote=True)
        cust_rows += f"""
        <tr class="cust-row" data-search="{cust_search}">
          <td><a href="/credit/customer/{c['id']}" style="color:#38bdf8; font-weight:bold; text-decoration:none;" title="View Customer Khata Ledger">{c['name']}</a></td>
          <td>{c_phone_disp}</td>
          <td>{c['cnic'] or '-'}</td>
          <td style="color:{'#f87171' if c['balance_udhaar'] > 0 else '#34d399'}; font-weight:bold;">Rs. {c['balance_udhaar']:,.0f}</td>
          <td style="white-space:nowrap;">
            {f'''<button class="btn btn-sm btn-success" data-cid="{c['id']}" data-name="{c_name_esc}" data-bal="{c['balance_udhaar']}" onclick="openPayUdhaarModal(this)">Collect</button> <a href="/credit/customer/{c['id']}" class="btn btn-sm btn-secondary">Khata</a>''' if c['balance_udhaar'] > 0 else f'<a href="/credit/customer/{c['id']}" class="btn btn-sm btn-secondary">Khata</a>'}
          </td>
        </tr>
        """

    plan_rows = ""
    for p in plans:
        plan_search = f"{p['customer_name'].lower()} inst-{p['id']:04d}"
        plan_rows += f"""
        <tr class="plan-row" data-search="{plan_search}">
          <td><a href="/print/installment-contract/{p['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">INST-{p['id']:04d}</a></td>
          <td>{p['customer_name']}</td>
          <td>Rs. {p['financed_amount']:,.0f}</td>
          <td>{p['paid_count']} / {p['total_months']}</td>
          <td>Rs. {p['monthly_due']:,.0f} / mo</td>
          <td><a href="/credit/plan/{p['id']}" class="btn btn-sm btn-primary">Schedule</a></td>
        </tr>
        """

    content = f"""
    <div class="grid-2">
      <!-- Customers & Udhaar Balances -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">👥 Customer Credit & Udhaar Balances ({len(customers)})</div>
          <div style="display:flex; gap:8px; align-items:center;">
            <input type="text" placeholder="🔍 Live filter customers..." class="form-control" style="width:160px; padding:4px 8px; font-size:11.5px;" oninput="filterCustTable(this.value)">
            <button type="button" class="btn btn-primary btn-sm" onclick="QuickAdd.open('customer', {{}})">+ Add Customer</button>
          </div>
        </div>
        <div class="table-responsive">
          <table class="data-table" id="customers-table">
            <thead>
              <tr><th>Name</th><th>Phone</th><th>CNIC</th><th>Udhaar Balance</th><th>Action</th></tr>
            </thead>
            <tbody>
              {cust_rows or '<tr><td colspan="5" style="text-align:center; color:#888;">No customers registered</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Installment Plans -->
      <div>
        {f'<div class="card" style="margin-bottom:12px; border:1px solid #ef4444;"><div class="card-title" style="color:#f87171;">⚠️ {len(overdue)} Overdue Installments!</div><p style="font-size:12px; color:#cbd5e1;">Review customers past their monthly due date.</p></div>' if overdue else ''}
        
        <div class="card">
          <div class="card-header">
            <div class="card-title">📅 Active Installment Plans ({len(plans)})</div>
            <input type="text" placeholder="🔍 Live filter plans..." class="form-control" style="width:150px; padding:4px 8px; font-size:11.5px;" oninput="filterPlansTable(this.value)">
          </div>
          <div class="table-responsive">
            <table class="data-table" id="plans-table">
              <thead>
                <tr><th>Plan</th><th>Customer</th><th>Financed</th><th>Paid</th><th>Monthly</th><th>Action</th></tr>
              </thead>
              <tbody>
                {plan_rows or '<tr><td colspan="6" style="text-align:center; color:#888;">No installment plans active</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: Collect Udhaar Payment -->
    <div id="collect-udhaar-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:2000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:440px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:800; color:var(--text);">Collect Udhaar Payment</h3>
          <button type="button" onclick="document.getElementById('collect-udhaar-modal').style.display='none'" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form method="POST" action="/credit/pay-udhaar">
          <input type="hidden" name="customer_id" id="udhaar-cust-id">
          <p style="font-size:13px; margin-bottom:8px;">Customer: <strong id="udhaar-cust-name" style="color:#38bdf8;"></strong></p>
          <p style="font-size:13px; margin-bottom:12px;">Outstanding Balance: <strong id="udhaar-cust-bal" style="color:#f87171;">Rs. 0</strong></p>
          
          <div class="form-group">
            <label class="form-label">Payment Received (Rs.)</label>
            <input type="number" name="amount" id="udhaar-pay-amt" class="form-control" style="font-size:16px; font-weight:bold; color:#34d399;" required>
          </div>

          <div class="form-group">
            <label class="form-label">Payment Mode / Account</label>
            <select name="account" class="form-control smart-select" data-list-key="payment_account" data-entity-name="Account" data-quickadd="lookup">
              {acc_opts}
            </select>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('collect-udhaar-modal').style.display='none'">Cancel</button>
            <button type="submit" class="btn btn-success" style="font-weight:bold;">Collect Payment</button>
          </div>
        </form>
      </div>
    </div>

    <script>
      function openPayUdhaarModal(cid, name, bal) {{
        if (typeof cid === 'object' && cid !== null) {{
          var btn = cid;
          cid = btn.getAttribute('data-cid');
          name = btn.getAttribute('data-name');
          bal = btn.getAttribute('data-bal');
        }}
        document.getElementById('udhaar-cust-id').value = cid;
        document.getElementById('udhaar-cust-name').innerText = name;
        document.getElementById('udhaar-cust-bal').innerText = 'Rs. ' + Number(bal).toLocaleString();
        document.getElementById('udhaar-pay-amt').value = bal;
        document.getElementById('collect-udhaar-modal').style.display = 'flex';
        setTimeout(() => document.getElementById('udhaar-pay-amt').focus(), 50);
      }}

      function filterCustTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.cust-row').forEach(r => {{
          var txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}

      function filterPlansTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.plan-row').forEach(r => {{
          var txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Udhaar & Installments", content, "credit", user)

@app.route("/credit/customer/<cid:int>")
@app.route("/credit/customer/<cid:int>/")
def credit_customer_ledger_screen(cid):
    user = require_login()
    c = db.query_one("SELECT * FROM customers WHERE id = ?", (cid,))
    if not c:
        return redirect("/credit")
    
    sales = db.query_all("SELECT * FROM sales WHERE customer_phone = ? OR customer_name = ? ORDER BY id DESC LIMIT 20", (c["phone"], c["name"]))
    payments = db.query_all("SELECT * FROM udhaar_ledger WHERE customer_id = ? ORDER BY id DESC LIMIT 20", (cid,))
    plans = db.query_all("SELECT * FROM installments WHERE customer_id = ? ORDER BY id DESC", (cid,))

    payment_accounts = lookups.get_lookup_list("payment_account")
    acc_opts = "".join(f'<option value="{a["label"]}">{a["label"]}</option>' for a in payment_accounts)

    sales_rows = ""
    for s in sales:
        sales_rows += f"""
        <tr>
          <td><a href="/print/sale/{s['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">{s['invoice_no']}</a></td>
          <td>{s['created_at'][:16]}</td>
          <td>{s['payment_method']}</td>
          <td style="text-align:right; font-weight:bold;">Rs. {s['grand_total']:,.0f}</td>
          <td><a href="/print/sale/{s['id']}" target="_blank" class="btn btn-sm btn-secondary">Slip</a></td>
        </tr>
        """

    pay_rows = ""
    for p in payments:
        p_date = p.get('transaction_date') or p['timestamp'][:16]
        p_badge = '<span class="badge" style="background:#10b981; color:#fff;">PAYMENT</span>' if p['transaction_type'] == 'PAYMENT' else f'<span class="badge" style="background:#6366f1; color:#fff;">{p["transaction_type"]}</span>'
        pay_rows += f"""
        <tr>
          <td><a href="/print/udhaar-payment/{p['id']}" target="_blank" style="color:#60a5fa; font-weight:bold;">#UDH-{p['id']:05d}</a><br><small style="color:#94a3b8;">{p_date}</small></td>
          <td>{p_badge}</td>
          <td><strong style="color:#34d399; font-size:13.5px;">Rs. {p['amount']:,.0f}</strong></td>
          <td><span style="font-weight:bold; color:{'#f87171' if p.get('balance_after', 0) > 0 else '#34d399'};">Rs. {p.get('balance_after', 0):,.0f}</span></td>
          <td>{p['payment_method']}</td>
          <td>{p.get('notes') or '-'}</td>
          <td style="text-align:right;">
            <a href="/print/udhaar-payment/{p['id']}" target="_blank" class="btn btn-sm btn-primary">🖨️ Receipt</a>
          </td>
        </tr>
        """

    paid_lid = request.query.get("paid_lid")
    paid_banner = f"""
    <div class="card" style="margin-bottom:14px; background:rgba(16,185,129,0.15); border:1px solid #10b981; padding:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
      <div>
        <strong style="color:#34d399; font-size:15px;">✅ Udhaar Payment Received Successfully!</strong>
        <div style="font-size:12px; color:#cbd5e1; margin-top:2px;">Khata balance has been updated. Official voucher #UDH-{int(paid_lid):05d} recorded.</div>
      </div>
      <a href="/print/udhaar-payment/{paid_lid}" target="_blank" class="btn btn-primary btn-sm" style="font-weight:bold; padding:8px 14px;">🖨️ Print Payment Receipt</a>
    </div>
    """ if paid_lid else ""

    c_name_esc = html.escape(c['name'], quote=True)
    content = f"""
    {paid_banner}
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
      <div>
        <div style="font-size: 12px; color: var(--text-muted);"><a href="/credit" style="color: #60a5fa; text-decoration: none;">&larr; Back to All Customers & Udhaar</a></div>
        <h1 style="font-size: 22px; font-weight: 800; margin-top: 4px;">👤 {c['name']} — Khata Ledger</h1>
        <div style="font-size: 13px; color: #94a3b8;">Phone: <strong>{c['phone']}</strong> &bull; CNIC: {c['cnic'] or 'N/A'} &bull; Address: {c['address'] or 'N/A'}</div>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="btn btn-success btn-sm" data-cid="{c['id']}" data-name="{c_name_esc}" data-bal="{c['balance_udhaar']}" onclick="openPayUdhaarModal(this)" style="font-weight:bold;">Collect Udhaar</button>
        <a href="/credit" class="btn btn-secondary btn-sm">All Customers</a>
      </div>
    </div>

    <div class="grid-3" style="margin-bottom: 16px;">
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">OUTSTANDING UDHAAR BALANCE</div>
        <div style="font-size: 24px; font-weight: 800; color: {'#f87171' if c['balance_udhaar'] > 0 else '#34d399'}; margin-top: 4px;">
          Rs. {c['balance_udhaar']:,.0f}
        </div>
      </div>
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">TOTAL INVOICES</div>
        <div style="font-size: 24px; font-weight: 800; color: #38bdf8; margin-top: 4px;">
          {len(sales)} Purchases
        </div>
      </div>
      <div class="card" style="padding: 14px;">
        <div style="font-size: 11px; color: var(--text-muted);">INSTALLMENT CONTRACTS</div>
        <div style="font-size: 24px; font-weight: 800; color: #a78bfa; margin-top: 4px;">
          {len(plans)} Plans
        </div>
      </div>
    </div>

    <div class="grid-2">
      <!-- Sales Invoices -->
      <div class="card">
        <div class="card-header"><div class="card-title">🧾 Purchase History ({len(sales)})</div></div>
        <div class="table-responsive">
          <table class="data-table">
            <thead><tr><th>Invoice</th><th>Date</th><th>Method</th><th style="text-align:right;">Amount</th><th>Action</th></tr></thead>
            <tbody>
              {sales_rows or '<tr><td colspan="5" style="text-align:center; color:#888;">No purchases on record</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Payment Collections -->
      <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div class="card-title">💵 Payment History ({len(payments)})</div>
          <button class="btn btn-success btn-xs" data-cid="{c['id']}" data-name="{c_name_esc}" data-bal="{c['balance_udhaar']}" onclick="openPayUdhaarModal(this)" style="font-weight:bold;">+ Collect Payment</button>
        </div>
        <div class="table-responsive">
          <table class="data-table">
            <thead><tr><th>Voucher / Date</th><th>Type</th><th>Amount Paid</th><th>Balance After</th><th>Account</th><th>Notes</th><th style="text-align:right;">Action</th></tr></thead>
            <tbody>
              {pay_rows or '<tr><td colspan="7" style="text-align:center; color:#888;">No payments recorded</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Modal: Collect Udhaar Payment -->
    <div id="collect-udhaar-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); backdrop-filter:blur(3px); z-index:2000; align-items:center; justify-content:center;">
      <div style="background:var(--card); border:1px solid var(--card-border); padding:24px; border-radius:12px; width:440px; max-width:92vw;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:800; color:var(--text);">Collect Udhaar Payment</h3>
          <button type="button" onclick="document.getElementById('collect-udhaar-modal').style.display='none'" style="background:none; border:none; color:var(--text-muted); font-size:18px; cursor:pointer;">✕</button>
        </div>
        <form method="POST" action="/credit/pay-udhaar">
          <input type="hidden" name="customer_id" id="udhaar-cust-id" value="{c['id']}">
          <p style="font-size:13px; margin-bottom:8px;">Customer: <strong id="udhaar-cust-name" style="color:#38bdf8;">{c['name']}</strong></p>
          <p style="font-size:13px; margin-bottom:12px;">Outstanding Balance: <strong id="udhaar-cust-bal" style="color:#f87171;">Rs. {c['balance_udhaar']:,.0f}</strong></p>
          
          <div class="form-group">
            <label class="form-label">Payment Received (Rs.)</label>
            <input type="number" name="amount" id="udhaar-pay-amt" class="form-control" value="{c['balance_udhaar']}" style="font-size:16px; font-weight:bold; color:#34d399;" required>
          </div>

          <div class="form-group">
            <label class="form-label">Payment Mode / Account</label>
            <select name="account" class="form-control smart-select" data-list-key="payment_account" data-entity-name="Account" data-quickadd="lookup">
              {acc_opts}
            </select>
          </div>

          <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:16px;">
            <button type="button" class="btn btn-secondary" onclick="document.getElementById('collect-udhaar-modal').style.display='none'">Cancel</button>
            <button type="submit" class="btn btn-success" style="font-weight:bold;">Collect Payment</button>
          </div>
        </form>
      </div>
    </div>
    <script>
      function openPayUdhaarModal(cid, name, bal) {{
        if (typeof cid === 'object' && cid !== null) {{
          var btn = cid;
          cid = btn.getAttribute('data-cid');
          name = btn.getAttribute('data-name');
          bal = btn.getAttribute('data-bal');
        }}
        document.getElementById('collect-udhaar-modal').style.display = 'flex';
        setTimeout(() => document.getElementById('udhaar-pay-amt').focus(), 50);
      }}
    </script>
    """
    return layout(f"{c['name']} — Khata Ledger", content, "credit", user)

@app.route("/credit/pay-udhaar", method=["GET", "POST"])
def pay_udhaar_route():
    user = require_login()
    cid = int(request.params.get("customer_id") or 0)
    amt = float(request.params.get("amount") or 0)
    pm = request.params.get("account") or request.params.get("payment_method") or "Cash Drawer"
    notes = request.params.get("notes") or "Udhaar payment collected"
    pdate = request.params.get("payment_date") or None
    reason = request.params.get("backdate_reason") or ""
    res = None
    if cid > 0 and amt > 0:
        res = credit.record_udhaar_payment(cid, amt, payment_method=pm, notes=notes, payment_date=pdate, backdate_reason=reason, user_id=user["id"], username=user["username"])
    if res and res.get("success") and res.get("ledger_id"):
        return redirect(f"/credit/customer/{cid}?paid_lid={res['ledger_id']}")
    ref = request.headers.get("Referer")
    if ref and "/credit" in ref:
        return redirect(ref)
    return redirect(f"/credit/customer/{cid}" if cid > 0 else "/credit")

@app.route("/credit/plan/<iid:int>")
def plan_schedule_screen(iid):
    user = require_login()
    dtls = credit.get_installment_details(iid)
    if not dtls: return redirect("/credit")
    p = dtls["plan"]
    sched = dtls["schedule"]

    sched_rows = ""
    for s in sched:
        btn = f'<a href="/credit/pay-installment/{s["id"]}" class="btn btn-sm btn-success">Collect</a>' if s['status'] != 'PAID' else f'<a href="/print/installment-payment/{s["id"]}" target="_blank" class="btn btn-sm btn-secondary">Receipt</a>'
        sched_rows += f"""
        <tr>
          <td>Month #{s['installment_no']}</td>
          <td>{s['due_date']}</td>
          <td>Rs. {s['due_amount']:,.0f}</td>
          <td>Rs. {s['paid_amount']:,.0f}</td>
          <td><span class="badge {'badge-success' if s['status'] == 'PAID' else 'badge-warning'}">{s['status']}</span></td>
          <td>{btn}</td>
        </tr>
        """

    content = f"""
    <div class="card" style="max-width:850px; margin:0 auto;">
      <div class="card-header">
        <div class="card-title">Contract INST-{p['id']:04d} — {p['customer_name']}</div>
        <div>
          <a href="/print/installment-contract/{p['id']}" target="_blank" class="btn btn-sm btn-primary">🖨️ Print Agreement</a>
          <a href="/credit" class="btn btn-sm btn-secondary">Back</a>
        </div>
      </div>
      <p style="font-size:12.5px; color:#cbd5e1; margin-bottom:12px;">
        Total: Rs. {p['total_price']:,.0f} | Down Payment: Rs. {p['down_payment']:,.0f} | Financed: Rs. {p['financed_amount']:,.0f}
      </p>

      <table class="data-table">
        <thead>
          <tr><th>Month</th><th>Due Date</th><th>Due Amount</th><th>Paid</th><th>Status</th><th>Action</th></tr>
        </thead>
        <tbody>
          {sched_rows}
        </tbody>
      </table>
    </div>
    """
    return layout("Installment Schedule", content, "credit", user)

@app.route("/credit/pay-installment/<sid:int>")
def pay_installment_route(sid):
    user = require_login()
    s = db.query_one("SELECT * FROM installment_schedule WHERE id = ?", (sid,))
    if s:
        due = s["due_amount"] - s["paid_amount"]
        res = credit.pay_installment(sid, due, user_id=user["id"], username=user["username"])
        if res["success"]:
            return redirect(f"/print/installment-payment/{sid}")
    return redirect("/credit")

# ═══════════════════════════════════════════════════════════
# EXPENSES
# ═══════════════════════════════════════════════════════════

@app.route("/expenses")
def expenses_screen():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]

    # Query params
    req_month = request.query.get("month", "").strip()
    req_cat = request.query.get("category", "").strip()
    quick = request.query.get("quick", "").strip()
    req_start = request.query.get("start_date", "").strip()
    req_end = request.query.get("end_date", "").strip()

    if quick == "this_month":
        req_month = current_month
    elif quick == "last_month":
        from datetime import date, timedelta
        first_this = date(datetime.now().year, datetime.now().month, 1)
        req_month = (first_this - timedelta(days=1)).strftime("%Y-%m")
    elif quick == "all":
        req_month = ""

    active_month = req_month or current_month

    # Fetch month summary and list
    summary = accounting.get_month_expenses_summary(active_month, category=req_cat)
    exps = summary.get("expenses", [])

    # Load dynamic categories from lookup_lists
    cat_items = lookups.get_lookup_list("expense_category")
    cat_opts = "".join(f'<option value="{c["label"]}">{c["label"]}</option>' for c in cat_items)
    cat_filter_opts = '<option value="">All Categories</option>' + "".join(
        f'<option value="{c["label"]}" {"selected" if req_cat == c["label"] else ""}>{c["label"]}</option>'
        for c in cat_items
    )

    # Load payment accounts
    pm_items = lookups.get_lookup_list("payment_account")
    pm_opts = "".join(f'<option value="{p["label"]}">{p["label"]}</option>' for p in pm_items) if pm_items else '<option value="Cash Drawer">Cash Drawer</option><option value="Online">Online</option>'

    exp_rows = ""
    for e in exps:
        pm_badge = '<span class="badge badge-danger" style="font-size:10px;">💵 Drawer</span>' if e.get("is_cash") else '<span class="badge badge-info" style="font-size:10px;">🏦 Bank</span>'
        exp_rows += f"""<tr class='exp-row' data-search='{e["category"].lower()} {(e["description"] or "").lower()}'>
          <td>{e["expense_date"]}</td>
          <td><strong>{e["category"]}</strong></td>
          <td>{e["description"] or "-"}</td>
          <td style='font-weight:bold; color:#f87171;'>Rs. {e["amount"]:,.0f}</td>
          <td>{e["payment_method"]} {pm_badge}</td>
        </tr>"""

    content = f"""
    <div style="margin-bottom:16px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
      <div>
        <h2 style="margin:0; font-size:1.3rem; color:var(--text, #f8fafc);">💸 Shop Expenses Management</h2>
        <div style="font-size:12px; color:#94a3b8;">Record, track, audit, and export daily & monthly business expenses</div>
      </div>
      <div style="display:flex; gap:8px; align-items:center;">
        <a href="/expenses/export.csv?month={active_month}&category={req_cat}" class="btn btn-secondary btn-sm font-weight-bold">📥 Export CSV / Excel</a>
        <a href="/print/expenses?month={active_month}&category={req_cat}" target="_blank" class="btn btn-primary btn-sm font-weight-bold">🖨️ Print Monthly Report</a>
      </div>
    </div>

    <!-- Monthly Summary KPI Badges -->
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:16px;">
      <div class="card" style="padding:14px; background:rgba(244,63,94,0.08); border-left:4px solid #f43f5e;">
        <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Total Month Expenses</div>
        <div style="font-size:1.4rem; font-weight:800; color:#f87171; margin-top:4px;">Rs. {summary['total_expenses']:,.0f}</div>
        <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">{len(exps)} transactions in {active_month}</div>
      </div>
      <div class="card" style="padding:14px; background:rgba(239,68,68,0.08); border-left:4px solid #ef4444;">
        <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Cash Drawer Expenses</div>
        <div style="font-size:1.4rem; font-weight:800; color:#ef4444; margin-top:4px;">Rs. {summary['cash_expenses']:,.0f}</div>
        <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Direct cash deducted from counter</div>
      </div>
      <div class="card" style="padding:14px; background:rgba(56,189,248,0.08); border-left:4px solid #38bdf8;">
        <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Bank / Online Expenses</div>
        <div style="font-size:1.4rem; font-weight:800; color:#38bdf8; margin-top:4px;">Rs. {summary['non_cash_expenses']:,.0f}</div>
        <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Paid via bank / jazzcash / easypaisa</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-header">
          <div class="card-title">💸 Record Shop Expense</div>
          <button type="button" class="btn btn-sm btn-primary" onclick="QuickAdd.open('expense_category', {{ listKey: 'expense_category', entityName: 'Expense Category', triggerSelect: document.getElementById('expense-cat-select') }})">+ Add Category</button>
        </div>
        <form method="POST" action="/expenses/create">
          <div class="form-group">
            <label class="form-label">Expense Category</label>
            <select name="category" id="expense-cat-select" class="form-control smart-select" data-list-key="expense_category" data-entity-name="Expense Category" data-quickadd="expense_category" data-allow-rename="true">
              {cat_opts}
              <option value="Other">Other expense...</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Expense Date</label>
            <input type="date" name="expense_date" value="{today}" class="form-control" style="font-weight:bold;">
          </div>
          <div class="form-group">
            <label class="form-label">Amount (Rs.)</label>
            <input type="number" name="amount" class="form-control" placeholder="0" required autofocus>
          </div>
          <div class="form-group">
            <label class="form-label">Description / Payee Details</label>
            <input type="text" name="description" class="form-control" placeholder="e.g. Electricity bill / Chai & Samosa for counter / Rent">
          </div>
          <div class="form-group">
            <label class="form-label">Paid From Account</label>
            <select name="payment_method" class="form-control smart-select" data-list-key="payment_account" data-entity-name="Payment Account" data-quickadd="lookup">
              {pm_opts}
            </select>
          </div>
          <button type="submit" class="btn btn-danger" style="width:100%; font-weight:bold; padding:12px; margin-top:6px;">Record Expense</button>
        </form>
      </div>

      <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <div>
            <div class="card-title">Recent Expenses ({len(exps)})</div>
            <div style="font-size:11px; color:#94a3b8;">Month: <strong>{active_month}</strong></div>
          </div>
          <form method="GET" action="/expenses" style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
            <input type="month" name="month" value="{active_month}" class="form-control" style="width:130px; padding:3px 6px; font-size:11.5px; font-weight:bold;" onchange="this.form.submit()">
            <select name="category" class="form-control" style="width:130px; padding:3px 6px; font-size:11.5px;" onchange="this.form.submit()">
              {cat_filter_opts}
            </select>
          </form>
        </div>
        <div style="padding:8px 12px; border-bottom:1px solid var(--border, #334155); display:flex; justify-content:space-between; align-items:center; gap:8px;">
          <input type="text" id="expense-table-filter" placeholder="🔍 Search descriptions..." class="form-control" style="padding:4px 8px; font-size:11.5px; flex:1;" oninput="filterExpensesTable(this.value)">
          <div style="display:flex; gap:4px;">
            <a href="/expenses?quick=this_month" class="btn btn-sm {'btn-primary' if active_month == current_month else 'btn-secondary'}" style="padding:2px 8px; font-size:11px;">This Month</a>
            <a href="/expenses?quick=last_month" class="btn btn-sm btn-secondary" style="padding:2px 8px; font-size:11px;">Last Month</a>
          </div>
        </div>
        <div class="table-responsive" style="max-height:480px; overflow-y:auto;">
          <table class="data-table" id="expenses-table">
            <thead><tr><th>Date</th><th>Category</th><th>Description</th><th>Amount</th><th>Account</th></tr></thead>
            <tbody>{exp_rows or '<tr><td colspan="5" style="text-align:center; color:#888; padding:24px;">No expenses recorded for this month</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      function filterExpensesTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.exp-row').forEach(r => {{
          const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Expenses", content, "expenses", user)

@app.route("/expenses/create", method="POST")
def create_expense_route():
    user = require_admin()
    cat = request.forms.get("category")
    amt = float(request.forms.get("amount", 0))
    desc = request.forms.get("description", "")
    pm = request.forms.get("payment_method", "CASH")
    exp_date = request.forms.get("expense_date", "").strip() or None
    accounting.record_expense(cat, amt, description=desc, payment_method=pm, expense_date=exp_date, user_id=user["id"], username=user["username"])
    return redirect("/expenses")

@app.route("/expenses/export.csv")
def expenses_export_csv():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]
    month = request.query.get("month", current_month).strip()
    category = request.query.get("category", "").strip() or None

    summary = accounting.get_month_expenses_summary(month, category=category)
    exps = summary.get("expenses", [])

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Expense ID", "Date", "Category", "Description", "Amount (PKR)", "Payment Method", "Account Type", "Logged By", "Timestamp"])
    for e in exps:
        acct_type = "Cash Drawer" if e.get("is_cash") else "Bank / Online"
        writer.writerow([
            e.get("id", ""),
            e.get("expense_date", ""),
            e.get("category", ""),
            e.get("description", ""),
            f"{float(e.get('amount') or 0):.2f}",
            e.get("payment_method", ""),
            acct_type,
            e.get("username", "") or "Admin",
            e.get("created_at", "")
        ])
    writer.writerow([])
    writer.writerow(["TOTAL EXPENSES", f"{summary['total_expenses']:.2f}"])
    writer.writerow(["DRAWER CASH EXPENSES", f"{summary['cash_expenses']:.2f}"])
    writer.writerow(["BANK / ONLINE EXPENSES", f"{summary['non_cash_expenses']:.2f}"])

    csv_data = output.getvalue()
    response.content_type = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="expenses_{month}.csv"'
    return csv_data

@app.route("/print/expenses")
def print_expenses_route():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]
    month = request.query.get("month", current_month).strip()
    category = request.query.get("category", "").strip() or None
    start_d, end_d = get_month_date_range(month)
    return printing.render_monthly_expenses_report(start_d, end_d, category=category)

# ═══════════════════════════════════════════════════════════
# REPORTS & EARNINGS CENTER
# ═══════════════════════════════════════════════════════════

@app.route("/reports")
@app.route("/reports/pnl")
def reports_screen():
    user = require_admin()
    now = datetime.now()
    earnings = accounting.get_earnings_center()
    m_rep = accounting.get_monthly_report(now.year, now.month)

    content = f"""
    <div class="card" style="margin-bottom:16px;">
      <div class="card-header">
        <div class="card-title">📊 5-Stream Earnings Center Overview</div>
        <div style="display:flex; gap:8px;">
          <a href="/reports/top-sellers" class="btn btn-warning btn-sm">🔥 Top-Selling Products & Velocity</a>
          <a href="/print/monthly-report/{now.year}/{now.month}" target="_blank" class="btn btn-primary btn-sm">🖨️ Print A4 Monthly Statement</a>
        </div>
      </div>

      <table class="data-table" style="font-size:13.5px;">
        <thead>
          <tr><th>Revenue Stream</th><th style="text-align:right;">Volume / Sold</th><th style="text-align:right;">Total Revenue</th><th style="text-align:right;">Net Profit</th></tr>
        </thead>
        <tbody>
          <tr><td><strong>1. Phone Retail Sales</strong></td><td style="text-align:right;">{earnings['stream1_phones']['units_sold']} units</td><td style="text-align:right;">Rs. {earnings['stream1_phones']['revenue']:,.0f}</td><td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {earnings['stream1_phones']['profit']:,.0f}</td></tr>
          <tr><td><strong>2. Accessories & Tempered Glass</strong></td><td style="text-align:right;">{earnings['stream2_accessories']['items_sold']} items</td><td style="text-align:right;">Rs. {earnings['stream2_accessories']['revenue']:,.0f}</td><td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {earnings['stream2_accessories']['profit']:,.0f}</td></tr>
          <tr><td><strong>3. Hardware Repair Workshop</strong></td><td style="text-align:right;">{earnings['stream3_repairs']['jobs_delivered']} jobs</td><td style="text-align:right;">Rs. {earnings['stream3_repairs']['revenue']:,.0f}</td><td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {earnings['stream3_repairs']['profit']:,.0f}</td></tr>
          <tr><td><strong>4. Software Lab Services</strong></td><td style="text-align:right;">{earnings['stream4_software']['tickets_completed']} tickets</td><td style="text-align:right;">Rs. {earnings['stream4_software']['revenue']:,.0f}</td><td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {earnings['stream4_software']['profit']:,.0f}</td></tr>
          <tr><td><strong>5. Quick Services (Load / EasyPaisa)</strong></td><td style="text-align:right;">{earnings['stream5_quick_services']['transactions']} trans</td><td style="text-align:right;">Rs. {earnings['stream5_quick_services']['volume']:,.0f}</td><td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {earnings['stream5_quick_services']['profit']:,.0f}</td></tr>
          <tr style="background:rgba(255,255,255,0.05); font-weight:bold;">
            <td>TOTAL GROSS PROFIT</td><td></td><td></td><td style="text-align:right; color:#34d399; font-size:16px;">Rs. {earnings['total_gross_profit']:,.0f}</td>
          </tr>
          <tr>
            <td>Less Total Business Expenses</td><td></td><td></td><td style="text-align:right; color:#f87171; font-weight:bold;">- Rs. {earnings['total_expenses']:,.0f}</td>
          </tr>
          <tr style="background:rgba(16,185,129,0.15); font-size:16px; font-weight:800;">
            <td>NET CLEAR PROFIT</td><td></td><td></td><td style="text-align:right; color:#34d399;">Rs. {earnings['net_profit']:,.0f}</td>
          </tr>
        </tbody>
      </table>
    </div>
    """
    return layout("Reports", content, "reports", user)

@app.route("/reports/top-sellers")
def top_sellers_screen():
    user = require_admin()
    is_admin = True

    period = request.query.get("period", "this_month")
    category = request.query.get("category", "All")
    brand = request.query.get("brand", "All")
    sort_by = request.query.get("sort_by", "units")
    limit = safe_int(request.query.get("limit", 50), default=50)
    custom_start = request.query.get("custom_start")
    custom_end = request.query.get("custom_end")

    report = top_sellers.get_top_sellers_report(
        period=period, category=category, brand=brand, sort_by=sort_by,
        limit=limit, is_admin=is_admin, custom_start=custom_start, custom_end=custom_end
    )

    periods = [
        ("today", "Today"),
        ("yesterday", "Yesterday"),
        ("7days", "Last 7 Days"),
        ("30days", "Last 30 Days"),
        ("this_month", "This Month"),
        ("last_month", "Last Month")
    ]
    period_chips = ""
    for p_val, p_lbl in periods:
        act = "btn-primary" if period == p_val else "btn-secondary"
        period_chips += f'<a href="/reports/top-sellers?period={p_val}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by={sort_by}" class="btn btn-sm {act}">{p_lbl}</a> '

    cat_chips = f'<a href="/reports/top-sellers?period={period}&category=All&brand={urllib.parse.quote(brand)}&sort_by={sort_by}" class="btn btn-sm {"btn-primary" if category == "All" else "btn-secondary"}">All Categories</a> '
    for c in report["available_categories"]:
        act = "btn-primary" if category == c else "btn-secondary"
        cat_chips += f'<a href="/reports/top-sellers?period={period}&category={urllib.parse.quote(c)}&brand={urllib.parse.quote(brand)}&sort_by={sort_by}" class="btn btn-sm {act}">{c}</a> '

    sort_tabs = f'<a href="/reports/top-sellers?period={period}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by=units" class="btn btn-sm {"btn-warning" if sort_by == "units" else "btn-secondary"}">⚡ By Units Sold</a> '
    if is_admin:
        sort_tabs += f'<a href="/reports/top-sellers?period={period}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by=revenue" class="btn btn-sm {"btn-warning" if sort_by == "revenue" else "btn-secondary"}">💰 By Gross Revenue</a> '
        sort_tabs += f'<a href="/reports/top-sellers?period={period}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by=profit" class="btn btn-sm {"btn-warning" if sort_by == "profit" else "btn-secondary"}">📈 By Net Profit</a> '

    kpi_cards = f"""
    <div class="grid-4" style="margin-bottom:16px;">
      <div class="card" style="padding:12px; border-left:4px solid #3b82f6;">
        <div style="font-size:11px; color:var(--text-muted); font-weight:bold;">TOTAL UNITS SOLD</div>
        <div style="font-size:22px; font-weight:800; color:#38bdf8; margin-top:2px;">{report['total_net_units']} Units</div>
      </div>
    """
    if is_admin:
        kpi_cards += f"""
      <div class="card" style="padding:12px; border-left:4px solid #10b981;">
        <div style="font-size:11px; color:var(--text-muted); font-weight:bold;">GROSS REVENUE</div>
        <div style="font-size:22px; font-weight:800; color:#34d399; margin-top:2px;">Rs. {report['total_revenue']:,.0f}</div>
      </div>
      <div class="card" style="padding:12px; border-left:4px solid #ec4899;">
        <div style="font-size:11px; color:var(--text-muted); font-weight:bold;">NET CLEAR PROFIT</div>
        <div style="font-size:22px; font-weight:800; color:#f472b6; margin-top:2px;">Rs. {report['total_profit']:,.0f}</div>
      </div>
      <div class="card" style="padding:12px; border-left:4px solid #8b5cf6;">
        <div style="font-size:11px; color:var(--text-muted); font-weight:bold;">AVERAGE PROFIT MARGIN</div>
        <div style="font-size:22px; font-weight:800; color:#c084fc; margin-top:2px;">{report['overall_margin_percent']}%</div>
      </div>
        """
    kpi_cards += "</div>"

    rows_html = ""
    for idx, it in enumerate(report["items"], 1):
        st = it.get("alert_state", "OK")
        if st == "OUT":
            stock_badge = '<span class="badge badge-danger">OUT OF STOCK (0)</span>'
        elif st == "LOW":
            stock_badge = f'<span class="badge badge-warning">LOW ({it["current_stock"]})</span>'
        else:
            stock_badge = f'<span class="badge badge-success">{it["current_stock"]} in stock</span>'

        on_ord = f'<br><span class="badge badge-info" style="font-size:9.5px; margin-top:2px;">📦 {it["on_order_qty"]} on order</span>' if it.get("on_order_qty", 0) > 0 else ""

        row_tds = f"""
        <tr>
          <td style="text-align:center; font-weight:bold; color:var(--text-muted);">{idx}</td>
          <td>
            <strong>{it['brand']} {it['model_name']}</strong>
            <div style="font-size:11px; color:#94a3b8;">{it['specs'] or it['category']} &bull; <code>{it['barcode'] or f"VAR-{it['variant_id']}"}</code></div>
          </td>
          <td><span class="badge badge-secondary">{it['category']}</span></td>
          <td style="text-align:center;">{stock_badge}{on_ord}</td>
          <td style="text-align:center; font-weight:800; font-size:14px; color:#38bdf8;">{it['net_units_sold']}</td>
          <td style="text-align:center; color:#94a3b8;">{it['units_returned']}</td>
        """
        if is_admin:
            row_tds += f"""
          <td style="text-align:right; font-weight:bold;">Rs. {it['gross_revenue']:,.0f}</td>
          <td style="text-align:right; color:#34d399; font-weight:bold;">Rs. {it['net_profit']:,.0f}</td>
          <td style="text-align:center; font-weight:bold; color:#fbbf24;">{it['margin_percent']}%</td>
          <td style="text-align:center; font-weight:bold; color:#38bdf8;">{it['reorder_suggestion']}</td>
          <td style="text-align:center;">
            <a href="/purchasing" class="btn btn-xs btn-primary">+ Reorder</a>
          </td>
            """
        row_tds += "</tr>"
        rows_html += row_tds

    admin_cols_head = """
      <th style="text-align:right;">Gross Revenue</th>
      <th style="text-align:right;">Net Profit</th>
      <th style="text-align:center;">Margin %</th>
      <th style="text-align:center;">Reorder Adv.</th>
      <th style="text-align:center;">Action</th>
    """ if is_admin else ""

    print_url = f"/print/top-sellers-report?period={period}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by={sort_by}"
    csv_url = f"/reports/top-sellers/export.csv?period={period}&category={urllib.parse.quote(category)}&brand={urllib.parse.quote(brand)}&sort_by={sort_by}"

    content = f"""
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
      <div>
        <h1 style="font-size:22px; font-weight:800; color:var(--text); margin-bottom:4px;">🔥 Top-Selling Products & Reorder Intelligence</h1>
        <div style="font-size:12.5px; color:var(--text-muted);">
          Sales velocity aggregated from live registers &bull; Period: {report['start_date']} to {report['end_date']}
        </div>
      </div>
      <div style="display:flex; gap:8px;">
        <a href="{print_url}" target="_blank" class="btn btn-secondary btn-sm">🖨️ Print A4 Report</a>
        <a href="{csv_url}" class="btn btn-success btn-sm">📥 Export CSV</a>
        <a href="/reports" class="btn btn-secondary btn-sm">📊 All Reports</a>
      </div>
    </div>

    <!-- Period Filter Chips -->
    <div class="card" style="padding:10px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
      <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
        <span style="font-size:11px; font-weight:bold; color:var(--text-muted); margin-right:4px;">PERIOD:</span>
        {period_chips}
      </div>
      <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
        <span style="font-size:11px; font-weight:bold; color:var(--text-muted); margin-right:4px;">SORT BY:</span>
        {sort_tabs}
      </div>
    </div>

    <!-- Category Chips -->
    <div class="card" style="padding:10px; margin-bottom:16px;">
      <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
        <span style="font-size:11px; font-weight:bold; color:var(--text-muted); margin-right:4px;">CATEGORIES:</span>
        {cat_chips}
      </div>
    </div>

    <!-- KPI Summary Cards -->
    {kpi_cards}

    <!-- Top Sellers Table -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">Top Sellers Leaderboard ({len(report['items'])} items ranked by {sort_by.upper()})</div>
      </div>
      <div class="table-responsive">
        <table class="data-table" style="font-size:13px;">
          <thead>
            <tr>
              <th style="width:36px; text-align:center;">#</th>
              <th>Product & Specifications</th>
              <th>Category</th>
              <th style="text-align:center;">Stock Status</th>
              <th style="text-align:center;">Net Sold</th>
              <th style="text-align:center;">Returns</th>
              {admin_cols_head}
            </tr>
          </thead>
          <tbody>
            {rows_html or '<tr><td colspan="11" style="text-align:center; padding:36px; color:#94a3b8;">No sales activity recorded for this period & filters.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """
    return layout("Top Sellers & Velocity", content, "top_sellers", user)

@app.route("/reports/top-sellers/export.csv")
def top_sellers_export_csv():
    user = require_admin()
    is_admin = True
    period = request.query.get("period", "this_month")
    category = request.query.get("category", "All")
    brand = request.query.get("brand", "All")
    sort_by = request.query.get("sort_by", "units")

    report = top_sellers.get_top_sellers_report(
        period=period, category=category, brand=brand, sort_by=sort_by,
        limit=500, is_admin=is_admin
    )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)

    header = ["Rank", "Brand", "Model Name", "Category", "Specs", "Barcode", "Current Stock", "Stock Status", "Units Sold", "Units Returned", "Net Units Sold"]
    if is_admin:
        header.extend(["Gross Revenue (Rs)", "Total Cost (Rs)", "Net Profit (Rs)", "Margin %", "Suggested Reorder Qty", "Days Stock Left", "Last Supplier", "Last Cost (Rs)"])
    writer.writerow(header)

    for idx, it in enumerate(report["items"], 1):
        row = [
            idx, it["brand"], it["model_name"], it["category"], it["specs"],
            it["barcode"], it["current_stock"], it["alert_state"],
            it["net_units_sold"] + it["units_returned"], it["units_returned"], it["net_units_sold"]
        ]
        if is_admin:
            row.extend([
                it["gross_revenue"], it["cost_total"], it["net_profit"],
                it["margin_percent"], it["reorder_suggestion"],
                it["days_left"] or "", it.get("last_supplier_name", ""), it.get("last_cost", 0)
            ])
        writer.writerow(row)

    csv_data = output.getvalue()
    response.content_type = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="top_sellers_{period}.csv"'
    return csv_data

@app.route("/print/top-sellers-report")
def print_top_sellers_report():
    user = require_admin()
    period = request.query.get("period", "this_month")
    category = request.query.get("category", "All")
    brand = request.query.get("brand", "All")
    sort_by = request.query.get("sort_by", "units")

    report = top_sellers.get_top_sellers_report(
        period=period, category=category, brand=brand, sort_by=sort_by,
        limit=100, is_admin=True
    )
    return printing.render_a4_top_sellers_report(report)


# ═══════════════════════════════════════════════════════════
# DAY CLOSING (Z-REPORT)
# ═══════════════════════════════════════════════════════════

@app.route("/day-closing")
def day_closing_screen():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]

    view = request.query.get("view", "").strip()
    req_month = request.query.get("month", "").strip()
    target_date = request.query.get("date", "").strip() or today

    if view == "month" or req_month:
        active_month = req_month or current_month
        m_data = accounting.get_month_day_closings(active_month)
        tot = m_data["totals"]
        days = m_data["days"]

        diff_tot = tot["cash_difference"]
        diff_color = "#10b981" if diff_tot >= 0 else "#ef4444"

        month_rows_html = ""
        for d in days:
            st_badge = '<span class="badge badge-success">CLOSED</span>' if d["is_closed"] else '<span class="badge badge-warning">OPEN</span>'
            diff_style = f"color:{'#10b981' if d['difference'] >= 0 else '#ef4444'}; font-weight:bold;"
            act_disp = f"Rs. {d['actual_cash']:,.0f}" if d["is_closed"] else "-"
            diff_disp = f"Rs. {d['difference']:+,.0f}" if d["is_closed"] else "-"
            
            actions = f"""
              <a href="/day-closing?date={d['date']}" class="btn btn-secondary btn-sm" style="padding:2px 8px; font-size:11px;">Reconcile</a>
            """
            if d["is_closed"]:
                actions += f"""
                  <a href="/print/day-closing/{d['date']}" target="_blank" class="btn btn-primary btn-sm" style="padding:2px 8px; font-size:11px; margin-left:4px;">Z-Report</a>
                """

            month_rows_html += f"""
            <tr>
              <td><strong>{d['date']}</strong></td>
              <td>{st_badge}</td>
              <td style="text-align:right;">Rs. {d['opening_cash']:,.0f}</td>
              <td style="text-align:right; color:#34d399; font-weight:600;">Rs. {d['inflow']:,.0f}</td>
              <td style="text-align:right; color:#f87171;">Rs. {d['expenses']:,.0f}</td>
              <td style="text-align:right;">Rs. {d['expected_cash']:,.0f}</td>
              <td style="text-align:right; font-weight:bold;">{act_disp}</td>
              <td style="text-align:right; {diff_style}">{diff_disp}</td>
              <td>{d['closed_by'] or '-'}</td>
              <td style="text-align:right;">{actions}</td>
            </tr>
            """

        content = f"""
        <div style="max-width:1100px; margin:0 auto;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
            <div>
              <div style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
                <a href="/day-closing?date={today}" class="btn btn-secondary btn-sm">🔒 Today's Day Closing</a>
                <a href="/day-closing?view=month&month={active_month}" class="btn btn-primary btn-sm font-weight-bold">📅 Monthly Closing History & Audit</a>
              </div>
              <h2 style="margin:0; font-size:1.3rem; color:var(--text, #f8fafc);">📅 Monthly Closing History — {active_month}</h2>
              <div style="font-size:12px; color:#94a3b8;">Complete calendar audit, cash drawer reconciliations, and variance analysis</div>
            </div>
            <div style="display:flex; gap:8px; align-items:center;">
              <form method="GET" action="/day-closing" style="margin:0;">
                <input type="hidden" name="view" value="month">
                <input type="month" name="month" value="{active_month}" class="form-control" style="width:140px; padding:4px 8px; font-size:12px; font-weight:bold;" onchange="this.form.submit()">
              </form>
              <a href="/day-closing/export.csv?month={active_month}" class="btn btn-secondary btn-sm font-weight-bold">📥 Export CSV / Excel</a>
              <a href="/print/day-closing-monthly?month={active_month}" target="_blank" class="btn btn-primary btn-sm font-weight-bold">🖨️ Print Monthly Report</a>
            </div>
          </div>

          <!-- 4 Monthly KPI Cards -->
          <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin-bottom:16px;">
            <div class="card" style="padding:14px; background:rgba(16,185,129,0.08); border-left:4px solid #10b981;">
              <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Month Cash Inflow</div>
              <div style="font-size:1.4rem; font-weight:800; color:#34d399; margin-top:4px;">Rs. {tot['total_cash_in']:,.0f}</div>
              <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Sales + Udhaar collections + Services</div>
            </div>
            <div class="card" style="padding:14px; background:rgba(244,63,94,0.08); border-left:4px solid #f43f5e;">
              <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Drawer Cash Expenses</div>
              <div style="font-size:1.4rem; font-weight:800; color:#f87171; margin-top:4px;">Rs. {tot['expenses_total']:,.0f}</div>
              <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Direct cash paid out from counter</div>
            </div>
            <div class="card" style="padding:14px; background:rgba(59,130,246,0.08); border-left:4px solid #3b82f6;">
              <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Days Audited</div>
              <div style="font-size:1.4rem; font-weight:800; color:#60a5fa; margin-top:4px;">{tot['closed_count']} Closed / {tot['open_count']} Open</div>
              <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Across {tot['days_count']} calendar days</div>
            </div>
            <div class="card" style="padding:14px; background:rgba(255,255,255,0.03); border-left:4px solid {diff_color};">
              <div style="font-size:11.5px; color:#94a3b8; font-weight:600; text-transform:uppercase;">Reconciled Cash Variance</div>
              <div style="font-size:1.4rem; font-weight:800; color:{diff_color}; margin-top:4px;">Rs. {diff_tot:+,.0f}</div>
              <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Counted cash vs Expected in closed days</div>
            </div>
          </div>

          <!-- Calendar Table -->
          <div class="card">
            <div class="table-responsive">
              <table class="data-table" style="font-size:12.5px;">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Status</th>
                    <th style="text-align:right;">Opening Cash</th>
                    <th style="text-align:right;">Total Inflow</th>
                    <th style="text-align:right;">Cash Expenses</th>
                    <th style="text-align:right;">Expected Cash</th>
                    <th style="text-align:right;">Actual Counted</th>
                    <th style="text-align:right;">Difference</th>
                    <th>Closed By</th>
                    <th style="text-align:right;">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {month_rows_html}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        """
        return layout("Monthly Closings", content, "closing", user)

    data = accounting.get_day_closing_data(target_date)

    exp_items_html = ""
    if data.get("expenses_list"):
        for ex in data["expenses_list"]:
            badge = '<span class="badge badge-danger" style="font-size:10.5px;">💵 Drawer Cash</span>' if ex.get("is_cash") else '<span class="badge badge-info" style="font-size:10.5px;">🏦 Bank / Wallet</span>'
            exp_items_html += f"<tr><td><strong>{ex['category']}</strong></td><td>{ex['description'] or '-'}</td><td style='text-align:right; font-weight:bold; color:#f87171;'>Rs. {ex['amount']:,.0f}</td><td>{ex['payment_method']}</td><td>{badge}</td></tr>"

        cat_summary_chips = " ".join(
            f"<span style='background:rgba(255,255,255,0.06); padding:2px 8px; border-radius:12px; font-size:11px; margin-right:4px;'>"
            f"<strong>{c['category']}:</strong> Rs. {c['total']:,.0f}</span>"
            for c in data["expenses_by_category"]
        )

        exp_box = f"""
        <div style="margin-bottom:16px; background:rgba(244,63,94,0.08); border:1px solid rgba(244,63,94,0.3); border-radius:8px; padding:12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:8px;">
            <strong style="color:#f87171; font-size:13px;">💸 Shop Expenses for {target_date} ({len(data['expenses_list'])})</strong>
            <div style="font-size:12px;">
              <span style="color:#f87171; font-weight:bold;">Drawer Cash: Rs. {data['cash_expenses_total']:,.0f}</span> | 
              <span style="color:#38bdf8; font-weight:bold;">Bank/Wallet: Rs. {data['non_cash_expenses_total']:,.0f}</span> | 
              <span style="font-weight:800; color:#cbd5e1;">Total: Rs. {data['total_expenses']:,.0f}</span>
            </div>
          </div>
          <div style="margin-bottom:8px;">{cat_summary_chips}</div>
          <table class="data-table" style="font-size:12px; margin-bottom:0;">
            <thead><tr><th>Category</th><th>Description</th><th style="text-align:right;">Amount</th><th>Account</th><th>Effect</th></tr></thead>
            <tbody>{exp_items_html}</tbody>
          </table>
        </div>
        """
    else:
        exp_box = f"""
        <div style="margin-bottom:14px; padding:8px 12px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px; font-size:12px; color:#94a3b8; display:flex; justify-content:space-between; align-items:center;">
          <span>No shop expenses recorded for <strong>{target_date}</strong>.</span>
          <a href="/expenses" class="btn btn-sm btn-outline-primary" style="padding:2px 8px; font-size:11px;">+ Record Expense</a>
        </div>
        """

    saved_act = data["existing_record"]["actual_cash"] if data.get("existing_record") else data["expected_cash"]
    saved_diff = data["existing_record"]["cash_difference"] if data.get("existing_record") else 0.0
    status_label = "CLOSED" if data.get("existing_record") else "OPEN (UNSAVED)"
    status_color = "#10b981" if data.get("existing_record") else "#f59e0b"

    content = f"""
    <div class="card" style="max-width:760px; margin:0 auto;">
      <div class="card-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <div>
          <div class="card-title">🔒 Daily Closing & Cash Drawer Reconciliation (Z-Report)</div>
          <div style="font-size:11.5px; color:#94a3b8;">
            Date: <strong>{target_date}</strong> &bull; Status: <span style="color:{status_color}; font-weight:bold;">{status_label}</span>
          </div>
        </div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <a href="/day-closing?view=month&month={target_date[:7]}" class="btn btn-secondary btn-sm">📅 Monthly History</a>
          <input type="date" value="{target_date}" class="form-control" style="width:140px; padding:4px 8px; font-size:12px; font-weight:bold;" onchange="location.href='/day-closing?date='+this.value">
          <a href="/sales?date={target_date}" class="btn btn-secondary btn-sm">📊 Day's Sales</a>
          <a href="/print/day-closing/{target_date}" target="_blank" class="btn btn-secondary btn-sm">🖨️ Z-Report</a>
          <a href="/print/daily-sales?start_date={target_date}&end_date={target_date}" target="_blank" class="btn btn-primary btn-sm font-weight-bold">🖨️ Full Day Audit (Sales + Items + Expenses)</a>
        </div>
      </div>

      <form method="POST" action="/day-closing/submit">
        <input type="hidden" name="closing_date" value="{target_date}">
        
        <!-- Drawer Cash Inflows Table -->
        <table class="data-table" style="font-size:13px; margin-bottom:12px;">
          <tr style="background:rgba(255,255,255,0.02);"><th colspan="2" style="font-size:11.5px; text-transform:uppercase; color:#38bdf8;">1. Drawer Cash Inflows</th></tr>
          <tr><td>Opening Cash in Drawer:</td><td style="text-align:right;"><input type="number" id="inp-opening-cash" name="opening_cash" class="form-control" value="{data['opening_cash']}" style="width:120px; text-align:right; display:inline-block;" oninput="recalcReconciliation()"></td></tr>
          <tr><td>POS Cash Sales:</td><td style="text-align:right; font-weight:bold;">Rs. {data['cash_sales']:,.0f}</td></tr>
          <tr><td>Udhaar Collected (Cash):</td><td style="text-align:right; font-weight:bold;">Rs. {data['udhaar_received']:,.0f}</td></tr>
          <tr><td>Repairs Income (Cash):</td><td style="text-align:right; font-weight:bold;">Rs. {data['repair_income']:,.0f}</td></tr>
          <tr><td>Software Services (Cash):</td><td style="text-align:right; font-weight:bold;">Rs. {data['software_income']:,.0f}</td></tr>
          <tr><td>Quick Services Commission:</td><td style="text-align:right; font-weight:bold;">Rs. {data['quick_service_income']:,.0f}</td></tr>
          <tr style="font-weight:bold; border-top:1px solid var(--border);">
            <td>Total Cash Inflow:</td>
            <td style="text-align:right; color:#34d399;">+ Rs. {data['total_cash_in']:,.0f}</td>
          </tr>
        </table>

        <!-- Drawer Cash Outflows Table -->
        <table class="data-table" style="font-size:13px; margin-bottom:14px;">
          <tr style="background:rgba(255,255,255,0.02);"><th colspan="2" style="font-size:11.5px; text-transform:uppercase; color:#f87171;">2. Drawer Cash Outflows</th></tr>
          <tr style="color:#f87171;"><td>Less Shop Expenses Paid (Cash Drawer):</td><td style="text-align:right; font-weight:bold;">- Rs. {data['cash_expenses_total']:,.0f}</td></tr>
          <tr style="color:#f87171;"><td>Less Supplier Payments (Cash):</td><td style="text-align:right; font-weight:bold;">- Rs. {data['supplier_payments']:,.0f}</td></tr>
          <tr style="color:#f87171;"><td>Less Customer Refunds / Returns (Cash):</td><td style="text-align:right; font-weight:bold;">- Rs. {data['refunds']:,.0f}</td></tr>
          <tr style="font-weight:bold; border-top:1px solid var(--border);">
            <td>Total Cash Outflow:</td>
            <td style="text-align:right; color:#f87171;">- Rs. {data['total_cash_out']:,.0f}</td>
          </tr>
          <tr style="background:rgba(59,130,246,0.18); font-size:15px; font-weight:800;">
            <td style="color:#93c5fd;">EXPECTED DRAWER CASH:</td>
            <td style="text-align:right; color:#60a5fa;" id="disp-expected-cash">Rs. {data['expected_cash']:,.0f}</td>
          </tr>
        </table>

        {exp_box}

        <!-- Non-Cash Summary Bar -->
        <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:8px; padding:10px 14px; margin-bottom:16px; font-size:12px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;">
          <div><strong style="color:#94a3b8;">Non-Cash Activity:</strong></div>
          <div>Card: <strong>Rs. {data['card_sales']:,.0f}</strong></div>
          <div>Bank/Online: <strong>Rs. {data['online_sales']:,.0f}</strong></div>
          <div>New Credit: <strong>Rs. {data['udhaar_sales']:,.0f}</strong></div>
          <div>Non-Cash Expenses: <strong>Rs. {data['non_cash_expenses_total']:,.0f}</strong></div>
        </div>

        <!-- Counted Cash & Live Difference -->
        <div style="background:rgba(15,23,42,0.6); border:1px solid var(--border); border-radius:8px; padding:14px; margin-bottom:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div style="flex:1; min-width:220px;">
              <label class="form-label" style="font-size:13px; font-weight:bold;">Actual Cash Counted in Drawer (Rs.)</label>
              <input type="number" id="inp-actual-cash" name="actual_cash" class="form-control" value="{saved_act}" style="font-size:18px; font-weight:bold; color:#34d399;" required oninput="recalcReconciliation()">
            </div>
            <div style="text-align:right; min-width:180px;">
              <div style="font-size:11.5px; color:#94a3b8; text-transform:uppercase; font-weight:bold;">Reconciliation Difference</div>
              <div id="disp-diff" style="font-size:20px; font-weight:800; color:{'#10b981' if saved_diff >= 0 else '#ef4444'}; margin-top:2px;">
                Rs. {saved_diff:+,.0f}
              </div>
              <div id="disp-diff-status" style="font-size:11px; font-weight:bold; color:#94a3b8;">
                {'BALANCED' if saved_diff == 0 else ('SURPLUS' if saved_diff > 0 else 'SHORTAGE')}
              </div>
            </div>
          </div>
        </div>

        <button type="submit" class="btn btn-success" style="width:100%; padding:14px; font-size:15.5px; font-weight:bold;">
          Save Official Day Closing ({target_date}) & Print Z-Report
        </button>
      </form>
    </div>

    <script>
      const totalCashIn = {data['total_cash_in']};
      const totalCashOut = {data['total_cash_out']};

      function recalcReconciliation() {{
        const op = parseFloat(document.getElementById('inp-opening-cash').value) || 0;
        const act = parseFloat(document.getElementById('inp-actual-cash').value) || 0;
        const expected = op + totalCashIn - totalCashOut;
        const diff = act - expected;

        document.getElementById('disp-expected-cash').innerText = 'Rs. ' + expected.toLocaleString();
        const diffEl = document.getElementById('disp-diff');
        const statusEl = document.getElementById('disp-diff-status');

        diffEl.innerText = (diff >= 0 ? '+Rs. ' : '-Rs. ') + Math.abs(diff).toLocaleString();
        if (diff === 0) {{
          diffEl.style.color = '#10b981';
          statusEl.innerText = 'BALANCED (Drawer Exact)';
          statusEl.style.color = '#10b981';
        }} else if (diff > 0) {{
          diffEl.style.color = '#38bdf8';
          statusEl.innerText = 'SURPLUS (Extra Cash)';
          statusEl.style.color = '#38bdf8';
        }} else {{
          diffEl.style.color = '#ef4444';
          statusEl.innerText = 'SHORTAGE (Missing Cash)';
          statusEl.style.color = '#ef4444';
        }}
      }}
    </script>
    """
    return layout("Day Closing", content, "closing", user)

@app.route("/day-closing/submit", method="POST")
def day_closing_submit():
    user = require_admin()
    op = float(request.forms.get("opening_cash", 0))
    act = float(request.forms.get("actual_cash", 0))
    today = datetime.now().strftime("%Y-%m-%d")
    cdate = request.forms.get("closing_date", "").strip() or today
    accounting.record_day_closing(actual_cash=act, opening_cash=op, closing_date=cdate, user_id=user["id"], username=user["username"])
    return redirect(f"/print/day-closing/{cdate}")

@app.route("/day-closing/export.csv")
def day_closing_export_csv():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]
    month = request.query.get("month", current_month).strip()

    m_data = accounting.get_month_day_closings(month)
    tot = m_data["totals"]
    days = m_data["days"]

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Status", "Opening Cash", "Cash Sales", "Udhaar Collected", "Services Cash", "Total Inflow", "Cash Expenses", "Supplier Payments", "Total Outflow", "Expected Cash", "Actual Counted", "Difference", "Closed By", "Closed At"])
    for d in days:
        writer.writerow([
            d["date"],
            d["status"],
            f"{d['opening_cash']:.2f}",
            f"{d['cash_sales']:.2f}",
            f"{d['udhaar_received']:.2f}",
            f"{d['services_cash']:.2f}",
            f"{d['inflow']:.2f}",
            f"{d['expenses']:.2f}",
            f"{d['supplier_payments']:.2f}",
            f"{d['outflow']:.2f}",
            f"{d['expected_cash']:.2f}",
            f"{d['actual_cash']:.2f}" if d["is_closed"] else "",
            f"{d['difference']:.2f}" if d["is_closed"] else "",
            d["closed_by"],
            d["closed_at"]
        ])
    writer.writerow([])
    writer.writerow(["TOTALS", f"{tot['closed_count']} Closed / {tot['open_count']} Open", "", f"{tot['sales_cash']:.2f}", f"{tot['udhaar_received']:.2f}", f"{tot['services_cash']:.2f}", f"{tot['total_cash_in']:.2f}", f"{tot['expenses_total']:.2f}", "", f"{tot['total_cash_out']:.2f}", f"{tot['expected_cash']:.2f}", f"{tot['actual_cash']:.2f}", f"{tot['cash_difference']:.2f}"])

    csv_data = output.getvalue()
    response.content_type = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="day_closings_{month}.csv"'
    return csv_data

@app.route("/print/day-closing-monthly")
def print_day_closing_monthly_route():
    user = require_admin()
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]
    month = request.query.get("month", current_month).strip()
    return printing.render_monthly_closing_report(month, is_admin=True)

# ═══════════════════════════════════════════════════════════
# SETTINGS & HARDWARE TEST SCREENS
# ═══════════════════════════════════════════════════════════

@app.route("/settings")
def settings_screen():
    user = require_admin()
    shop = printing.get_shop_info()

    content = f"""
    <div style="max-width:920px; margin:0 auto;">
      <div style="display:flex; gap:8px; margin-bottom:16px;">
        <a href="/settings" class="btn btn-primary">⚙️ Shop & Profile</a>
        <a href="/settings/users" class="btn btn-secondary">👥 Users & Permissions</a>
        <a href="/settings/lookups" class="btn btn-secondary">📋 Lists & Categories</a>
        <a href="/settings/scanner-test" class="btn btn-secondary">🔬 USB Scanner Diagnostics</a>
        <a href="/settings/diagnostics" class="btn btn-secondary">🩺 System Health</a>
      </div>

      <div class="card" style="margin-bottom:18px;">
        <div class="card-title" style="margin-bottom:12px;">🖼️ Shop Logo (Receipt & Top Bar)</div>
        <div style="display:flex; align-items:center; gap:20px;">
          <div id="logo-preview-box" style="border:2px dashed var(--card-border); border-radius:8px; padding:12px; min-width:180px; min-height:80px; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.1);">
            {'<img src="/api/shop/logo?v=' + str(shop["profile_version"]) + '" style="max-height:64px; max-width:180px; object-fit:contain;" alt="Current Logo">' if shop.get("has_logo") else '<span style="color:var(--text-muted); font-size:12px;">No Logo Uploaded</span>'}
          </div>
          <div style="flex:1;">
            <p style="color:var(--text-muted); font-size:12.5px; margin-bottom:10px;">
              Upload PNG or JPG image (Max 5MB). Automatically processed into Web UI logo and 1-bit monochrome ESC-POS thermal receipt bitmaps for 80mm & 58mm printers.
            </p>
            <div style="display:flex; gap:10px;">
              <input type="file" id="logo-upload-input" accept="image/png,image/jpeg,image/webp" style="display:none;" onchange="handleLogoUpload(this)">
              <button type="button" class="btn btn-primary btn-sm" onclick="document.getElementById('logo-upload-input').click()">📁 Choose Logo Image</button>
              {'''<button type="button" class="btn btn-danger btn-sm" onclick="handleRemoveLogo()">🗑️ Remove Logo</button>''' if shop.get("has_logo") else ''}
            </div>
            <div id="logo-upload-msg" style="margin-top:8px; font-size:12px;"></div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom:12px;">⚙️ Shop Identity & Hardware Configuration</div>
        <form method="POST" action="/settings/save">
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Shop Name *</label>
              <input type="text" name="shop_name" class="form-control" value="{shop['name']}" required>
            </div>
            <div class="form-group">
              <label class="form-label">Tagline</label>
              <input type="text" name="tagline" class="form-control" value="{shop['tagline']}">
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Primary Phone *</label>
              <input type="text" name="phone1" class="form-control" value="{shop['phone']}" required>
            </div>
            <div class="form-group">
              <label class="form-label">Secondary Phone</label>
              <input type="text" name="phone2" class="form-control" value="{shop.get('phone2', '')}">
            </div>
          </div>

          <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">WhatsApp Number *</label>
              <input type="text" name="whatsapp" class="form-control" value="{shop['whatsapp']}" required>
            </div>
            <div class="form-group">
              <label class="form-label">Email Address</label>
              <input type="email" name="email" class="form-control" value="{shop.get('email', '')}">
            </div>
          </div>

          <div style="display:grid; grid-template-columns:2fr 1fr; gap:12px;">
            <div class="form-group">
              <label class="form-label">Shop Physical Address *</label>
              <input type="text" name="address" class="form-control" value="{shop['address']}" required>
            </div>
            <div class="form-group">
              <label class="form-label">City</label>
              <input type="text" name="city" class="form-control" value="{shop.get('city', 'Lahore')}">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">NTN / Tax Registration Number</label>
            <input type="text" name="ntn_tax_no" class="form-control" value="{shop.get('ntn_tax_no', '')}" placeholder="Optional">
          </div>

          <div class="form-group">
            <label class="form-label">Warranty Terms (Printed on Invoices)</label>
            <textarea name="warranty_terms" class="form-control" rows="2">{shop['warranty_terms']}</textarea>
          </div>

          <div class="form-group">
            <label class="form-label">Return Policy Note</label>
            <textarea name="return_policy" class="form-control" rows="2">{shop.get('return_policy', '7 Days checking return policy with original receipt.')}</textarea>
          </div>

          <div class="form-group">
            <label class="form-label">Receipt Footer Note</label>
            <input type="text" name="receipt_footer" class="form-control" value="{shop['footer_note']}">
          </div>

          <div class="form-group">
            <label class="form-label">Thermal Receipt Printer Width</label>
            <select name="receipt_printer_width" class="form-control">
              <option value="80" {'selected' if shop['printer_width']=='80' else ''}>80 mm Standard Thermal</option>
              <option value="58" {'selected' if shop['printer_width']=='58' else ''}>58 mm Small Thermal</option>
            </select>
          </div>

          <button type="submit" class="btn btn-success" style="width:100%; padding:12px; font-weight:bold; margin-top:10px;">💾 Save Shop Settings & Sync Everywhere</button>
        </form>
      </div>
    </div>

    <script>
      async function handleLogoUpload(input) {{
        if (!input.files || !input.files[0]) return;
        const file = input.files[0];
        const msg = document.getElementById('logo-upload-msg');
        msg.innerHTML = '<span style="color:#60a5fa;">⏳ Processing logo and generating thermal bitmaps...</span>';
        
        const fd = new FormData();
        fd.append('logo', file);
        try {{
          const res = await fetch('/api/settings/logo/upload', {{
            method: 'POST',
            body: fd
          }});
          const data = await res.json();
          if (data.success) {{
            msg.innerHTML = '<span style="color:#10b981;">✅ Logo uploaded and synced!</span>';
            setTimeout(() => window.location.reload(), 600);
          }} else {{
            msg.innerHTML = '<span style="color:#ef4444;">❌ ' + data.message + '</span>';
          }}
        }} catch(e) {{
          msg.innerHTML = '<span style="color:#ef4444;">Upload error</span>';
        }}
      }}

      async function handleRemoveLogo() {{
        if (!confirm('Are you sure you want to remove the shop logo?')) return;
        try {{
          const res = await fetch('/api/settings/logo/remove', {{ method: 'POST' }});
          const data = await res.json();
          if (data.success) {{
            window.location.reload();
          }}
        }} catch(e) {{
          alert('Failed to remove logo');
        }}
      }}
    </script>
    """
    return layout("Settings", content, "settings", user)

@app.route("/settings/save", method="POST")
def settings_save_route():
    user = require_admin()
    s_name = request.forms.get("shop_name", "").strip() or "PAK MOBILE & ACCESSORIES"
    tagline = request.forms.get("tagline", "").strip()
    p1 = request.forms.get("phone1", "").strip()
    p2 = request.forms.get("phone2", "").strip()
    wa = request.forms.get("whatsapp", "").strip()
    em = request.forms.get("email", "").strip()
    addr = request.forms.get("address", "").strip()
    city = request.forms.get("city", "").strip()
    ntn = request.forms.get("ntn_tax_no", "").strip()
    footer = request.forms.get("receipt_footer", "").strip()
    warranty = request.forms.get("warranty_terms", "").strip()
    ret_pol = request.forms.get("return_policy", "").strip()
    p_width = request.forms.get("receipt_printer_width", "80").strip()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with db.transaction() as cx:
        cur = cx.cursor()
        cur.execute("""
            INSERT INTO shop_profile (id, shop_name, tagline, address, city, phone1, phone2, whatsapp, email, ntn_tax_no, receipt_footer, warranty_terms, return_policy, profile_version, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                shop_name = excluded.shop_name,
                tagline = excluded.tagline,
                address = excluded.address,
                city = excluded.city,
                phone1 = excluded.phone1,
                phone2 = excluded.phone2,
                whatsapp = excluded.whatsapp,
                email = excluded.email,
                ntn_tax_no = excluded.ntn_tax_no,
                receipt_footer = excluded.receipt_footer,
                warranty_terms = excluded.warranty_terms,
                return_policy = excluded.return_policy,
                profile_version = shop_profile.profile_version + 1,
                updated_at = excluded.updated_at
        """, (s_name, tagline, addr, city, p1, p2, wa, em, ntn, footer, warranty, ret_pol, now))

        settings_map = {
            "shop_name": s_name,
            "tagline": tagline,
            "phone": p1,
            "whatsapp": wa,
            "address": addr,
            "warranty_terms": warranty,
            "footer_note": footer,
            "receipt_printer_width": p_width
        }
        for k, v in settings_map.items():
            cur.execute("""
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (k, v, now))

    db.bump_change_version("profile")
    auth.log_audit(user["id"], user["username"], "UPDATE_SHOP_PROFILE", "shop_profile", "1", "", f"Updated profile for {s_name}")
    return redirect("/settings")

# ═══════════════════════════════════════════════════════════
# LOGO & CHANGE-FEED API ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.route("/api/shop/logo")
def api_shop_logo():
    logo_data, mime = logo_engine.get_logo_data()
    if not logo_data:
        abort(404, "Logo not found")
    response.content_type = mime or "image/png"
    response.set_header("Cache-Control", "public, max-age=3600")
    return bytes(logo_data)

@app.route("/api/settings/logo/upload", method="POST")
def api_settings_logo_upload():
    require_admin()
    upload = request.files.get("logo")
    if not upload:
        response.status = 400
        return json.dumps({"success": False, "message": "No file uploaded"})
    
    file_bytes = upload.file.read()
    res = logo_engine.process_and_store_logo(file_bytes)
    response.content_type = "application/json"
    if not res["success"]:
        response.status = 400
    return json.dumps(res)

@app.route("/api/settings/logo/remove", method="POST")
def api_settings_logo_remove():
    require_admin()
    res = logo_engine.remove_logo()
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/change-feed")
def api_change_feed():
    client_ver = safe_int(request.query.get("v"), 0)

    state = db.get_change_feed_state()
    prof = db.query_one("SELECT shop_name, tagline, phone1, whatsapp, address, has_logo, profile_version FROM shop_profile WHERE id = 1")
    alert_sum = alert_engine.get_alert_summary()

    res = {
        "version": state["version"],
        "profile_version": state["profile_version"],
        "groups": state["groups"],
        "changed": (client_ver != state["version"]),
        "alerts_count": alert_sum.get("total_urgent", 0)
    }
    if client_ver != state["version"] and prof:
        res["profile"] = {
            "name": prof["shop_name"],
            "tagline": prof.get("tagline", ""),
            "phone": prof.get("phone1", ""),
            "whatsapp": prof.get("whatsapp", ""),
            "address": prof.get("address", ""),
            "has_logo": bool(prof.get("has_logo")),
            "version": prof["profile_version"]
        }
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/settings/lookups")
def settings_lookups_screen():
    user = require_admin()
    active_key = request.query.get("key", "brand")
    
    # Available lists
    lists_meta = [
        ("brand", "Phone Brands"),
        ("category", "Product Categories"),
        ("color", "Colors"),
        ("ram", "RAM Variants"),
        ("storage", "Storage Variants"),
        ("network", "Network / SIM"),
        ("condition", "Device Conditions"),
        ("pta_status", "PTA Approval Statuses"),
        ("expense_category", "Expense Categories"),
        ("payment_account", "Bank / Payment Accounts"),
        ("customer_type", "Customer Types"),
        ("city_area", "Markets & Cities"),
        ("return_reason", "Return Reasons"),
        ("trade_in_condition", "Trade-in Conditions"),
        ("repair_complaint", "Repair Complaints"),
        ("technician", "Technicians & Ustads"),
        ("accessory_type", "Accessory Types"),
        ("spare_part_type", "Spare Part Types"),
        ("warranty_type", "Warranty Types"),
        ("quick_service_provider", "Quick Service Providers"),
        ("supplier_category", "Supplier Categories")
    ]

    items = lookups.get_lookup_list(active_key, include_archived=True)
    
    tabs_html = ""
    for lk, lbl in lists_meta:
        act = "btn-primary" if lk == active_key else "btn-secondary"
        tabs_html += f'<a href="/settings/lookups?key={lk}" class="btn btn-sm {act}" style="margin:2px;">{lbl}</a> '

    extra_cat_th = "<th>Alert Level</th><th>Reorder Qty</th>" if active_key == "category" else ""

    item_rows = ""
    for it in items:
        usage = lookups.get_item_usage_count(active_key, it["label"])
        status_pill = '<span class="badge badge-success">Active</span>' if it["is_active"] else '<span class="badge badge-danger">Archived</span>'
        action_btn = f'<button class="btn btn-sm btn-danger" onclick="archiveItem({it["id"]})">Archive</button>' if it["is_active"] else f'<button class="btn btn-sm btn-success" onclick="restoreItem({it["id"]})">Restore</button>'

        extra_cat_td = ""
        if active_key == "category":
            low_val = it.get("default_low_stock_level")
            reorder_val = it.get("default_reorder_qty")
            low_str = f"&le; {low_val} units" if low_val is not None else '<span style="color:#94a3b8;">Global (2)</span>'
            reorder_str = f"{reorder_val} units" if reorder_val is not None else '<span style="color:#94a3b8;">Global (10)</span>'
            extra_cat_td = f'<td><span class="badge badge-warning">{low_str}</span></td><td><span class="badge badge-info">{reorder_str}</span></td>'

        low_arg = it.get("default_low_stock_level") if it.get("default_low_stock_level") is not None else 'null'
        reorder_arg = it.get("default_reorder_qty") if it.get("default_reorder_qty") is not None else 'null'

        item_rows += f"""
        <tr>
          <td><strong>{it['label']}</strong></td>
          {extra_cat_td}
          <td>{usage} records</td>
          <td>{status_pill}</td>
          <td style="text-align:right;">
            <button class="btn btn-sm btn-secondary" onclick="renameItem({it['id']}, '{it['label']}', {low_arg}, {reorder_arg})">✎ Edit</button>
            <button class="btn btn-sm btn-secondary" onclick="mergeItem({it['id']}, '{it['label']}')">⇄ Merge</button>
            {action_btn}
          </td>
        </tr>
        """

    content = f"""
    <div style="max-width:1100px; margin:0 auto;">
      <div style="display:flex; gap:8px; margin-bottom:16px;">
        <a href="/settings" class="btn btn-secondary">⚙️ Shop & Printer</a>
        <a href="/settings/lookups" class="btn btn-primary">📋 Lists & Categories</a>
        <a href="/settings/scanner-test" class="btn btn-secondary">🔬 USB Scanner Diagnostics</a>
      </div>

      <div class="card" style="margin-bottom:16px; padding:12px;">
        <div style="font-size:12px; font-weight:700; color:var(--text-muted); margin-bottom:8px;">SELECT LIST TO MANAGE:</div>
        <div>{tabs_html}</div>
      </div>

      <div class="grid-2">
        <!-- Items Table -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">List Items ({len(items)})</div>
          </div>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr><th>Label</th>{extra_cat_th}<th>Usage Count</th><th>Status</th><th style="text-align:right;">Actions</th></tr>
              </thead>
              <tbody>
                {item_rows or '<tr><td colspan="6" style="text-align:center;color:#888;">No items in this list</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Add & Bulk Add Panel -->
        <div>
          <div class="card" style="margin-bottom:14px;">
            <div class="card-title" style="margin-bottom:10px;">➕ Add Single Item</div>
            <div style="display:flex; gap:8px;">
              <input type="text" id="lookup-new-label" class="form-control" placeholder="New item name..." />
              <button class="btn btn-success" onclick="addSingleItem()">Add</button>
            </div>
          </div>

          <div class="card">
            <div class="card-title" style="margin-bottom:10px;">📥 Bulk Add (Paste Multiple Lines)</div>
            <textarea id="lookup-bulk-text" class="form-control" rows="6" placeholder="Paste items here (one per line)..."></textarea>
            <button class="btn btn-primary" style="width:100%; margin-top:10px;" onclick="addBulkItems()">Import Lines</button>
          </div>
        </div>
      </div>
    </div>

    <script>
      const currentListKey = "{active_key}";

      async function addSingleItem() {{
        const inp = document.getElementById('lookup-new-label');
        const val = inp.value.trim();
        if (!val) return;
        const res = await fetch('/api/lookups/add', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ list_key: currentListKey, label: val }})
        }});
        const data = await res.json();
        if (data.success) window.location.reload();
        else alert(data.error || 'Failed to add item');
      }}

      async function addBulkItems() {{
        const txt = document.getElementById('lookup-bulk-text').value.trim();
        if (!txt) return;
        const res = await fetch('/api/lookups/bulk-add', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ list_key: currentListKey, lines_text: txt }})
        }});
        const data = await res.json();
        if (data.success) {{
          alert('Added ' + data.added + ' items (skipped ' + data.skipped + ' duplicates)');
          window.location.reload();
        }} else alert(data.error || 'Failed to bulk import');
      }}

      async function renameItem(id, oldLabel, curLow, curReorder) {{
        const n = prompt('Rename "' + oldLabel + '" to:', oldLabel);
        if (n === null) return;
        const newName = n.trim() || oldLabel;
        let newLow = curLow;
        let newReorder = curReorder;
        if ('{active_key}' === 'category') {{
          const pLow = prompt('Default Low-Stock Alert Level for "' + newName + '" (e.g. 2 for Phones, 5 for Accessories):', curLow !== null ? curLow : '');
          if (pLow !== null) newLow = pLow.trim();
          const pReorder = prompt('Default Reorder Qty for "' + newName + '" (e.g. 10):', curReorder !== null ? curReorder : '');
          if (pReorder !== null) newReorder = pReorder.trim();
        }}
        const res = await fetch('/api/lookups/rename', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            id: id,
            label: newName,
            default_low_stock_level: (newLow !== null && newLow !== '') ? parseInt(newLow) : null,
            default_reorder_qty: (newReorder !== null && newReorder !== '') ? parseInt(newReorder) : null
          }})
        }});
        const data = await res.json();
        if (data.success) window.location.reload();
        else alert(data.error || 'Failed to update');
      }}

      async function archiveItem(id) {{
        if (confirm('Archive this lookup option? It will be hidden from dropdowns.')) {{
          const res = await fetch('/api/lookups/archive', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ id: id }})
          }});
          const data = await res.json();
          if (data.success) window.location.reload();
        }}
      }}

      async function restoreItem(id) {{
        const res = await fetch('/api/lookups/restore', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ id: id }})
        }});
        const data = await res.json();
        if (data.success) window.location.reload();
      }}

      async function mergeItem(srcId, srcLabel) {{
        const tgt = prompt('Enter the ID of the TARGET item to merge "' + srcLabel + '" into (this will update all historical products/repairs and archive "' + srcLabel + '"):');
        if (tgt && parseInt(tgt)) {{
          const res = await fetch('/api/lookups/merge', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ list_key: currentListKey, source_id: srcId, target_id: parseInt(tgt) }})
          }});
          const data = await res.json();
          if (data.success) {{
            alert(data.message);
            window.location.reload();
          }} else alert(data.error || 'Failed to merge');
        }}
      }}
    </script>
    """
    return layout("Lists & Categories", content, "settings", user)

@app.route("/settings/audit")
@app.route("/settings/audit/")
def settings_audit_screen():
    user = require_admin()
    q_act = request.query.get("action", "").strip()
    q_user = request.query.get("username", "").strip()
    
    clauses = []
    params = []
    if q_act:
        clauses.append("action LIKE ?")
        params.append(f"%{q_act}%")
    if q_user:
        clauses.append("username LIKE ?")
        params.append(f"%{q_user}%")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    logs = db.query_all(f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT 100", tuple(params))

    rows_html = ""
    for l in logs:
        rows_html += f"""
        <tr class="audit-row" data-search="{l['action'].lower()} {l['username'].lower()} {l['entity'].lower()} {html.escape((l['new_val'] or '')).lower()}">
          <td style="font-size:12px; color:#94a3b8;">{l['timestamp']}</td>
          <td><strong>{l['username']}</strong></td>
          <td><span class="badge badge-purple">{l['action']}</span></td>
          <td><code>{l['entity']} #{l['entity_id']}</code></td>
          <td style="font-size:12.5px; max-width:320px; overflow:hidden; text-overflow:ellipsis;">{html.escape(l['new_val'] or '-')}</td>
        </tr>
        """

    content = f"""
    <div style="max-width:1100px; margin:0 auto;">
      <div style="display:flex; gap:8px; margin-bottom:16px;">
        <a href="/settings" class="btn btn-secondary">⚙️ Shop & Printer</a>
        <a href="/settings/users" class="btn btn-secondary">👥 Users & Security</a>
        <a href="/settings/lookups" class="btn btn-secondary">📋 Lists & Categories</a>
        <a href="/settings/audit" class="btn btn-primary">📜 Audit Log</a>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title">📜 System Audit Log ({len(logs)} Events)</div>
          <input type="text" placeholder="🔍 Live filter events..." class="form-control" style="width:200px; padding:4px 8px; font-size:12px;" oninput="filterAuditTable(this.value)">
        </div>
        <div class="table-responsive" style="max-height:600px; overflow-y:auto;">
          <table class="data-table">
            <thead>
              <tr><th>Timestamp</th><th>User</th><th>Action</th><th>Target Entity</th><th>Details</th></tr>
            </thead>
            <tbody>
              {rows_html or '<tr><td colspan="5" style="text-align:center; color:#888;">No audit records found</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    <script>
      function filterAuditTable(q) {{
        q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
        document.querySelectorAll('.audit-row').forEach(r => {{
          var txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
          r.style.display = txt.includes(q) ? '' : 'none';
        }});
      }}
    </script>
    """
    return layout("Audit Log", content, "settings", user)

@app.route("/settings/scanner-test")
def settings_scanner_test_screen():
    user = require_admin()
    content = f"""
    <div style="max-width:900px; margin:0 auto;">
      <div style="display:flex; gap:8px; margin-bottom:16px;">
        <a href="/settings" class="btn btn-secondary">⚙️ Shop & Printer</a>
        <a href="/settings/lookups" class="btn btn-secondary">📋 Lists & Categories</a>
        <a href="/settings/scanner-test" class="btn btn-primary">🔬 USB Scanner Diagnostics</a>
      </div>

      <div class="card" style="margin-bottom:16px;">
        <div class="card-header">
          <div class="card-title">🔬 Real-Time USB Barcode & IMEI Scanner Diagnostics</div>
          <button type="button" class="btn btn-secondary btn-sm" onclick="ScannerEngine.playSuccessBeep()">🔊 Test Audio Beep</button>
        </div>
        <p style="font-size:13px; color:var(--text-muted); margin-bottom:16px;">
          Scan any barcode or IMEI sticker with your physical USB scanner right now. The diagnostic burst engine below measures character transmission speed, validates format, and verifies that burst timing is strictly &le; 40 ms.
        </p>

        <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:12px; margin-bottom:16px;">
          <div style="background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">
            <div style="font-size:11px; color:var(--text-muted);">LAST SCANNED CODE</div>
            <div id="diag-code" style="font-size:16px; font-weight:800; color:var(--primary); margin-top:4px;">Waiting for scan...</div>
          </div>
          <div style="background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">
            <div style="font-size:11px; color:var(--text-muted);">BURST LATENCY (AVG)</div>
            <div id="diag-latency" style="font-size:16px; font-weight:800; color:#34d399; margin-top:4px;">0 ms</div>
          </div>
          <div style="background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">
            <div style="font-size:11px; color:var(--text-muted);">LENGTH / FORMAT</div>
            <div id="diag-format" style="font-size:16px; font-weight:800; color:#cbd5e1; margin-top:4px;">-</div>
          </div>
          <div style="background:rgba(0,0,0,0.2); padding:12px; border-radius:8px;">
            <div style="font-size:11px; color:var(--text-muted);">BURST VERDICT</div>
            <div id="diag-verdict" style="font-size:14px; font-weight:800; color:#94a3b8; margin-top:4px;">READY</div>
          </div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h4 style="font-size:13px; color:var(--text);">Live Keystroke Event Log:</h4>
          <button type="button" class="btn btn-sm btn-secondary" onclick="clearEventLog()">Clear Log</button>
        </div>
        <div class="table-responsive" style="max-height:260px; overflow-y:auto; border:1px solid var(--card-border); border-radius:6px;">
          <table class="data-table">
            <thead>
              <tr><th>Timestamp</th><th>Scanned Barcode / IMEI</th><th>Avg Keystroke Interval</th><th>Classification</th></tr>
            </thead>
            <tbody id="diag-log-tbody">
              <tr><td colspan="4" style="text-align:center; color:#64748b;">No scan events recorded yet. Point scanner and pull trigger.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <script>
      let scanHistory = [];

      window.onScannerTestEvent = function(event) {{
        const tbody = document.getElementById('diag-log-tbody');
        if (scanHistory.length === 0) tbody.innerHTML = '';

        const isFast = event.latency <= 45;
        const verdictPill = isFast ? '<span class="badge badge-success">🟢 USB SCANNER BURST</span>' : '<span class="badge badge-warning">🟡 MANUAL TYPING</span>';
        
        document.getElementById('diag-code').innerText = event.code;
        document.getElementById('diag-latency').innerText = event.latency + ' ms';
        document.getElementById('diag-format').innerText = event.code.length + ' chars (' + (event.code.length === 15 ? 'IMEI' : 'Barcode') + ')';
        document.getElementById('diag-verdict').innerHTML = verdictPill;

        const row = document.createElement('tr');
        row.innerHTML = `
          <td>${{event.timestamp}}</td>
          <td><code>${{event.code}}</code></td>
          <td><strong>${{event.latency}} ms</strong> / char</td>
          <td>${{verdictPill}}</td>
        `;
        tbody.prepend(row);
        scanHistory.push(event);
      }};

      function clearEventLog() {{
        scanHistory = [];
        document.getElementById('diag-log-tbody').innerHTML = '<tr><td colspan="4" style="text-align:center; color:#64748b;">Log cleared. Point scanner and pull trigger.</td></tr>';
      }}
    </script>
    """
    return layout("Scanner Diagnostics", content, "settings", user)

@app.route("/settings/diagnostics")
def settings_diagnostics_screen():
    user = require_admin()
    diag = inventory.health_check_diagnostics()

    cards_html = ""
    for chk in diag["checks"]:
        is_pass = chk["status"] == "PASS"
        st_color = "#10b981" if is_pass else "#ef4444"
        badge_bg = "rgba(16, 185, 129, 0.15)" if is_pass else "rgba(239, 68, 68, 0.15)"
        icon = "✅" if is_pass else "❌"
        cards_html += f"""
        <div style="background:var(--card); border:1px solid var(--border); border-left:4px solid {st_color}; border-radius:8px; padding:14px; margin-bottom:12px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-weight:bold; font-size:14px; color:var(--text);">{icon} {chk['name']}</div>
            <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">{chk['detail']}</div>
          </div>
          <span style="font-size:12px; font-weight:bold; color:{st_color}; background:{badge_bg}; padding:4px 10px; border-radius:6px; border:1px solid {st_color}40;">
            {chk['status']}
          </span>
        </div>
        """

    diag_json = json.dumps(diag, indent=2)

    content = f"""
    <div style="max-width:900px; margin:0 auto;">
      <div style="display:flex; gap:8px; margin-bottom:16px;">
        <a href="/settings" class="btn btn-secondary">⚙️ Shop & Printer</a>
        <a href="/settings/lookups" class="btn btn-secondary">📋 Lists & Categories</a>
        <a href="/settings/scanner-test" class="btn btn-secondary">🔬 USB Scanner Diagnostics</a>
        <a href="/settings/diagnostics" class="btn btn-primary">🩺 Health Diagnostics</a>
      </div>

      <div class="card">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div class="card-title">🩺 System Health Diagnostics & Integrity</div>
            <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">Last run: {diag['timestamp']} &bull; Non-destructive test transaction</div>
          </div>
          <div style="display:flex; gap:8px;">
            <button type="button" class="btn btn-sm btn-secondary" onclick="copyDiagnostics()">📋 Copy Diagnostics</button>
            <a href="/settings/diagnostics" class="btn btn-sm btn-primary">🔄 Re-run Diagnostics</a>
          </div>
        </div>

        <div style="margin-top:16px;">
          {cards_html}
        </div>
      </div>

      <!-- Fresh Launch Data Purge Card -->
      <div class="card" style="margin-top:16px; border:1px solid #f87171; background:rgba(239, 68, 68, 0.04);">
        <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div class="card-title" style="color:#ef4444;">🧹 Clean Database (Delete All Test Data / Fresh Launch)</div>
            <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
              Dukan start karne se pehle testing ka sara data (Sales, Purchases, Phones, Quick Services, Repairs, Expenses) saaf karein.
            </div>
          </div>
          <button type="button" class="btn btn-danger btn-sm" onclick="promptResetDatabase()">🗑️ Reset to Fresh Database</button>
        </div>
        <div style="font-size:11.5px; color:#94a3b8; margin-top:10px; line-height:1.5;">
          ℹ️ <strong>Note:</strong> Is se sirf test transactions aur stock delete hoga. Dukan ke settings, categories, brands, aur Admin/Staff accounts bilkul safe rahenge. Password <code>admin123</code> aur PIN <code>9999</code> par reset ho jayenge.
        </div>
      </div>
    </div>

    <textarea id="diag-raw-data" style="display:none;">{diag_json}</textarea>
    <script>
      function copyDiagnostics() {{
        const raw = document.getElementById('diag-raw-data').value;
        navigator.clipboard.writeText(raw).then(() => {{
          alert('Diagnostics copied to clipboard (sanitized: passwords and customer data excluded).');
        }}).catch(() => {{
          alert('Failed to copy. Please allow clipboard permissions.');
        }});
      }}
      function promptResetDatabase() {{
        var conf = prompt("Khabardaar! Kya aap waqai tamam test data delete karke fresh launch karna chahte hain?\\n\\nAgar haan, to tasdeeq ke liye 'RESET' likhein:");
        if (conf === "RESET") {{
          var fd = new FormData();
          fd.append("confirm", "RESET");
          fetch("/api/admin/reset-database", {{ method: "POST", body: fd }})
            .then(r => r.json())
            .then(data => {{
              if (data.success) {{
                alert("Mubarak ho! Database bilkul saaf aur fresh ho gaya hai.\\nAb page reload ho raha hai.");
                window.location.href = "/";
              }} else {{
                alert("Error: " + (data.error || "Failed to reset database"));
              }}
            }}).catch(e => alert("Error communicating with server: " + e));
        }}
      }}
    </script>
    """
    return layout("Health Diagnostics", content, "settings", user)

@app.route("/api/admin/reset-database", method="POST")
def api_admin_reset_database():
    user = require_admin()
    confirm_text = request.forms.get("confirm", "").strip()
    admin_pin = request.forms.get("admin_pin", "").strip()

    if confirm_text != "RESET" and admin_pin != "9999":
        response.content_type = "application/json"
        response.status = 400
        return json.dumps({"success": False, "error": "Invalid confirmation code or PIN. Please enter RESET."})

    try:
        import clean_database
        clean_database.purge_dummy_data()
        response.content_type = "application/json"
        return json.dumps({"success": True, "message": "Database completely wiped and reset to clean fresh state!"})
    except Exception as e:
        response.content_type = "application/json"
        response.status = 500
        return json.dumps({"success": False, "error": str(e)})

# ═══════════════════════════════════════════════════════════
# JSON APIS (UNIVERSAL SEARCH, LOOKUPS & SCANNER)
# ═══════════════════════════════════════════════════════════

@app.route("/api/scan-route", method=["GET", "POST"])
def api_scan_route():
    if request.method == "POST":
        payload = request.json or {}
        code = payload.get("code", "").strip()
        ctx = payload.get("context", "GENERAL").strip()
    else:
        code = request.query.get("code", "").strip()
        ctx = request.query.get("context", "GENERAL").strip()
    response.content_type = "application/json"
    return json.dumps(scanner.universal_scan_route(code, context=ctx))

@app.route("/api/imei-lookup")
def api_imei_lookup():
    require_login()
    q = request.query.get("q", "").strip()
    res = scanner.get_imei_lifecycle(q)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/search")
def api_search():
    user = require_login()
    q = request.query.get("q", "").strip()
    role = user.get("role", "EMPLOYEE")
    res = search.search_all(q, role=role)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/search/products")
def api_search_products():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    q = request.query.get("q", "").strip()
    role = user.get("role", "EMPLOYEE")
    res = search.search_products_and_units(q, limit=15, role=role)
    clean_res = [inventory.public_item(item, is_admin) for item in res]
    response.content_type = "application/json"
    return json.dumps({"success": True, "items": clean_res})

@app.route("/api/pos/variant-units/<vid:int>")
def api_pos_variant_units(vid):
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    units = db.query_all("""
        SELECT u.*, u.id AS unit_id, v.ram, v.storage, v.color, v.retail_price, v.sku,
               p.brand, p.name AS model_name, p.category, p.item_type
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        WHERE u.variant_id = ? AND u.status = 'IN_STOCK'
        ORDER BY u.id ASC
    """, (vid,))
    clean_units = [inventory.public_item(u, is_admin) for u in units]
    response.content_type = "application/json"
    return json.dumps({"success": True, "units": clean_units})

@app.route("/sales")
@app.route("/sales/")
def sales_screen():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]

    # Query params
    view = request.query.get("view", "").strip()
    req_date = request.query.get("date", "").strip()
    req_month = request.query.get("month", "").strip()
    req_start = request.query.get("start_date", "").strip()
    req_end = request.query.get("end_date", "").strip()
    quick = request.query.get("quick", "").strip()
    sp_id = safe_int(request.query.get("salesperson_id", 0)) if is_admin else user["id"]
    pm_filter = request.query.get("payment_method", "").strip()
    it_filter = request.query.get("item_type", "").strip()
    q = request.query.get("q", "").strip()
    inv = request.query.get("invoice", "").strip()

    if inv:
        s = db.query_one("SELECT * FROM sales WHERE invoice_no = ?", (inv,))
        if s:
            return redirect(f"/print/sale/{s['id']}")

    # Quick button handling
    if quick == "today":
        req_date = today
        view = "day"
    elif quick == "yesterday":
        from datetime import timedelta
        yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        req_date = yest
        view = "day"
    elif quick == "week":
        from datetime import timedelta
        req_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        req_end = today
        view = "month"
    elif quick == "this_month":
        req_month = current_month
        view = "month"
    elif quick == "last_month":
        from datetime import date
        first_this = date(datetime.now().year, datetime.now().month, 1)
        from datetime import timedelta
        last_day_prev = first_this - timedelta(days=1)
        req_month = last_day_prev.strftime("%Y-%m")
        view = "month"

    # Determine view mode: 'day' vs 'month'
    if req_date and view != "month" and not q:
        mode = "day"
        target_date = req_date
    elif q:
        mode = "search"
        target_date = today
    elif view == "month" or (req_start and req_end) or req_month:
        mode = "month"
        if req_start and req_end:
            target_start = req_start
            target_end = req_end
            month_val = req_start[:7]
        elif req_month:
            target_start, target_end = get_month_date_range(req_month)
            month_val = req_month
        else:
            target_start = f"{current_month}-01"
            target_end = today
            month_val = current_month
    else:
        # Default to TODAY's individual invoices!
        mode = "day"
        target_date = today

    # Load salespersons for filter dropdown (Admin only)
    employees = db.query_all("SELECT id, username, full_name FROM users ORDER BY full_name ASC") if is_admin else []
    emp_options = '<option value="">All Staff / Cashiers</option>' + "".join(
        f'<option value="{e["id"]}" {"selected" if sp_id == e["id"] else ""}>{e["full_name"] or e["username"]}</option>'
        for e in employees
    )

    pm_options = f"""
      <option value="">All Payment Modes</option>
      <option value="CASH" {"selected" if pm_filter == 'CASH' else ""}>💵 Cash Drawer</option>
      <option value="CARD" {"selected" if pm_filter == 'CARD' else ""}>💳 Card</option>
      <option value="ONLINE" {"selected" if pm_filter == 'ONLINE' else ""}>📱 Bank / Online / Wallet</option>
      <option value="UDHAAR" {"selected" if pm_filter == 'UDHAAR' else ""}>👥 Udhaar (Credit)</option>
    """

    it_options = f"""
      <option value="">All Item Types</option>
      <option value="PHONE" {"selected" if it_filter == 'PHONE' else ""}>📱 Mobile Phones</option>
      <option value="ACCESSORY" {"selected" if it_filter in ('ACCESSORY', 'ACC') else ""}>🎧 Accessories & Glass</option>
    """

    # ═════════════════════════════════════════════════════════
    # MODE 1: MONTH / RANGE DATE-WISE BREAKDOWN VIEW
    # ═════════════════════════════════════════════════════════
    if mode == "month":
        summary = accounting.get_date_wise_sales_summary(
            target_start, target_end,
            salesperson_id=sp_id if sp_id else None,
            payment_method=pm_filter if pm_filter else None,
            item_type=it_filter if it_filter else None,
            is_admin=is_admin
        )
        days = summary["days"]
        tot = summary["totals"]

        # Mini Bar Chart SVG
        max_net = max([d["net_sale"] for d in days] + [1])
        chart_bars = ""
        # Display chronological in chart (reverse of table)
        for d in reversed(days):
            pct = max(4, int((d["net_sale"] / max_net) * 80))
            day_num = d["date"][-2:]
            chart_bars += f"""
            <div style="flex:1; min-width:14px; max-width:28px; display:flex; flex-direction:column; align-items:center; height:90px; justify-content:flex-end;" title="{d['date']}: Rs. {d['net_sale']:,.0f} ({d['invoices_count']} bills)">
              <div style="font-size:9px; color:#94a3b8; margin-bottom:2px;">{d['invoices_count'] if d['invoices_count'] > 0 else ''}</div>
              <div style="width:100%; height:{pct}%; background:{'#38bdf8' if d['net_sale'] > 0 else 'rgba(255,255,255,0.05)'}; border-radius:3px 3px 0 0; transition:all 0.2s;" onmouseover="this.style.background='#60a5fa'" onmouseout="this.style.background='#38bdf8'"></div>
              <div style="font-size:9.5px; color:#cbd5e1; margin-top:3px; font-weight:bold;">{day_num}</div>
            </div>
            """

        chart_box = f"""
        <div class="card" style="margin-bottom:16px; padding:12px 16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <div style="font-size:12px; font-weight:bold; color:#94a3b8; text-transform:uppercase;">Daily Net Sales Velocity ({target_start} to {target_end})</div>
            <div style="font-size:11px; color:#38bdf8;">Peak Day: <strong>Rs. {max_net:,.0f}</strong></div>
          </div>
          <div style="display:flex; align-items:flex-end; gap:4px; height:90px; padding-top:6px; overflow-x:auto;">
            {chart_bars or '<div style="color:#64748b; font-size:12px; margin:auto;">No sales data for selected period</div>'}
          </div>
        </div>
        """

        # Build Month Table Rows
        table_rows = ""
        for d in days:
            cost_td = f'<td style="text-align:right;">Rs. {d["cost"]:,.0f}</td>' if is_admin else ''
            profit_td = f'<td style="text-align:right; font-weight:bold; color:{"#34d399" if d["profit"] >= 0 else "#f87171"};">Rs. {d["profit"]:,.0f}</td>' if is_admin else ''
            exp_td = f'<td style="text-align:right; color:#f87171;">{f"-Rs. {d['expenses']:,.0f}" if d["expenses"] > 0 else "-"}</td>' if is_admin else ''
            net_day_td = f'<td style="text-align:right; font-weight:800; color:{"#34d399" if d["net_of_day"] >= 0 else "#f87171"};">Rs. {d["net_of_day"]:,.0f}</td>' if is_admin else ''

            table_rows += f"""
            <tr style="cursor:pointer;" onclick="location.href='/sales?date={d['date']}&view=day'">
              <td><a href="/sales?date={d['date']}&view=day" style="color:#38bdf8; font-weight:bold; text-decoration:none;">📅 {d['date']}</a></td>
              <td style="text-align:center;"><span class="badge badge-info">{d['invoices_count']}</span></td>
              <td style="text-align:center; font-weight:bold; color:#38bdf8;">{d['phones_sold']}</td>
              <td style="text-align:center; color:#94a3b8;">{d['accessories_sold']}</td>
              <td style="text-align:right;">Rs. {d['gross_sale']:,.0f}</td>
              <td style="text-align:right; color:#f87171;">{f"-Rs. {d['returns']:,.0f}" if d['returns'] > 0 else "-"}</td>
              <td style="text-align:right; font-weight:800; color:#34d399; font-size:13.5px;">Rs. {d['net_sale']:,.0f}</td>
              {cost_td}
              {profit_td}
              <td style="text-align:right; font-size:11px; color:#cbd5e1;">
                💵 {d['cash_paid']:,.0f} &bull; 💳 {d['card_paid']+d['online_paid']:,.0f} &bull; 👥 {d['udhaar_amount']:,.0f}
              </td>
              {exp_td}
              {net_day_td}
              <td style="text-align:right;">
                <a href="/sales?date={d['date']}&view=day" class="btn btn-xs btn-primary">Bills &rarr;</a>
              </td>
            </tr>
            """

        tot_cost_th = f'<th style="text-align:right;">Rs. {tot.get("cost", 0):,.0f}</th>' if is_admin else ''
        tot_prof_th = f'<th style="text-align:right; color:{"#34d399" if tot.get("profit", 0) >= 0 else "#f87171"};">Rs. {tot.get("profit", 0):,.0f}</th>' if is_admin else ''
        tot_exp_th = f'<th style="text-align:right; color:#f87171;">-Rs. {tot.get("expenses", 0):,.0f}</th>' if is_admin else ''
        tot_net_day_th = f'<th style="text-align:right; font-weight:800; color:{"#34d399" if tot.get("net_of_day", 0) >= 0 else "#f87171"};">Rs. {tot.get("net_of_day", 0):,.0f}</th>' if is_admin else ''

        admin_headers = """
          <th style="text-align:right;">Cost</th>
          <th style="text-align:right;">Gross Profit</th>
        """ if is_admin else ""

        admin_headers_end = """
          <th style="text-align:right;">Expenses</th>
          <th style="text-align:right;">Net of Day</th>
        """ if is_admin else ""

        export_url = f"/sales/export.csv?start_date={target_start}&end_date={target_end}&salesperson_id={sp_id}&payment_method={pm_filter}&item_type={it_filter}"
        print_url = f"/print/daily-sales?start_date={target_start}&end_date={target_end}&salesperson_id={sp_id}&payment_method={pm_filter}"

        content = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
          <div>
            <h1 style="font-size:22px; font-weight:800; margin:0;">🧾 Date-Wise Daily Sales & Revenue Breakdown</h1>
            <div style="font-size:12px; color:#94a3b8;">
              Period: <strong>{target_start}</strong> to <strong>{target_end}</strong> &bull; Total: <strong>{tot['invoices_count']} Invoices</strong>
            </div>
          </div>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <a href="{export_url}" class="btn btn-secondary btn-sm">📥 Export CSV</a>
            <a href="{print_url}" target="_blank" class="btn btn-primary btn-sm">🖨️ Print Statement</a>
            <a href="/day-closing" class="btn btn-outline-primary btn-sm">🔒 Day Closing</a>
          </div>
        </div>

        <!-- Filter Bar Card -->
        <div class="card" style="margin-bottom:16px; padding:14px;">
          <form method="GET" action="/sales" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <input type="hidden" name="view" value="month">
            
            <!-- Quick Preset Buttons -->
            <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
              <span style="font-size:12px; font-weight:bold; color:#cbd5e1;">Quick:</span>
              <a href="/sales?quick=today" class="btn btn-xs {'btn-primary' if quick == 'today' else 'btn-secondary'}">Today</a>
              <a href="/sales?quick=yesterday" class="btn btn-xs {'btn-primary' if quick == 'yesterday' else 'btn-secondary'}">Yesterday</a>
              <a href="/sales?quick=week" class="btn btn-xs {'btn-primary' if quick == 'week' else 'btn-secondary'}">This Week</a>
              <a href="/sales?quick=this_month" class="btn btn-xs {'btn-primary' if quick == 'this_month' or (not quick and not req_start and req_month == current_month) else 'btn-secondary'}">This Month</a>
              <a href="/sales?quick=last_month" class="btn btn-xs {'btn-primary' if quick == 'last_month' else 'btn-secondary'}">Last Month</a>
            </div>

            <!-- Custom Month & Date Range -->
            <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
              <label style="font-size:11.5px; color:#94a3b8;">Month:</label>
              <input type="month" name="month" value="{month_val}" class="form-control" style="width:130px; padding:4px 6px; font-size:12px;" onchange="this.form.submit()">

              <label style="font-size:11.5px; color:#94a3b8;">From:</label>
              <input type="date" name="start_date" value="{target_start}" class="form-control" style="width:130px; padding:4px 6px; font-size:12px;">
              
              <label style="font-size:11.5px; color:#94a3b8;">To:</label>
              <input type="date" name="end_date" value="{target_end}" class="form-control" style="width:130px; padding:4px 6px; font-size:12px;">

              {f'<select name="salesperson_id" class="form-control" style="width:140px; padding:4px 6px; font-size:12px;" onchange="this.form.submit()">{emp_options}</select>' if is_admin else ''}
              
              <select name="payment_method" class="form-control" style="width:130px; padding:4px 6px; font-size:12px;" onchange="this.form.submit()">
                {pm_options}
              </select>

              <select name="item_type" class="form-control" style="width:120px; padding:4px 6px; font-size:12px;" onchange="this.form.submit()">
                {it_options}
              </select>

              <button type="submit" class="btn btn-primary btn-sm">Filter</button>
            </div>
          </form>
        </div>

        <!-- High-level KPI Cards -->
        <div class="grid-4" style="margin-bottom:16px;">
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">TOTAL INVOICES</div>
            <div style="font-size:22px; font-weight:800; color:#38bdf8; margin-top:4px;">{tot['invoices_count']} Bills</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">📱 {tot['phones_sold']} Phones &bull; 🎧 {tot['acc_sold']} Acc</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">NET SALES VOLUME</div>
            <div style="font-size:22px; font-weight:800; color:#34d399; margin-top:4px;">Rs. {tot['net_sale']:,.0f}</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">Gross: Rs. {tot['gross_sale']:,.0f} {f'&bull; Ret: -Rs. {tot["returns"]:,.0f}' if tot['returns'] > 0 else ''}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">{('NET GROSS PROFIT' if is_admin else 'CASH RECEIVED')}</div>
            <div style="font-size:22px; font-weight:800; color:#60a5fa; margin-top:4px;">Rs. {(tot.get('profit', tot['cash_paid'])):,.0f}</div>
            <div style="font-size:11px; color:#cbd5e1; margin-top:2px;">Cash: Rs. {tot['cash_paid']:,.0f} &bull; Bank: Rs. {tot['online_paid']+tot['card_paid']:,.0f}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">{('NET OF PERIOD (AFTER EXPENSES)' if is_admin else 'UDHAAR CREATED')}</div>
            <div style="font-size:22px; font-weight:800; color:{'#10b981' if tot.get('net_of_day', 0) >= 0 else '#f87171'}; margin-top:4px;">Rs. {(tot.get('net_of_day', tot['udhaar_amount'])):,.0f}</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">{f'Expenses: -Rs. {tot.get("expenses", 0):,.0f}' if is_admin else f'Due: Rs. {tot["udhaar_amount"]:,.0f}'}</div>
          </div>
        </div>

        {chart_box}

        <!-- Month Table (One row per date) -->
        <div class="card">
          <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div class="card-title">📅 Date-Wise Daily Sales Breakdown ({len(days)} Active Days)</div>
            <div style="font-size:12px; color:#94a3b8;">Click any date row to view that day's invoices</div>
          </div>
          <div class="table-responsive">
            <table class="data-table" style="font-size:13px;">
              <thead>
                <tr>
                  <th>Date</th>
                  <th style="text-align:center;">Bills</th>
                  <th style="text-align:center;">Phones</th>
                  <th style="text-align:center;">Acc</th>
                  <th style="text-align:right;">Gross</th>
                  <th style="text-align:right;">Returns</th>
                  <th style="text-align:right;">NET Sale</th>
                  {admin_headers}
                  <th style="text-align:right;">Split (Cash &bull; Bank &bull; Udhaar)</th>
                  {admin_headers_end}
                  <th style="text-align:right;">Action</th>
                </tr>
              </thead>
              <tbody>
                {table_rows or '<tr><td colspan="12" style="text-align:center; padding:32px; color:#64748b;">No sales found for the selected period.</td></tr>'}
              </tbody>
              <tfoot>
                <tr style="background:rgba(255,255,255,0.05); border-top:2px solid var(--border); font-weight:bold; font-size:13.5px;">
                  <th>TOTALS</th>
                  <th style="text-align:center;">{tot['invoices_count']}</th>
                  <th style="text-align:center; color:#38bdf8;">{tot['phones_sold']}</th>
                  <th style="text-align:center;">{tot['acc_sold']}</th>
                  <th style="text-align:right;">Rs. {tot['gross_sale']:,.0f}</th>
                  <th style="text-align:right; color:#f87171;">-Rs. {tot['returns']:,.0f}</th>
                  <th style="text-align:right; color:#34d399; font-size:14px;">Rs. {tot['net_sale']:,.0f}</th>
                  {tot_cost_th}
                  {tot_prof_th}
                  <th style="text-align:right; font-size:11.5px;">💵 {tot['cash_paid']:,.0f} &bull; 💳 {tot['online_paid']+tot['card_paid']:,.0f} &bull; 👥 {tot['udhaar_amount']:,.0f}</th>
                  {tot_exp_th}
                  {tot_net_day_th}
                  <th></th>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
        """
        return layout("Daily Sales Breakdown", content, "sales", user)

    # ═════════════════════════════════════════════════════════
    # MODE 2: SINGLE DAY INVOICES DRILL-DOWN OR SEARCH VIEW
    # ═════════════════════════════════════════════════════════
    else:
        date_expr_sales = "COALESCE(NULLIF(s.transaction_date, ''), substr(s.created_at, 1, 10))"
        if q:
            clauses = ["(s.invoice_no LIKE ? OR s.customer_name LIKE ? OR s.customer_phone LIKE ?)"]
            params = [f"%{q}%", f"%{q}%", f"%{q}%"]
            if not is_admin:
                clauses.append("s.salesperson_id = ?")
                params.append(user["id"])
            where_sql = " AND ".join(clauses)
            sales = db.query_all(f"""
                SELECT s.*, (SELECT COUNT(*) FROM sale_items WHERE sale_id = s.id) AS item_count
                FROM sales s WHERE {where_sql} ORDER BY s.id DESC LIMIT 100
            """, tuple(params))
            heading_title = f"Search Results for '{q}' ({len(sales)} Invoices)"
        else:
            clauses = [f"{date_expr_sales} = ?"]
            params = [target_date]
            if not is_admin:
                clauses.append("s.salesperson_id = ?")
                params.append(user["id"])
            if sp_id and is_admin:
                clauses.append("s.salesperson_id = ?")
                params.append(sp_id)
            if pm_filter:
                if pm_filter.upper() == "CASH":
                    clauses.append("(UPPER(s.payment_method) LIKE '%CASH%' OR UPPER(s.payment_method) LIKE '%DRAWER%')")
                elif pm_filter.upper() == "CARD":
                    clauses.append("UPPER(s.payment_method) = 'CARD'")
                elif pm_filter.upper() in ("ONLINE", "BANK"):
                    clauses.append("(UPPER(s.payment_method) IN ('ONLINE', 'BANK') OR UPPER(s.payment_method) LIKE '%EASYPAISA%' OR UPPER(s.payment_method) LIKE '%JAZZCASH%')")
                elif pm_filter.upper() == "UDHAAR":
                    clauses.append("s.balance_due > 0")

            where_sql = " AND ".join(clauses)
            sales = db.query_all(f"""
                SELECT s.*, (SELECT COUNT(*) FROM sale_items WHERE sale_id = s.id) AS item_count
                FROM sales s WHERE {where_sql} ORDER BY s.id DESC
            """, tuple(params))
            heading_title = f"Invoices for {target_date} ({len(sales)} Invoices)"

        tot_grand = sum(float(s["grand_total"] or 0) for s in sales if s.get("status") not in ("VOIDED", "CANCELLED"))
        tot_returned = sum(float(s.get("returned_amount") or 0) for s in sales if s.get("status") not in ("VOIDED", "CANCELLED"))
        tot_net = max(0.0, tot_grand - tot_returned)
        tot_paid = sum(float(s["paid_amount"] or 0) for s in sales if s.get("status") not in ("VOIDED", "CANCELLED"))
        tot_udhaar = sum(float(s["balance_due"] or 0) for s in sales if s.get("status") not in ("VOIDED", "CANCELLED"))
        tot_cash = sum(float(s["paid_amount"] or 0) for s in sales if s.get("status") not in ("VOIDED", "CANCELLED") and lookups.is_cash_account(s.get("payment_method")))

        # Query Udhaar & Credit Recoveries received on target_date
        udh_date_expr = "COALESCE(NULLIF(u.transaction_date, ''), substr(u.timestamp, 1, 10))"
        udhaar_payments = db.query_all(f"""
            SELECT u.*, c.name AS customer_name, c.phone AS customer_phone,
                   COALESCE(usr.full_name, usr.username, 'Staff') AS staff_name
            FROM udhaar_ledger u
            JOIN customers c ON u.customer_id = c.id
            LEFT JOIN users usr ON u.user_id = usr.id
            WHERE {udh_date_expr} = ?
              AND u.transaction_type IN ('PAYMENT', 'INSTALLMENT_PAYMENT')
            ORDER BY u.id DESC
        """, (target_date,))

        tot_udhaar_rec = sum(float(u["amount"] or 0) for u in udhaar_payments)
        tot_udhaar_rec_cash = sum(float(u["amount"] or 0) for u in udhaar_payments if lookups.is_cash_account(u.get("payment_method")))
        tot_udhaar_rec_non_cash = tot_udhaar_rec - tot_udhaar_rec_cash
        tot_drawer_cash = tot_cash + tot_udhaar_rec_cash

        udhaar_rows_html = ""
        for u in udhaar_payments:
            u_time = u['timestamp'][11:16] if len(u.get('timestamp') or '') >= 16 else (u.get('transaction_date') or '')
            u_phone = '-' if not u['customer_phone'] or u['customer_phone'].startswith('NOP-') else u['customer_phone']
            is_cash = lookups.is_cash_account(u.get("payment_method"))
            pm_tag = '<span class="badge" style="background:#0284c7; color:#fff;">💵 CASH DRAWER</span>' if is_cash else f'<span class="badge" style="background:#10b981; color:#fff;">📲 {u["payment_method"]}</span>'
            u_search = f"udh-{u['id']} {(u['customer_name'] or '').lower()} {u_phone.lower()} {(u.get('notes') or '').lower()}"
            udhaar_rows_html += f"""
            <tr class="udhaar-row" data-search="{u_search}">
              <td><a href="/print/udhaar-payment/{u['id']}" target="_blank" style="color:#60a5fa; font-weight:bold; text-decoration:none;">#UDH-{u['id']:05d}</a><br><small style="color:#94a3b8;">🕒 {u_time}</small></td>
              <td><a href="/credit/customer/{u['customer_id']}" style="color:#38bdf8; font-weight:bold; text-decoration:none;">{u['customer_name']}</a></td>
              <td><small style="color:#cbd5e1;">{u_phone}</small></td>
              <td>{pm_tag}</td>
              <td style="text-align:right;"><strong style="color:#34d399; font-size:14px;">Rs. {u['amount']:,.0f}</strong></td>
              <td style="text-align:right;"><span style="font-weight:bold; color:{'#f87171' if u['balance_after'] > 0 else '#34d399'};">Rs. {u['balance_after']:,.0f}</span></td>
              <td><small style="color:#cbd5e1;">{u['staff_name']}</small></td>
              <td><small style="color:#94a3b8;">{u['notes'] or '-'}</small></td>
              <td style="text-align:right; white-space:nowrap;">
                <a href="/print/udhaar-payment/{u['id']}" target="_blank" class="btn btn-sm btn-primary">🖨️ Receipt</a>
                <a href="/credit/customer/{u['customer_id']}" class="btn btn-sm btn-secondary">Khata</a>
              </td>
            </tr>
            """

        rows_html = ""
        for s in sales:
            pm = (s.get("payment_method") or "CASH").upper()
            bal_due = float(s.get("balance_due") or 0)
            paid_amt = float(s.get("paid_amount") or 0)
            
            if "UDHAAR" in pm or bal_due > 0:
                if paid_amt <= 0:
                    pm_badge = '<span class="badge" style="background:#dc2626; color:#fff; font-weight:bold;">📝 UDHAAR</span>'
                else:
                    pm_badge = '<span class="badge" style="background:#d97706; color:#fff; font-weight:bold;">⚠️ PARTIAL UDHAAR</span>'
            elif lookups.is_cash_account(s.get("payment_method")):
                pm_badge = '<span class="badge" style="background:#0284c7; color:#fff;">💵 CASH</span>'
            elif pm in ("ONLINE", "BANK", "RAAST", "EASYPAISA", "JAZZCASH") or "ONLINE" in pm:
                pm_badge = f'<span class="badge" style="background:#10b981; color:#fff;">📲 {s["payment_method"]}</span>'
            elif pm == "CARD":
                pm_badge = '<span class="badge" style="background:#6366f1; color:#fff;">💳 CARD</span>'
            else:
                pm_badge = f'<span class="badge" style="background:#8b5cf6; color:#fff;">{s["payment_method"]}</span>'
            
            s_status = (s.get("status") or "COMPLETED").upper()
            ret_amt = float(s.get("returned_amount") or 0)
            if s_status == "COMPLETED" and ret_amt > 0:
                s_status = "PARTIALLY_RETURNED"

            if s_status == "RETURNED":
                status_badge = '<span class="badge" style="background:#ef4444; color:#fff; font-weight:bold;">↩️ RETURNED</span>'
            elif s_status == "PARTIALLY_RETURNED":
                status_badge = '<span class="badge" style="background:#f59e0b; color:#fff; font-weight:bold;">⚠️ PARTIAL RET</span>'
            elif s_status == "VOIDED":
                status_badge = '<span class="badge" style="background:#64748b; color:#fff;">🚫 VOIDED</span>'
            elif s_status == "CANCELLED":
                status_badge = '<span class="badge badge-danger">CANCELLED</span>'
            else:
                status_badge = '<span class="badge badge-success">COMPLETED</span>'

            net_amt = max(0.0, float(s['grand_total'] or 0) - ret_amt)
            if s_status == "RETURNED":
                total_html = f'<span style="font-size:12px; color:#94a3b8; text-decoration:line-through;">Rs. {s["grand_total"]:,.0f}</span><br><span style="color:#ef4444; font-weight:bold; font-size:11px;">↩️ Ret: -Rs. {ret_amt:,.0f}</span><br><small style="color:#ef4444; font-weight:800;">Net: Rs. 0</small>'
            elif ret_amt > 0:
                total_html = f'<span style="font-weight:bold; font-size:14px; color:#34d399;">Rs. {net_amt:,.0f}</span><br><small style="color:#f59e0b; font-weight:bold;">↩️ Ret: -Rs. {ret_amt:,.0f}</small><br><small style="color:#94a3b8;">Gross: Rs. {s["grand_total"]:,.0f}</small>'
            elif s_status == "VOIDED":
                total_html = f'<span style="font-size:12px; color:#64748b; text-decoration:line-through;">Rs. {s["grand_total"]:,.0f}</span><br><small style="color:#64748b; font-weight:bold;">VOIDED</small>'
            else:
                total_html = f'<span style="font-weight:bold; font-size:14px; color:#34d399;">Rs. {s["grand_total"]:,.0f}</span>'

            time_str = s['created_at'][11:16] if len(s['created_at']) >= 16 else s['created_at']
            is_bd = bool(s.get("transaction_date") and s.get("created_at") and s["transaction_date"] != s["created_at"][:10])
            bd_badge = f'<br><span class="badge" style="background:#d97706; color:#fff; font-size:10px;" title="{html.escape(s.get("backdate_reason") or "Back-dated")}">🕒 Back-dated</span>' if is_bd else ''

            items = db.query_all("SELECT item_name, variant_details, imei1, qty, is_returned FROM sale_items WHERE sale_id = ?", (s['id'],))
            items_summary = ", ".join(
                f"{it['item_name']} {it['variant_details'] or ''} ({it['qty']})" + (' <span style="color:#ef4444; font-weight:bold; font-size:10px;">[RETURNED]</span>' if it.get("is_returned") == 1 else '')
                for it in items[:2]
            )
            if len(items) > 2:
                items_summary += f" +{len(items)-2} more"

            return_action = f'<a href="/returns?invoice={s["invoice_no"]}" class="btn btn-sm btn-secondary" style="margin-left:4px;">↩️ Return</a>' if s_status != "RETURNED" else '<span class="badge" style="background:#ef4444; color:#fff; font-size:10.5px; padding:4px 8px; margin-left:4px;">Returned</span>'

            rows_html += f"""
            <tr class="sale-row" data-search="{s['invoice_no'].lower()} {(s['customer_name'] or '').lower()} {(s['customer_phone'] or '').lower()}">
              <td><a href="/print/sale/{s['id']}" target="_blank" style="color:#38bdf8; font-weight:bold; text-decoration:none;">{s['invoice_no']}</a><br><small style="color:#94a3b8;">🕒 {time_str}</small>{bd_badge}</td>
              <td><strong>{s['customer_name']}</strong><br><small style="color:#94a3b8;">📞 {s['customer_phone'] or 'No Phone'}</small></td>
              <td><small style="color:#cbd5e1;">{s['salesperson_name'] or 'Counter'}</small></td>
              <td><span style="font-size:12px;">{items_summary or 'No items'}</span><br><small style="color:#94a3b8;">{s['item_count']} item(s)</small></td>
              <td>{pm_badge}</td>
              <td>{total_html}</td>
              <td style="font-size:12px;">Paid: Rs. {s['paid_amount']:,.0f}{f'<br><span style="color:#f87171; font-weight:bold;">Due: Rs. {s["balance_due"]:,.0f}</span>' if s['balance_due'] > 0 else ''}</td>
              <td>{status_badge}</td>
              <td style="text-align:right; white-space:nowrap;">
                <a href="/print/sale/{s['id']}" target="_blank" class="btn btn-sm btn-primary">🖨️ Receipt</a>
                {return_action}
              </td>
            </tr>
            """

        content = f"""
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:16px;">
          <div>
            <div style="margin-bottom:4px;">
              <a href="/sales?month={target_date[:7]}&view=month" class="btn btn-secondary btn-xs">&larr; Back to Month View ({target_date[:7]})</a>
            </div>
            <h1 style="font-size:22px; font-weight:800; margin:0;">🧾 Invoices & Receipts for {target_date}</h1>
            <div style="font-size:12px; color:#94a3b8;">Click any receipt to view, reprint or process returns</div>
          </div>
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <a href="/pos" class="btn btn-success btn-sm">+ New POS Sale</a>
            <a href="/print/daily-sales?start_date={target_date}&end_date={target_date}" target="_blank" class="btn btn-primary btn-sm font-weight-bold">🖨️ Print Detailed Day Sales Report</a>
            <a href="/print/day-closing/{target_date}" target="_blank" class="btn btn-secondary btn-sm">🖨️ Z-Report ({target_date})</a>
          </div>
        </div>

        <!-- Date & Search Bar Card -->
        <div class="card" style="margin-bottom:16px; padding:14px;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
              <label style="font-size:12px; font-weight:bold; color:#cbd5e1;">Select Date:</label>
              <input type="date" value="{target_date}" class="form-control" style="width:145px; padding:4px 8px; font-size:13px; font-weight:bold;" onchange="location.href='/sales?date='+this.value+'&view=day'">
              <a href="/sales?quick=today" class="btn btn-xs {'btn-primary' if target_date == today and not q else 'btn-secondary'}">Today</a>
              <a href="/sales?quick=yesterday" class="btn btn-xs btn-secondary">Yesterday</a>
              <a href="/sales?month={target_date[:7]}&view=month" class="btn btn-xs btn-outline-primary">📅 View Full Month</a>
            </div>
            <form method="GET" action="/sales" style="display:flex; gap:6px;">
              <input type="text" name="q" value="{q}" placeholder="🔍 Search invoice / customer..." class="form-control" style="width:220px; padding:4px 8px; font-size:12px;">
              <button type="submit" class="btn btn-primary btn-sm">Search</button>
              {f'<a href="/sales?date={today}&view=day" class="btn btn-secondary btn-sm">Clear</a>' if q else ''}
            </form>
          </div>
        </div>

        <!-- KPI Cards -->
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:12px; margin-bottom:16px;">
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">TOTAL INVOICES</div>
            <div style="font-size:20px; font-weight:800; color:#38bdf8; margin-top:4px;">{len(sales)} Bills</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">+ {len(udhaar_payments)} Udhaar Collections</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">NET SALES VOLUME</div>
            <div style="font-size:20px; font-weight:800; color:#34d399; margin-top:4px;">Rs. {tot_net:,.0f}</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Gross: Rs. {tot_grand:,.0f} {f'&bull; Ret: -Rs. {tot_returned:,.0f}' if tot_returned > 0 else ''}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">CASH RECEIVED (DRAWER)</div>
            <div style="font-size:20px; font-weight:800; color:#60a5fa; margin-top:4px;">Rs. {tot_drawer_cash:,.0f}</div>
            <div style="font-size:10px; color:#cbd5e1; margin-top:2px;">Sales: Rs. {tot_cash:,.0f} &bull; Udhaar Rec: Rs. {tot_udhaar_rec_cash:,.0f}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">UDHAAR RECOVERED TODAY</div>
            <div style="font-size:20px; font-weight:800; color:#10b981; margin-top:4px;">Rs. {tot_udhaar_rec:,.0f}</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Cash: Rs. {tot_udhaar_rec_cash:,.0f} &bull; Online: Rs. {tot_udhaar_rec_non_cash:,.0f}</div>
          </div>
          <div class="card" style="padding:12px;">
            <div style="font-size:11px; color:#94a3b8;">NEW UDHAAR CREATED</div>
            <div style="font-size:20px; font-weight:800; color:#f87171; margin-top:4px;">Rs. {tot_udhaar:,.0f}</div>
            <div style="font-size:10px; color:#94a3b8; margin-top:2px;">Outstanding on today's sales</div>
          </div>
        <!-- Section Toggle Tabs: All, Sales, Udhaar Payments -->
        <div style="display:flex; gap:8px; margin-bottom:12px; align-items:center;">
          <button type="button" id="tab-sales-all" class="btn btn-sm btn-primary" onclick="setSalesViewTab('all')">📋 All ({len(sales) + len(udhaar_payments)})</button>
          <button type="button" id="tab-sales-invoices" class="btn btn-sm btn-secondary" onclick="setSalesViewTab('invoices')">🧾 Sales Invoices ({len(sales)})</button>
          <button type="button" id="tab-sales-udhaar" class="btn btn-sm btn-secondary" onclick="setSalesViewTab('udhaar')">💵 Udhaar Payments ({len(udhaar_payments)})</button>
        </div>

        <!-- Invoices Table -->
        <div class="card" id="sec-invoices-card">
          <div class="card-header" style="display:flex; justify-content:space-between; align-items:center;">
            <div class="card-title">{heading_title}</div>
            <input type="text" placeholder="🔍 Quick live filter..." class="form-control" style="width:200px; padding:4px 8px; font-size:12px;" oninput="filterSalesTable(this.value)">
          </div>
          <div class="table-responsive">
            <table class="data-table" id="sales-history-table">
              <thead>
                <tr>
                  <th>Invoice # / Time</th>
                  <th>Customer</th>
                  <th>Salesperson</th>
                  <th>Items Sold</th>
                  <th>Payment</th>
                  <th>Total Amount</th>
                  <th>Payment Status</th>
                  <th>Status</th>
                  <th style="text-align:right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows_html or '<tr><td colspan="9" style="text-align:center; color:#64748b; padding:32px;">No sales recorded for this date.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Udhaar Recoveries Table -->
        <div class="card" id="sec-udhaar-card" style="margin-top:16px;">
          <div class="card-header" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>
              <div class="card-title" style="color:#10b981;">💵 Udhaar & Credit Recoveries Received on {target_date} ({len(udhaar_payments)} Collections &bull; Rs. {tot_udhaar_rec:,.0f})</div>
              <div style="font-size:12px; color:#94a3b8;">Payments collected from customers towards their outstanding Khata balance</div>
            </div>
            <a href="/credit" class="btn btn-secondary btn-sm">👥 All Customer Khatas</a>
          </div>
          <div class="table-responsive">
            <table class="data-table" style="font-size:13px;">
              <thead>
                <tr>
                  <th>Voucher # / Time</th>
                  <th>Customer Name</th>
                  <th>Phone</th>
                  <th>Payment Account</th>
                  <th style="text-align:right;">Amount Collected</th>
                  <th style="text-align:right;">Remaining Balance</th>
                  <th>Received By</th>
                  <th>Notes</th>
                  <th style="text-align:right;">Actions</th>
                </tr>
              </thead>
              <tbody>
                {udhaar_rows_html or f'<tr><td colspan="9" style="text-align:center; color:#64748b; padding:20px;">No Udhaar payments collected on {target_date}.</td></tr>'}
              </tbody>
            </table>
          </div>
        </div>

        <script>
          function setSalesViewTab(tab) {{
            const secInv = document.getElementById('sec-invoices-card');
            const secUdh = document.getElementById('sec-udhaar-card');
            const btnAll = document.getElementById('tab-sales-all');
            const btnInv = document.getElementById('tab-sales-invoices');
            const btnUdh = document.getElementById('tab-sales-udhaar');
            if (btnAll) btnAll.className = (tab === 'all') ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
            if (btnInv) btnInv.className = (tab === 'invoices') ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
            if (btnUdh) btnUdh.className = (tab === 'udhaar') ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
            if (secInv) secInv.style.display = (tab === 'all' || tab === 'invoices') ? 'block' : 'none';
            if (secUdh) secUdh.style.display = (tab === 'all' || tab === 'udhaar') ? 'block' : 'none';
          }}

          function filterSalesTable(q) {{
            q = (typeof window.normText === 'function') ? window.normText(q) : q.toLowerCase().trim();
            document.querySelectorAll('.sale-row').forEach(r => {{
              const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
              r.style.display = txt.includes(q) ? '' : 'none';
            }});
            document.querySelectorAll('.udhaar-row').forEach(r => {{
              const txt = (typeof window.normText === 'function') ? window.normText(r.getAttribute('data-search') || '') : (r.getAttribute('data-search') || '').toLowerCase();
              r.style.display = txt.includes(q) ? '' : 'none';
            }});
          }}
        </script>
        """
        return layout("Sales History", content, "sales", user)

@app.route("/sales/export.csv")
def sales_export_csv():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]

    start_date = request.query.get("start_date", f"{current_month}-01").strip()
    end_date = request.query.get("end_date", today).strip()
    sp_id = safe_int(request.query.get("salesperson_id", 0)) if is_admin else user["id"]
    pm = request.query.get("payment_method", "").strip()
    it = request.query.get("item_type", "").strip()

    summary = accounting.get_date_wise_sales_summary(
        start_date, end_date,
        salesperson_id=sp_id if sp_id else None,
        payment_method=pm if pm else None,
        item_type=it if it else None,
        is_admin=is_admin
    )

    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)

    if is_admin:
        writer.writerow(["Date", "Invoices", "Phones Sold", "Accessories Sold", "Gross Sale", "Discounts", "Returns", "Net Sale", "Cost", "Profit", "Cash Paid", "Card Paid", "Online Paid", "Udhaar Amount", "Expenses", "Net of Day"])
        for d in summary["days"]:
            writer.writerow([
                d["date"], d["invoices_count"], d["phones_sold"], d["accessories_sold"],
                d["gross_sale"], d["discounts"], d["returns"], d["net_sale"],
                d["cost"], d["profit"], d["cash_paid"], d["card_paid"], d["online_paid"], d["udhaar_amount"],
                d["expenses"], d["net_of_day"]
            ])
        tot = summary["totals"]
        writer.writerow(["TOTALS", tot["invoices_count"], tot["phones_sold"], tot["acc_sold"], tot["gross_sale"], tot["discounts"], tot["returns"], tot["net_sale"], tot["cost"], tot["profit"], tot["cash_paid"], tot["card_paid"], tot["online_paid"], tot["udhaar_amount"], tot["expenses"], tot["net_of_day"]])
    else:
        writer.writerow(["Date", "Invoices", "Phones Sold", "Accessories Sold", "Gross Sale", "Discounts", "Returns", "Net Sale", "Cash Paid", "Card Paid", "Online Paid", "Udhaar Amount"])
        for d in summary["days"]:
            writer.writerow([
                d["date"], d["invoices_count"], d["phones_sold"], d["accessories_sold"],
                d["gross_sale"], d["discounts"], d["returns"], d["net_sale"],
                d["cash_paid"], d["card_paid"], d["online_paid"], d["udhaar_amount"]
            ])
        tot = summary["totals"]
        writer.writerow(["TOTALS", tot["invoices_count"], tot["phones_sold"], tot["acc_sold"], tot["gross_sale"], tot["discounts"], tot["returns"], tot["net_sale"], tot["cash_paid"], tot["card_paid"], tot["online_paid"], tot["udhaar_amount"]])

    csv_data = output.getvalue()
    response.content_type = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="daily_sales_{start_date}_to_{end_date}.csv"'
    return csv_data

@app.route("/print/daily-sales")
@app.route("/print/sales-daily")
@app.route("/print/sales-report")
def print_daily_sales():
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    today = datetime.now().strftime("%Y-%m-%d")
    current_month = today[:7]

    req_date = request.query.get("date", "").strip()
    req_month = request.query.get("month", "").strip()
    start_date = request.query.get("start_date", "").strip()
    end_date = request.query.get("end_date", "").strip()

    if req_date:
        start_date = req_date
        end_date = req_date
    elif req_month and not (start_date and end_date):
        m_start, m_end = get_month_date_range(req_month)
        start_date = m_start
        end_date = m_end
    else:
        if not start_date:
            start_date = f"{current_month}-01"
        if not end_date:
            end_date = today

    sp_id = safe_int(request.query.get("salesperson_id", 0)) if is_admin else user["id"]
    pm = request.query.get("payment_method", "").strip()

    return printing.render_daily_sales_report(
        start_date, end_date,
        salesperson_id=sp_id if sp_id else None,
        payment_method=pm if pm else None,
        is_admin=is_admin
    )

@app.route("/repairing")
@app.route("/repairing/")
def repairing_alias():
    job = request.query.get("job", "").strip()
    if job:
        return redirect(f"/repairs?job={job}")
    return redirect("/repairs")

@app.route("/api/search/customers")
def api_search_customers():
    require_login()
    q = request.query.get("q", "").strip()
    res = search.search_customers(q, limit=10)
    response.content_type = "application/json"
    return json.dumps({"success": True, "items": res})

@app.route("/api/lookups")
def api_lookups():
    require_login()
    key = request.query.get("key", "").strip()
    items = lookups.get_lookup_list(key)
    response.content_type = "application/json"
    return json.dumps({"success": True, "items": items})

@app.route("/api/lookups/add", method="POST")
def api_lookups_add():
    user = require_login()
    payload = request.json or {}
    key = payload.get("list_key", "").strip()
    label = payload.get("label", "").strip()
    res = lookups.add_lookup_item(key, label, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/lookups/rename", method="POST")
def api_lookups_rename():
    user = require_admin()
    payload = request.json or {}
    item_id = int(payload.get("id", 0))
    label = payload.get("label", "").strip()
    low_level = payload.get("default_low_stock_level")
    reorder_qty = payload.get("default_reorder_qty")
    res = lookups.update_lookup_item(
        item_id, label, user_id=user["id"], username=user["username"],
        default_low_stock_level=int(low_level) if low_level is not None and str(low_level).isdigit() else None,
        default_reorder_qty=int(reorder_qty) if reorder_qty is not None and str(reorder_qty).isdigit() else None
    )
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/lookups/archive", method="POST")
def api_lookups_archive():
    user = require_admin()
    payload = request.json or {}
    item_id = int(payload.get("id", 0))
    res = lookups.archive_lookup_item(item_id, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/lookups/restore", method="POST")
def api_lookups_restore():
    user = require_admin()
    payload = request.json or {}
    item_id = int(payload.get("id", 0))
    res = lookups.restore_lookup_item(item_id, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/lookups/bulk-add", method="POST")
def api_lookups_bulk_add():
    user = require_admin()
    payload = request.json or {}
    key = payload.get("list_key", "").strip()
    text = payload.get("lines_text", "").strip()
    res = lookups.bulk_add_lookup_items(key, text, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/lookups/merge", method="POST")
def api_lookups_merge():
    user = require_admin()
    payload = request.json or {}
    key = payload.get("list_key", "").strip()
    src = int(payload.get("source_id", 0))
    tgt = int(payload.get("target_id", 0))
    res = lookups.merge_lookup_items(key, src, tgt, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/suppliers/quick-add", method="POST")
def api_suppliers_quick_add():
    user = require_admin()
    payload = request.json or {}
    name = payload.get("name", "").strip()
    phone = payload.get("phone", "").strip()
    comp = payload.get("company", "").strip()
    addr = payload.get("address", "").strip()
    if not name or not phone:
        response.status = 400
        return json.dumps({"success": False, "error": "Supplier Name and Phone are required"})
    sid = purchasing.create_supplier(name, phone, company=comp, address=addr)
    sup = db.query_one("SELECT * FROM suppliers WHERE id = ?", (sid,))
    response.content_type = "application/json"
    return json.dumps({"success": True, "supplier": sup})

@app.route("/api/customers/quick-add", method="POST")
def api_customers_quick_add():
    user = require_login()
    payload = request.json or {}
    name = payload.get("name", "").strip()
    phone = payload.get("phone", "").strip()
    cnic = payload.get("cnic", "").strip()
    ctype = payload.get("customer_type", "Walk-in / Retail").strip()
    if not name or not phone:
        response.status = 400
        return json.dumps({"success": False, "error": "Customer Name and Mobile Number are required"})
    existing = db.query_one("SELECT * FROM customers WHERE phone = ?", (phone,))
    if existing:
        response.content_type = "application/json"
        return json.dumps({"success": True, "customer": existing, "already_exists": True})
    cid = credit.create_customer(name, phone, cnic=cnic)
    cust = db.query_one("SELECT * FROM customers WHERE id = ?", (cid,))
    response.content_type = "application/json"
    return json.dumps({"success": True, "customer": cust, "already_exists": False})

@app.route("/api/products/quick-add", method="POST")
def api_products_quick_add():
    user = require_admin()
    payload = request.json or dict(request.forms)
    res = inventory.create_item_unified(payload, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/units/<uid:int>")
def api_get_unit(uid):
    user = require_login()
    u = db.query_one("""
        SELECT u.*, v.ram, v.storage, v.color, v.network, v.retail_price, v.wholesale_price,
               p.id AS product_id, p.brand, p.name AS model_name, p.category
        FROM units u
        JOIN variants v ON u.variant_id = v.id
        JOIN products p ON v.product_id = p.id
        WHERE u.id = ?
    """, (uid,))
    if not u:
        return HTTPResponse(status=404, body=json.dumps({"success": False, "error": "Unit not found"}), content_type="application/json")
    
    variants_list = db.query_all("SELECT id, ram, storage, color, network FROM variants WHERE product_id = ? AND is_archived = 0 ORDER BY id ASC", (u["product_id"],))
    return HTTPResponse(status=200, body=json.dumps({
        "success": True,
        "unit": dict(u),
        "available_variants": [dict(v) for v in variants_list]
    }), content_type="application/json")

@app.route("/api/units/update", method="POST")
def api_update_unit():
    user = require_admin()
    payload = request.json or dict(request.forms)
    uid = int(payload.get("unit_id") or 0)
    imei1 = str(payload.get("imei1") or "").strip()
    imei2 = str(payload.get("imei2") or "").strip()
    condition = str(payload.get("condition") or "New Box Pack").strip()
    pta = str(payload.get("pta_status") or "PTA Approved (Official)").strip()
    cp = float(payload.get("cost_price") or 0)
    bh = int(payload.get("battery_health") or 100)
    status = str(payload.get("status") or "IN_STOCK").strip()
    notes = str(payload.get("notes") or "").strip()
    target_vid = int(payload.get("variant_id") or 0) or None
    override_luhn = bool(payload.get("override_luhn") in (True, 1, "1", "true", "True"))
    admin_reason = str(payload.get("admin_reason") or "").strip()

    res = inventory.update_unit(
        uid, imei1, imei2=imei2, condition=condition, pta_status=pta, cost_price=cp,
        battery_health=bh, status=status, notes=notes, target_variant_id=target_vid,
        override_luhn=override_luhn, admin_reason=admin_reason,
        user_id=user["id"], username=user["username"], user_role=user["role"]
    )
    response.content_type = "application/json"
    response.status = 200 if res.get("success") else 400
    return json.dumps(res)

@app.route("/api/variants/<vid:int>")
def api_get_variant(vid):
    user = require_login()
    v = db.query_one("""
        SELECT v.*, p.brand, p.name AS model_name, p.category, p.item_type
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.id = ?
    """, (vid,))
    if not v:
        return HTTPResponse(status=404, body=json.dumps({"success": False, "error": "Variant not found"}), content_type="application/json")
    return HTTPResponse(status=200, body=json.dumps({"success": True, "variant": dict(v)}), content_type="application/json")

@app.route("/api/variants/update", method="POST")
def api_update_variant():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    ram = str(payload.get("ram") or "").strip()
    storage = str(payload.get("storage") or "").strip()
    color = str(payload.get("color") or "").strip()
    network = str(payload.get("network") or "").strip()
    rp = float(payload.get("retail_price") or 0)
    wp = float(payload.get("wholesale_price") or 0)
    mp = float(payload.get("min_selling_price") or 0)
    sq = int(payload.get("stock_quantity") or 0) if payload.get("stock_quantity") not in (None, "") else None
    barcode = str(payload.get("barcode") or "").strip()
    sku = str(payload.get("sku") or "").strip()
    low_stock = int(payload.get("low_stock_level") or 5) if payload.get("low_stock_level") not in (None, "") else None
    reorder_qty = int(payload.get("reorder_qty") or 10) if payload.get("reorder_qty") not in (None, "") else None
    alert_off = 1 if payload.get("alert_off") in (1, "1", True) else 0

    res = inventory.update_variant(
        vid, ram=ram, storage=storage, color=color, network=network,
        retail_price=rp, wholesale_price=wp, min_selling_price=mp,
        stock_quantity=sq, barcode=barcode, sku=sku,
        low_stock_level=low_stock, reorder_qty=reorder_qty, alert_off=alert_off,
        user_id=user["id"], username=user["username"]
    )
    response.content_type = "application/json"
    response.status = 200 if res.get("success") else 400
    return json.dumps(res)

@app.route("/api/variants/clone", method="POST")
def api_clone_variant():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    new_color = payload.get("new_color")
    new_ram = payload.get("new_ram")
    new_storage = payload.get("new_storage")
    new_network = payload.get("new_network")
    rp = payload.get("retail_price")
    wp = payload.get("wholesale_price")

    new_vid = inventory.clone_variant(
        vid, new_color=new_color, new_ram=new_ram, new_storage=new_storage, new_network=new_network,
        retail_price=rp, wholesale_price=wp, user_id=user["id"], username=user["username"]
    )
    response.content_type = "application/json"
    if new_vid:
        return json.dumps({"success": True, "new_variant_id": new_vid})
    else:
        response.status = 400
        return json.dumps({"success": False, "error": "Failed to clone variant"})

@app.route("/api/variants/archive", method="POST")
def api_archive_variant():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    res = inventory.archive_variant(vid, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    response.status = 200 if res.get("success") else 400
    return json.dumps(res)

@app.route("/api/variants/restore", method="POST")
def api_restore_variant():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    res = inventory.restore_variant(vid, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    response.status = 200 if res.get("success") else 400
    return json.dumps(res)

@app.route("/api/products/update", method="POST")
def api_update_product():
    user = require_admin()
    payload = request.json or dict(request.forms)
    pid = int(payload.get("product_id") or 0)
    brand = str(payload.get("brand") or "").strip()
    name = str(payload.get("name") or "").strip()
    category = str(payload.get("category") or "").strip()
    wm = int(payload.get("warranty_months") or 0)
    notes = str(payload.get("notes") or "").strip()
    image_url = str(payload.get("image_url") or "").strip()

    res = inventory.update_product(
        pid, brand=brand, name=name, category=category,
        warranty_months=wm, notes=notes, image_url=image_url,
        user_id=user["id"], username=user["username"]
    )
    response.content_type = "application/json"
    response.status = 200 if res.get("success") else 400
    return json.dumps(res)

@app.route("/api/items/<pid:int>")
def api_get_item_detail(pid):
    user = require_login()
    is_admin = (user["role"] == "ADMIN")
    prod = db.query_one("SELECT * FROM products WHERE id = ?", (pid,))
    if not prod:
        return HTTPResponse(status=404, body=json.dumps({"success": False, "message": "Item not found"}), content_type="application/json")
    variants = inventory.get_variants_for_product(pid)
    v0 = variants[0] if variants else None
    return HTTPResponse(
        status=200,
        body=json.dumps({
            "success": True,
            "product": inventory.public_item(dict(prod), is_admin),
            "variant": inventory.public_item(dict(v0), is_admin) if v0 else None,
            "variants": [inventory.public_item(dict(v), is_admin) for v in variants]
        }),
        content_type="application/json"
    )

@app.route("/api/items/create", method="POST")
def api_items_create():
    user = require_admin()
    payload = request.json or dict(request.forms)
    res = inventory.create_item_unified(payload, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/items/update", method="POST")
def api_items_update():
    user = require_admin()
    payload = request.json or dict(request.forms)
    res = inventory.update_item_unified(payload, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/items/delete", method="POST")
def api_items_delete():
    user = require_admin()
    payload = request.json or dict(request.forms)
    pid = int(payload.get("product_id") or 0)
    res = inventory.delete_or_archive_product(pid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/items/restore", method="POST")
def api_items_restore():
    user = require_admin()
    payload = request.json or dict(request.forms)
    pid = int(payload.get("product_id") or 0)
    res = inventory.restore_product(pid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/units/delete", method="POST")
def api_units_delete():
    user = require_admin()
    payload = request.json or dict(request.forms)
    uid = int(payload.get("unit_id") or 0)
    res = inventory.delete_unit(uid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/variants/delete", method="POST")
def api_variants_delete():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    res = inventory.delete_or_archive_variant(vid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/variants/restore", method="POST")
def api_variants_restore():
    user = require_admin()
    payload = request.json or dict(request.forms)
    vid = int(payload.get("variant_id") or 0)
    res = inventory.restore_variant(vid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/suppliers/delete", method="POST")
def api_suppliers_delete():
    user = require_admin()
    payload = request.json or dict(request.forms)
    sid = int(payload.get("supplier_id") or 0)
    res = purchasing.delete_or_archive_supplier(sid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/suppliers/restore", method="POST")
def api_suppliers_restore():
    user = require_admin()
    payload = request.json or dict(request.forms)
    sid = int(payload.get("supplier_id") or 0)
    res = purchasing.restore_supplier(sid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/customers/delete", method="POST")
def api_customers_delete():
    user = require_admin()
    payload = request.json or dict(request.forms)
    cid = int(payload.get("customer_id") or 0)
    res = credit.delete_or_archive_customer(cid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/customers/restore", method="POST")
def api_customers_restore():
    user = require_admin()
    payload = request.json or dict(request.forms)
    cid = int(payload.get("customer_id") or 0)
    res = credit.restore_customer(cid, user_id=user["id"], username=user["username"])
    response.status = res.get("status", 200)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/sales/void", method="POST")
def api_sales_void():
    user = require_admin()
    payload = request.json or dict(request.forms)
    sid = int(payload.get("sale_id") or 0)
    reason = str(payload.get("reason") or "Voided by Admin").strip()
    res = pos.admin_void_sale(sid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/purchases/void", method="POST")
def api_purchases_void():
    user = require_admin()
    payload = request.json or dict(request.forms)
    pid = int(payload.get("purchase_id") or 0)
    reason = str(payload.get("reason") or "Voided by Admin").strip()
    res = purchasing.void_purchase(pid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/expenses/void", method="POST")
def api_expenses_void():
    user = require_admin()
    payload = request.json or dict(request.forms)
    eid = int(payload.get("expense_id") or 0)
    reason = str(payload.get("reason") or "Voided by Admin").strip()
    res = accounting.void_expense(eid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/repairs/cancel", method="POST")
def api_repairs_cancel():
    user = require_perm("repair_jobs")
    payload = request.json or dict(request.forms)
    rid = int(payload.get("repair_id") or 0)
    reason = str(payload.get("reason") or "Cancelled").strip()
    res = services.cancel_or_void_repair_job(rid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/software/cancel", method="POST")
def api_software_cancel():
    user = require_perm("software_jobs")
    payload = request.json or dict(request.forms)
    jid = int(payload.get("job_id") or 0)
    reason = str(payload.get("reason") or "Cancelled").strip()
    res = services.cancel_or_void_software_job(jid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/quick-services/void", method="POST")
def api_quick_services_void():
    user = require_admin()
    payload = request.json or dict(request.forms)
    qid = int(payload.get("quick_service_id") or 0)
    reason = str(payload.get("reason") or "Voided by Admin").strip()
    res = services.void_quick_service(qid, reason=reason, user_id=user["id"], username=user["username"])
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/inventory/stock-history/<vid:int>")
def api_inventory_stock_history(vid):
    require_login()
    movements = db.query_all("""
        SELECT * FROM stock_ledger 
        WHERE variant_id = ? 
        ORDER BY id DESC LIMIT 50
    """, (vid,))
    response.content_type = "application/json"
    return json.dumps({"success": True, "variant_id": vid, "movements": [dict(m) for m in movements]})

@app.route("/api/inventory/bulk-price/preview")
def api_inventory_bulk_price_preview():
    require_admin()
    brand = request.query.get("brand") or None
    cat = request.query.get("category") or None
    adj_type = request.query.get("adjustment_type", "AMOUNT")
    ret_adj = float(request.query.get("retail_adj", 0))
    ws_adj = float(request.query.get("wholesale_adj", 0))
    res = inventory.preview_bulk_price_update(brand=brand, category=cat, adjustment_type=adj_type, retail_adj=ret_adj, wholesale_adj=ws_adj)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/inventory/import/preview", method="POST")
def api_inventory_import_preview():
    require_admin()
    payload = request.json or {}
    rows = payload.get("rows", [])
    res = inventory.preview_inventory_import(rows)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/health-check")
def api_health_check():
    user = require_admin()
    res = inventory.health_check_diagnostics()
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/pos/checkout", method="POST")
def api_pos_checkout():
    user = require_login()
    payload = request.json or {}
    items = payload.get("items", [])
    cname = payload.get("customer_name", "Walk-in Customer")
    cphone = payload.get("customer_phone", "")
    disc = float(payload.get("discount_amount", 0))
    paid = float(payload.get("paid_amount", 0))
    pm = payload.get("payment_method", "CASH")
    sdate = payload.get("sale_date")
    reason = payload.get("backdate_reason", "")

    res = pos.pos_checkout(items, customer_name=cname, customer_phone=cphone, discount_amount=disc, paid_amount=paid, payment_method=pm, user_id=user["id"], username=user["username"], sale_date=sdate, backdate_reason=reason)
    response.content_type = "application/json"
    return json.dumps(res)

@app.route("/api/check-closed-day")
def api_check_closed_day():
    require_login()
    d = request.query.get("date", "").strip()[:10]
    closing = db.query_one("SELECT * FROM day_closings WHERE closing_date = ?", (d,))
    response.content_type = "application/json"
    return json.dumps({"is_closed": bool(closing), "date": d})

@app.route("/api/pos/quick-top-sellers")
def api_pos_quick_top_sellers():
    require_login()
    cat = request.query.get("category", "")
    items = top_sellers.get_pos_quick_top_sellers(category=cat, limit=20)
    response.content_type = "application/json"
    return json.dumps({"success": True, "items": items})

# ═══════════════════════════════════════════════════════════
# PRINTING ROUTES (THERMAL 80/58mm, LABELS, A4)
# ═══════════════════════════════════════════════════════════

@app.route("/print/sale/<sid:int>")
def print_sale_route(sid):
    user = require_login()
    return printing.render_sale_receipt(sid)

@app.route("/print/return/<rid:int>")
def print_return_route(rid):
    user = require_login()
    return printing.render_return_receipt(rid)

@app.route("/print/repair/<rid:int>")
def print_repair_route(rid):
    user = require_login()
    return printing.render_repair_ticket(rid)

@app.route("/print/software/<jid:int>")
def print_software_route(jid):
    user = require_login()
    return printing.render_software_receipt(jid)

@app.route("/print/trade-in/<tid:int>")
def print_trade_in_route(tid):
    user = require_login()
    return printing.render_trade_in_slip(tid)

@app.route("/print/barcode-label/<vid:int>")
def print_barcode_label_route(vid):
    user = require_login()
    v = db.query_one("""
        SELECT v.*, p.brand, p.name AS product_name
        FROM variants v
        JOIN products p ON v.product_id = p.id
        WHERE v.id = ?
    """, (vid,))
    if not v:
        return "<h3>Variant not found</h3>"
    item_name = f"{v['brand']} {v['product_name']}"
    spec = f"{v['ram']}/{v['storage']} {v['color']}" if v.get("ram") else (v.get("color") or "")
    code = v.get("barcode") or f"VAR-{vid:05d}"
    unit_id = request.query.get("unit_id")
    if unit_id:
        u = db.query_one("SELECT * FROM units WHERE id = ?", (int(unit_id),))
        if u and u.get("imei1"):
            code = u["imei1"]
    return printing.render_barcode_label(item_name, spec, code, v["retail_price"])

@app.route("/print/supplier-payment/<lid:int>")
def print_supplier_payment_route(lid):
    user = require_admin()
    return printing.render_supplier_payment_receipt(lid)

@app.route("/print/installment-contract/<iid:int>")
def print_installment_contract_route(iid):
    user = require_login()
    return printing.render_installment_contract(iid)

@app.route("/print/installment-payment/<sid:int>")
def print_installment_payment_route(sid):
    user = require_login()
    return printing.render_installment_payment_receipt(sid)

@app.route("/print/udhaar-payment/<lid:int>")
@app.route("/print/udhaar-receipt/<lid:int>")
def print_udhaar_payment_route(lid):
    user = require_login()
    return printing.render_udhaar_payment_receipt(lid)

@app.route("/print/day-closing/<target_date>")
def print_day_closing_route(target_date):
    user = require_admin()
    return printing.render_day_closing_z_report(target_date)

@app.route("/print/monthly-report/<year:int>/<month:int>")
def print_monthly_report_route(year, month):
    user = require_admin()
    return printing.render_monthly_report(year, month)

@app.route("/static/<filename:path>")
def serve_static(filename):
    return static_file(filename, root=config.STATIC_DIR)

@app.error(404)
def error_404_handler(err):
    if request.path.startswith("/api/"):
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "error": f"API endpoint not found: {request.path}",
            "code": 404
        })
    shop = printing.get_shop_info()
    content = f"""
    <div style="max-width: 620px; margin: 60px auto; text-align: center; padding: 36px 24px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
      <div style="font-size: 52px; margin-bottom: 12px;">🔍</div>
      <h1 style="font-size: 26px; font-weight: 800; color: #f87171; margin-bottom: 8px;">404 — Page Not Found</h1>
      <p style="font-size: 14px; color: var(--text-muted); margin-bottom: 24px; line-height: 1.5;">
        The requested address <code style="background: rgba(255,255,255,0.08); padding: 3px 8px; border-radius: 4px; color: #38bdf8;">{request.path}</code> does not exist or has been moved.
      </p>
      <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
        <a href="/pos" class="btn btn-primary" style="padding: 10px 20px;">⚡ Return to POS</a>
        <a href="/inventory" class="btn btn-secondary" style="padding: 10px 20px;">📦 Inventory</a>
        <a href="/reports" class="btn btn-secondary" style="padding: 10px 20px;">📊 Reports</a>
      </div>
      <div style="margin-top: 32px; font-size: 11px; color: #64748b; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 16px;">
        {shop['name']} ERP &bull; Developed by Ahmed
      </div>
    </div>
    """
    return layout("404 Not Found", content, active_nav="")

@app.error(500)
def error_500_handler(err):
    if request.path.startswith("/api/"):
        response.content_type = "application/json"
        return json.dumps({
            "success": False,
            "error": f"Internal server error: {str(err)}",
            "code": 500
        })
    shop = printing.get_shop_info()
    content = f"""
    <div style="max-width: 620px; margin: 60px auto; text-align: center; padding: 36px 24px; background: var(--card); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
      <div style="font-size: 52px; margin-bottom: 12px;">⚠️</div>
      <h1 style="font-size: 26px; font-weight: 800; color: #ef4444; margin-bottom: 8px;">500 — Server Error</h1>
      <p style="font-size: 14px; color: var(--text-muted); margin-bottom: 24px; line-height: 1.5;">
        An unexpected error occurred while processing <code style="background: rgba(255,255,255,0.08); padding: 3px 8px; border-radius: 4px; color: #f87171;">{request.path}</code>.
      </p>
      <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;">
        <a href="/pos" class="btn btn-primary" style="padding: 10px 20px;">⚡ Return to POS</a>
        <a href="/inventory" class="btn btn-secondary" style="padding: 10px 20px;">📦 Inventory</a>
      </div>
      <div style="margin-top: 32px; font-size: 11px; color: #64748b; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 16px;">
        {shop['name']} ERP &bull; Developed by Ahmed
      </div>
    </div>
    """
    return layout("500 Server Error", content, active_nav="")

@app.route("/api/server/shutdown", method="POST")
def api_server_shutdown():
    import os, threading, time
    user = get_current_user()
    token = request.headers.get("X-Shutdown-Token") or request.forms.get("shutdown_token")
    valid_token = getattr(config, "SHUTDOWN_TOKEN", None) or os.environ.get("SHUTDOWN_TOKEN")
    if not ((user and user["role"] == "ADMIN") or (valid_token and token == valid_token)):
        abort(403, "Access Denied: Admin authorization or valid shutdown token required.")
    def do_shutdown():
        time.sleep(0.8)
        try:
            import db
            with db.get_connection() as cx:
                cx.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception:
            pass
        os._exit(0)
    threading.Thread(target=do_shutdown, daemon=True).start()
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Server Stopped - Mobile ERP</title>
    <style>body{background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding:80px;}</style>
    </head>
    <body>
      <div style="max-width:500px;margin:auto;background:#1e293b;padding:32px;border-radius:12px;border:1px solid #334155;">
        <h2 style="color:#10b981;">✅ Server Stopped Cleanly</h2>
        <p style="color:#94a3b8;line-height:1.6;">Mobile Shop ERP database was safely checkpointed. You can now close this browser tab.</p>
        <p style="margin-top:24px;font-size:12px;color:#64748b;">Developed by Ahmed</p>
      </div>
    </body>
    </html>
    """

# ═══════════════════════════════════════════════════════════
@app.route("/vvip-pos")
def serve_vvip_pos_screen():
    root = config.BUNDLE_DIR if os.path.exists(os.path.join(config.BUNDLE_DIR, "vvip_pos_showcase.html")) else getattr(config, "BASE_DIR", config.BUNDLE_DIR)
    return static_file("vvip_pos_showcase.html", root=root, mimetype="text/html")

# SERVER RUNNER
# ═══════════════════════════════════════════════════════════

def start_server():
    wrapped_app = SessionMiddleware(app, SESSION_OPTIONS)
    try:
        import waitress
        print(f"[SERVER] Starting Waitress multi-threaded WSGI server on {config.HOST}:{config.PORT} (6 threads)...")
        waitress.serve(wrapped_app, host=config.HOST, port=config.PORT, threads=6, _quiet=True)
    except Exception as e:
        print(f"[SERVER WARNING] Waitress error ({e}), falling back to standard server...")
        import bottle
        bottle.run(app=wrapped_app, host=config.HOST, port=config.PORT, quiet=True)

if __name__ == "__main__":
    print(f"Starting Mobile ERP on http://{config.HOST}:{config.PORT}...")
    start_server()
