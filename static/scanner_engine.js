/**
 * MOBILE & ACCESSORIES ERP — Hardened Universal Scanner Engine v3.2
 * Features:
 * 1. Keystroke timing burst detector (<=40ms interval)
 * 2. Input textbox leakage prevention & state restoration
 * 3. 300ms duplicate suppression window
 * 4. Topbar status chip with live latency display & audio mute toggle
 * 5. Web Audio feedback (zero external audio files)
 * 6. Universal context router across all screens + Life Card modal
 */

(function () {
  let buffer = [];
  let lastKeyTime = Date.now();
  let maxIntervalMs = 45; // characters arriving faster than this are from barcode scanner
  let minBarcodeLen = 6;
  let lastScannedCode = "";
  let lastScannedTimestamp = 0;
  let soundEnabled = true;
  let focusedInputSnapshot = null;
  let audioCtx = null;

  function getAudioContext() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtx;
  }

  function playSuccessBeep() {
    if (!soundEnabled) return;
    try {
      const ctx = getAudioContext();
      if (ctx.state === "suspended") ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.18, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.08);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.08);
    } catch (e) {}
  }

  function playErrorBeep() {
    if (!soundEnabled) return;
    try {
      const ctx = getAudioContext();
      if (ctx.state === "suspended") ctx.resume();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sawtooth";
      osc.frequency.setValueAtTime(240, ctx.currentTime);
      gain.gain.setValueAtTime(0.22, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.16);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.16);
    } catch (e) {}
  }

  function flashScreen(color) {
    const flashEl = document.createElement("div");
    flashEl.style.cssText = `position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:999999;box-shadow:inset 0 0 60px ${color};opacity:1;transition:opacity 0.25s ease-out;`;
    document.body.appendChild(flashEl);
    setTimeout(() => {
      flashEl.style.opacity = "0";
      setTimeout(() => flashEl.remove(), 250);
    }, 50);
  }

  function showToast(msg, isSuccess = true) {
    let toast = document.getElementById("scanner-global-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "scanner-global-toast";
      toast.style.cssText = "position:fixed;top:20px;right:20px;z-index:999999;padding:12px 20px;border-radius:8px;font-weight:bold;color:#fff;box-shadow:0 10px 25px rgba(0,0,0,0.3);transition:all 0.3s ease;font-size:14px;max-width:420px;";
      document.body.appendChild(toast);
    }
    toast.style.background = isSuccess ? "#10b981" : "#ef4444";
    toast.innerText = msg;
    toast.style.display = "block";
    toast.style.opacity = "1";
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.style.display = "none", 300);
    }, 2800);
  }

  // Topbar Status Chip
  function initScannerChip() {
    let chip = document.getElementById("scanner-status-chip");
    if (!chip) {
      const topbar = document.querySelector(".topbar-right") || document.querySelector("header") || document.querySelector(".topbar");
      if (topbar) {
        chip = document.createElement("div");
        chip.id = "scanner-status-chip";
        chip.className = "scanner-chip";
        chip.title = "USB Barcode/IMEI Scanner Status. Click to toggle sound.";
        chip.style.cssText = "display:inline-flex;align-items:center;gap:6px;background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.3);color:#059669;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;cursor:pointer;user-select:none;transition:all 0.2s ease;";
        chip.innerHTML = `<span id="scanner-indicator" style="width:8px;height:8px;border-radius:50%;background:#10b981;display:inline-block;"></span> <span id="scanner-text">Scanner: Ready</span> <span id="scanner-audio-icon" style="font-size:11px;">🔔</span>`;
        chip.onclick = function () {
          soundEnabled = !soundEnabled;
          const aIcon = document.getElementById("scanner-audio-icon");
          if (aIcon) aIcon.innerText = soundEnabled ? "🔔" : "🔕";
          showToast(soundEnabled ? "Scanner Sound: Enabled" : "Scanner Sound: Muted", true);
        };
        topbar.prepend(chip);
      }
    }
  }

  function updateChipStatus(text, latencyMs = null, isError = false) {
    const chipText = document.getElementById("scanner-text");
    const indicator = document.getElementById("scanner-indicator");
    const chip = document.getElementById("scanner-status-chip");
    if (chipText) {
      chipText.innerText = latencyMs ? `Scan (${latencyMs}ms)` : text;
    }
    if (indicator) {
      indicator.style.background = isError ? "#ef4444" : "#10b981";
    }
    if (chip) {
      chip.style.borderColor = isError ? "rgba(239,68,68,0.5)" : "rgba(16,185,129,0.5)";
      chip.style.color = isError ? "#dc2626" : "#059669";
      // Pulse animation
      chip.style.transform = "scale(1.06)";
      setTimeout(() => {
        chip.style.transform = "scale(1)";
        if (chipText && latencyMs) {
          setTimeout(() => {
            chipText.innerText = "Scanner: Ready";
          }, 3500);
        }
      }, 200);
    }
  }

  // Global Keydown Listener with Leakage Prevention
  window.addEventListener("keydown", function (e) {
    const now = Date.now();
    const interval = now - lastKeyTime;
    lastKeyTime = now;

    const activeEl = document.activeElement;
    const isInputElement = activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.isContentEditable);

    // Enter or Tab indicates scan complete
    if (e.key === "Enter" || e.key === "Tab") {
      if (buffer.length >= minBarcodeLen) {
        // High confidence scanner burst
        e.preventDefault();
        e.stopPropagation();

        const codeChars = buffer.map(b => b.char).join("");
        const totalDuration = now - buffer[0].time;
        const avgInterval = totalDuration / buffer.length;

        // Restore corrupted active input if characters leaked into it
        if (isInputElement && focusedInputSnapshot !== null) {
          activeEl.value = focusedInputSnapshot;
        }

        buffer = [];
        focusedInputSnapshot = null;

        // De-duplication check: ignore repeat scans within 300ms
        if (codeChars === lastScannedCode && (now - lastScannedTimestamp) < 300) {
          return;
        }
        lastScannedCode = codeChars;
        lastScannedTimestamp = now;

        handleScannedCode(codeChars.trim(), Math.round(avgInterval));
        return;
      }
      buffer = [];
      focusedInputSnapshot = null;
      return;
    }

    // Only collect single character printable keys
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      if (buffer.length === 0) {
        // First character of potential burst
        if (isInputElement) {
          focusedInputSnapshot = activeEl.value;
        } else {
          focusedInputSnapshot = null;
        }
        buffer.push({ char: e.key, time: now });
      } else {
        if (interval <= maxIntervalMs) {
          // Scanner burst confirmed!
          buffer.push({ char: e.key, time: now });
          // If typing inside an input element, stop propagation to prevent leaking
          if (isInputElement && buffer.length >= 3) {
            e.preventDefault();
            e.stopPropagation();
          }
        } else {
          // User is hand typing slowly (>45ms)
          buffer = [{ char: e.key, time: now }];
          if (isInputElement) {
            focusedInputSnapshot = activeEl.value;
          }
        }
      }
    }
  }, true);

  // Router handler
  async function handleScannedCode(code, avgLatencyMs = 12) {
    updateChipStatus(`Scan: ${code.slice(-6)}`, avgLatencyMs);

    // Notify test page if open
    if (window.onScannerTestEvent) {
      window.onScannerTestEvent({ code, latency: avgLatencyMs, timestamp: new Date().toLocaleTimeString() });
    }

    const currentPath = window.location.pathname;
    let context = "GENERAL";
    if (currentPath === "/pos" || currentPath === "/") context = "POS";
    else if (currentPath.includes("/purchasing") || currentPath.includes("/purchases")) context = "PURCHASE";
    else if (currentPath.includes("/returns")) context = "RETURNS";
    else if (currentPath.includes("/repairing") || currentPath.includes("/repairs")) context = "REPAIR";
    else if (currentPath.includes("/trade-in")) context = "TRADE_IN";
    else if (currentPath.includes("/software")) context = "SOFTWARE";

    // Call page-specific handler if registered
    if (window.onGlobalScan && typeof window.onGlobalScan === "function") {
      const handled = window.onGlobalScan(code, context);
      if (handled) {
        playSuccessBeep();
        flashScreen("rgba(16, 185, 129, 0.4)");
        return;
      }
    }

    // Context routes
    if (context === "POS" && window.posAddToCart) {
      // Let POS handle directly
      window.posAddToCart(code);
      return;
    }
    if (context === "PURCHASE" && window.purchaseAddScannedImei) {
      window.purchaseAddScannedImei(code);
      return;
    }
    if (context === "REPAIR" && window.repairAddScannedImei) {
      window.repairAddScannedImei(code);
      return;
    }
    if (context === "TRADE_IN" && window.tradeInAddScannedImei) {
      window.tradeInAddScannedImei(code);
      return;
    }

    // Default route: /api/scan-route
    try {
      const resp = await fetch("/api/scan-route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code, context: context })
      });
      const data = await resp.json();

      if (data.success) {
        playSuccessBeep();
        flashScreen("rgba(16, 185, 129, 0.4)");

        if (context === "POS" && window.posAddToCart) {
          window.posAddToCart(data);
        } else if (context === "PURCHASE" && window.purchaseAddScannedImei) {
          window.purchaseAddScannedImei(data);
        } else {
          openImeiLifeCardModal(code);
        }
      } else {
        playErrorBeep();
        flashScreen("rgba(239, 68, 68, 0.5)");
        updateChipStatus("Not Found", null, true);
        showToast(data.error || "Item not found for code: " + code, false);
      }
    } catch (err) {
      playErrorBeep();
      updateChipStatus("Error", null, true);
      showToast("Scanner route error: " + err.message, false);
    }
  }

  // Device Life Card Modal
  window.openImeiLifeCardModal = async function (imei) {
    try {
      const resp = await fetch("/api/imei-lookup?q=" + encodeURIComponent(imei));
      const data = await resp.json();
      if (!data.success || !data.lifecycle) {
        showToast("No record found for IMEI: " + imei, false);
        return;
      }
      renderLifeCardModal(data.lifecycle);
    } catch (e) {
      showToast("Error retrieving IMEI record", false);
    }
  };

  function renderLifeCardModal(c) {
    let m = document.getElementById("imei-life-modal");
    if (!m) {
      m = document.createElement("div");
      m.id = "imei-life-modal";
      m.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:99999;display:flex;align-items:center;justify-content:center;overflow-y:auto;padding:20px;";
      document.body.appendChild(m);
    }
    const u = c.unit;
    const s = c.sale;

    let saleHtml = s ? `
      <div style="background:#ecfdf5;border:1px solid #a7f3d0;padding:12px;border-radius:8px;margin-top:10px;">
        <h4 style="color:#065f46;margin-bottom:6px;font-size:14px;font-weight:700;">🛒 Sold to Customer</h4>
        <p><strong>Customer:</strong> ${s.customer_name} (${s.customer_phone || 'No phone'})</p>
        <p><strong>Invoice #:</strong> ${s.invoice_no} on ${s.sale_date}</p>
        <p><strong>Sale Price:</strong> Rs. ${Number(s.unit_price).toLocaleString()} (${s.payment_method})</p>
      </div>
    ` : `<div style="background:#fef3c7;border:1px solid #fde68a;padding:10px;border-radius:8px;margin-top:10px;color:#92400e;font-weight:600;">Status: Currently in shop stock. Ready for sale.</div>`;

    m.innerHTML = `
      <div style="background:var(--card-bg, #fff);border-radius:12px;padding:24px;max-width:540px;width:100%;color:var(--text, #0f172a);box-shadow:0 25px 50px -12px rgba(0,0,0,0.5);border:1px solid var(--border, #e2e8f0);">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border, #e2e8f0);padding-bottom:12px;">
          <h3 style="font-size:18px;font-weight:800;">📱 Device Life Card</h3>
          <button onclick="document.getElementById('imei-life-modal').style.display='none'" style="background:none;border:none;font-size:20px;cursor:pointer;color:inherit;">✕</button>
        </div>
        <div style="margin-top:14px;font-size:13px;line-height:1.6;">
          <h2 style="font-size:18px;color:#2563eb;margin-bottom:4px;font-weight:800;">${u.brand} ${u.model_name}</h2>
          <p><strong>Specs:</strong> ${u.ram} RAM / ${u.storage} Storage · <strong>Color:</strong> ${u.color}</p>
          <p><strong>IMEI 1:</strong> <code style="background:rgba(0,0,0,0.06);padding:2px 8px;border-radius:4px;font-weight:bold;">${u.imei1}</code></p>
          ${u.imei2 ? `<p><strong>IMEI 2:</strong> <code style="background:rgba(0,0,0,0.06);padding:2px 8px;border-radius:4px;font-weight:bold;">${u.imei2}</code></p>` : ''}
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0;background:rgba(0,0,0,0.03);padding:12px;border-radius:8px;">
            <div><strong>Condition:</strong> ${u.condition}</div>
            <div><strong>PTA Status:</strong> ${u.pta_status}</div>
            <div><strong>Cost Price:</strong> Rs. ${Number(u.cost_price).toLocaleString()}</div>
            <div><strong>Retail Price:</strong> Rs. ${Number(u.retail_price).toLocaleString()}</div>
            <div><strong>Date In:</strong> ${u.date_in}</div>
            <div><strong>Supplier:</strong> ${u.supplier_name || 'N/A'}</div>
          </div>
          ${saleHtml}
          ${c.repairs && c.repairs.length ? `<p style="margin-top:10px;"><strong>Repair History:</strong> ${c.repairs.length} job(s) logged</p>` : ''}
        </div>
        <div style="text-align:right;margin-top:18px;">
          <button onclick="document.getElementById('imei-life-modal').style.display='none'" style="background:#2563eb;color:#fff;border:none;padding:9px 20px;border-radius:8px;font-weight:bold;cursor:pointer;">Close</button>
        </div>
      </div>
    `;
    m.style.display = "flex";
  }

  // Auto initialize chip when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initScannerChip);
  } else {
    initScannerChip();
  }

  // Export globally
  window.ScannerEngine = {
    testScan: handleScannedCode,
    playSuccessBeep,
    playErrorBeep,
    flashScreen,
    showToast,
    updateChipStatus,
    setSoundEnabled: (v) => { soundEnabled = !!v; },
    isSoundEnabled: () => soundEnabled
  };
})();
