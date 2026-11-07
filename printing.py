# MOBILE & ACCESSORIES ERP — Universal Print Engine (Thermal 80/58mm, Labels & A4)
import json, re
from datetime import datetime
import db

def get_shop_info():
    prof = db.query_one("SELECT * FROM shop_profile WHERE id = 1")
    rows = db.query_all("SELECT key, value FROM settings")
    settings = {r["key"]: r["value"] for r in rows}
    
    if prof:
        return {
            "name": prof.get("shop_name") or settings.get("shop_name", "PAK MOBILE & ACCESSORIES"),
            "tagline": prof.get("tagline") or settings.get("tagline", "Smartphones, Accessories & Repairs"),
            "phone": prof.get("phone1") or settings.get("phone", "+92 300 1234567"),
            "phone2": prof.get("phone2") or "",
            "whatsapp": prof.get("whatsapp") or settings.get("whatsapp", "+92 300 1234567"),
            "email": prof.get("email") or "",
            "address": prof.get("address") or settings.get("address", "Main Market, Gulberg, Lahore"),
            "city": prof.get("city") or "Lahore",
            "ntn_tax_no": prof.get("ntn_tax_no") or "",
            "warranty_terms": prof.get("warranty_terms") or settings.get("warranty_terms", "7 Days Checking Warranty for Used Phones. 1 Year for Official New Phones."),
            "return_policy": prof.get("return_policy") or "7 Days checking return policy with original receipt.",
            "footer_note": prof.get("receipt_footer") or settings.get("footer_note", "Thank you for visiting! Developed by Ahmed"),
            "printer_width": settings.get("receipt_printer_width", "80"), # 80 or 58
            "auto_print": settings.get("receipt_auto_print", "1") == "1",
            "cash_drawer": settings.get("cash_drawer_pulse", "1") == "1",
            "has_logo": bool(prof.get("has_logo")),
            "profile_version": prof.get("profile_version", 1)
        }

    return {
        "name": settings.get("shop_name", "PAK MOBILE & ACCESSORIES"),
        "tagline": settings.get("tagline", "Smartphones, Accessories & Repairs"),
        "phone": settings.get("phone", "+92 300 1234567"),
        "whatsapp": settings.get("whatsapp", "+92 300 1234567"),
        "address": settings.get("address", "Main Market, Gulberg, Lahore"),
        "warranty_terms": settings.get("warranty_terms", "7 Days Checking Warranty for Used Phones. 1 Year for Official New Phones."),
        "footer_note": settings.get("footer_note", "Thank you for visiting! Developed by Ahmed"),
        "printer_width": settings.get("receipt_printer_width", "80"), # 80 or 58
        "auto_print": settings.get("receipt_auto_print", "1") == "1",
        "cash_drawer": settings.get("cash_drawer_pulse", "1") == "1",
        "has_logo": False,
        "profile_version": 1
    }

def print_wrapper_html(title, content_html, width_mm="80", auto_print=True):
    """Generates standalone Unicode-safe HTML document optimized for thermal or A4 printing."""
    is_a4 = str(width_mm).upper() == "A4"
    body_width = "100%" if is_a4 else f"{width_mm}mm"
    font_size = "12px" if is_a4 else ("12px" if width_mm == "80" else "10.5px")
    
    script_print = "window.onload = function(){ window.print(); };" if auto_print else ""
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  @page {{
    size: {"A4" if is_a4 else f"{width_mm}mm auto"};
    margin: {"10mm" if is_a4 else "2mm"};
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  }}
  body {{
    background: #fff;
    color: #000;
    width: {body_width};
    margin: 0 auto;
    font-size: {font_size};
    line-height: 1.35;
    padding: {"20px" if is_a4 else "6px"};
  }}
  .text-center {{ text-align: center; }}
  .text-right {{ text-align: right; }}
  .text-left {{ text-align: left; }}
  .bold {{ font-weight: bold; }}
  .divider {{
    border-top: 1px dashed #000;
    margin: 6px 0;
  }}
  .double-divider {{
    border-top: 2px solid #000;
    margin: 6px 0;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 4px 0;
  }}
  th, td {{
    padding: 3px 1px;
    font-size: inherit;
    vertical-align: top;
  }}
  th {{
    border-bottom: 1px solid #000;
    text-align: left;
  }}
  .barcode-box {{
    text-align: center;
    margin: 6px 0;
  }}
  .barcode-text {{
    font-family: monospace;
    font-size: 11px;
    letter-spacing: 2px;
  }}
  .no-print {{
    display: flex;
    justify-content: center;
    gap: 10px;
    margin-bottom: 12px;
    padding: 10px;
    background: #f1f5f9;
    border-radius: 6px;
  }}
  @media print {{
    .no-print {{ display: none !important; }}
  }}
  .btn-print {{
    background: #2563eb;
    color: #fff;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    cursor: pointer;
    font-weight: bold;
  }}
</style>
</head>
<body>
  <div class="no-print">
    <button class="btn-print" onclick="window.print()">🖨️ Print Now</button>
    <button class="btn-print" style="background:#475569" onclick="closePrintWindow()">✕ Close</button>
    <button class="btn-print" style="background:#0284c7" onclick="returnToApp()">← Back to App</button>
  </div>
  {content_html}
  <script>
  function closePrintWindow() {{
    window.close();
    setTimeout(function() {{
      if (document.referrer && document.referrer.indexOf(window.location.host) !== -1) {{
        window.location.href = document.referrer;
      }} else if (window.history.length > 1) {{
        window.history.back();
      }} else {{
        window.location.href = '/pos';
      }}
    }}, 120);
  }}
  function returnToApp() {{
    if (document.referrer && document.referrer.indexOf(window.location.host) !== -1) {{
      window.location.href = document.referrer;
    }} else if (window.history.length > 1) {{
      window.history.back();
    }} else {{
      window.location.href = '/pos';
    }}
  }}
  {script_print}
  </script>
</body>
</html>"""

def get_thermal_logo_bytes(printer_width="80"):
    """Returns pre-processed 1-bit ESC-POS raster bytes for direct thermal printing."""
    col = "logo_thermal_58" if str(printer_width) == "58" else "logo_thermal_80"
    row = db.query_one(f"SELECT {col} FROM shop_profile WHERE id = 1 AND has_logo = 1")
    if row and row.get(col):
        return bytes(row[col])
    return b""

def render_not_found(title="Record Not Found", message="The requested transaction record could not be found."):
    body = f"""
    <div class="text-center" style="padding: 24px 10px;">
      <h3 style="color:#ef4444; font-size:15px; margin-bottom:8px;">⚠️ {title}</h3>
      <p style="color:#64748b; font-size:11.5px; margin-bottom:14px;">{message}</p>
    </div>
    """
    return print_wrapper_html("Not Found", body, width_mm="80", auto_print=False)

def render_sale_receipt(sale_id):
    sale = db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))
    if not sale:
        return render_not_found("Invoice Not Found", f"No sale invoice found with ID #{sale_id}.")
    items = db.query_all("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,))
    shop = get_shop_info()
    
    # Items Table
    rows_html = ""
    for it in items:
        spec = f"<br><small style='color:#333'>{it['variant_details']}</small>" if it['variant_details'] else ""
        imei_str = ""
        if it["imei1"]:
            imei_str += f"<br><small><strong>IMEI 1:</strong> {it['imei1']}</small>"
        if it["imei2"]:
            imei_str += f"<br><small><strong>IMEI 2:</strong> {it['imei2']}</small>"
        if it["warranty_till"]:
            imei_str += f"<br><small><strong>Warranty:</strong> Till {it['warranty_till']}</small>"
            
        rows_html += f"""
        <tr>
          <td><strong>{it['item_name']}</strong>{spec}{imei_str}</td>
          <td class="text-center">{it['qty']}</td>
          <td class="text-right">Rs. {it['unit_price']:,.0f}</td>
          <td class="text-right">Rs. {it['line_total']:,.0f}</td>
        </tr>
        """
        
    discount_html = f"<tr><td colspan='3'>Discount:</td><td class='text-right'>- Rs. {sale['discount_amount']:,.0f}</td></tr>" if sale['discount_amount'] > 0 else ""
    balance_html = f"<tr><td colspan='3' class='bold' style='color:#b91c1c'>Balance Due:</td><td class='text-right bold' style='color:#b91c1c'>Rs. {sale['balance_due']:,.0f}</td></tr>" if sale['balance_due'] > 0 else ""
    change_html = f"<tr><td colspan='3'>Change Given:</td><td class='text-right'>Rs. {sale['change_amount']:,.0f}</td></tr>" if sale['change_amount'] > 0 else ""

    # Subsequent payments towards this invoice
    inv_payments = db.query_all("""
        SELECT * FROM udhaar_ledger 
        WHERE sale_id = ? AND transaction_type IN ('PAYMENT', 'INSTALLMENT_PAYMENT')
        ORDER BY id ASC
    """, (sale["id"],))
    subseq_payments_html = ""
    if inv_payments:
        subseq_payments_html = "<div class='divider'></div><p class='bold' style='font-size:10px; margin-bottom:2px;'>Payments Collected Against This Bill:</p><table style='font-size:9.5px; width:100%;'>"
        for ip in inv_payments:
            ip_date = (ip.get("transaction_date") or ip["timestamp"][:10])
            subseq_payments_html += f"<tr><td>{ip_date} ({ip.get('payment_method') or 'CASH'})</td><td class='text-right'>Rs. {ip['amount']:,.0f}</td><td class='text-right'>Bal: Rs. {ip['balance_after']:,.0f}</td></tr>"
        subseq_payments_html += "</table>"

    # WhatsApp share text
    wa_msg = f"Invoice #{sale['invoice_no']} from {shop['name']}. Total: Rs. {sale['grand_total']:,.0f}. Paid: Rs. {sale['paid_amount']:,.0f}."
    wa_link = f"https://wa.me/?text={wa_msg.replace(' ', '%20')}"

    logo_img = '<div style="margin-bottom:6px;"><img src="/api/shop/logo" style="max-height:50px; max-width:180px; object-fit:contain;" alt="Logo"></div>' if shop.get("has_logo") else ''

    body = f"""
    <div class="text-center">
      {logo_img}
      <h2 style="font-size:16px; font-weight:800; letter-spacing:0.5px;">{shop['name']}</h2>
      <p style="font-size:11px;">{shop['tagline']}</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
      <p style="font-size:11px; font-weight:600;">📞 {shop['phone']} | WhatsApp: {shop['whatsapp']}</p>
    </div>
    <div class="divider"></div>
    <table style="font-size:11px;">
      <tr><td><strong>Invoice #:</strong> {sale['invoice_no']}</td><td class="text-right"><strong>Date:</strong> {sale['created_at'][:16]}</td></tr>
      <tr><td><strong>Customer:</strong> {sale['customer_name']}</td><td class="text-right"><strong>Phone:</strong> {sale['customer_phone'] or 'N/A'}</td></tr>
      <tr><td><strong>Cashier:</strong> {sale['salesperson_name'] or 'Counter'}</td><td class="text-right"><strong>Payment:</strong> {sale['payment_method']}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <thead>
        <tr>
          <th>Item / Model</th>
          <th class="text-center">Qty</th>
          <th class="text-right">Price</th>
          <th class="text-right">Total</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <div class="double-divider"></div>
    <table style="font-size:12px;">
      <tr><td colspan="3">Subtotal:</td><td class="text-right">Rs. {sale['subtotal']:,.0f}</td></tr>
      {discount_html}
      <tr class="bold" style="font-size:14px;"><td colspan="3">GRAND TOTAL:</td><td class="text-right">Rs. {sale['grand_total']:,.0f}</td></tr>
      <tr><td colspan="3">Amount Paid:</td><td class="text-right">Rs. {sale['paid_amount']:,.0f}</td></tr>
      {change_html}
      {balance_html}
    </table>
    {subseq_payments_html}
    <div class="divider"></div>
    <div class="barcode-box">
      <div class="barcode-text">*{sale['invoice_no']}*</div>
      <small style="font-size:9.5px; color:#444;">Scan barcode for instant return / reprint</small>
    </div>
    <div class="divider"></div>
    <div style="font-size:10px; color:#333; text-align:justify; margin:4px 0;">
      <strong>Terms & Conditions:</strong><br>
      {shop['warranty_terms']}
    </div>
    <div class="text-center" style="margin-top:8px;">
      <p style="font-size:10.5px; font-weight:bold;">{shop['footer_note']}</p>
      <p class="no-print" style="margin-top:6px;"><a href="{wa_link}" target="_blank" style="color:#059669; font-weight:bold; font-size:11px; text-decoration:none;">📲 Share Bill on WhatsApp</a></p>
    </div>
    """
    return print_wrapper_html(f"Receipt - {sale['invoice_no']}", body, width_mm=shop['printer_width'], auto_print=shop['auto_print'])

def render_repair_ticket(repair_id):
    job = db.query_one("SELECT * FROM repair_jobs WHERE id = ?", (repair_id,))
    if not job:
        return render_not_found("Job Not Found", f"No repair job found with ID #{repair_id}.")
    shop = get_shop_info()
    parts = db.query_all("SELECT * FROM repair_parts_used WHERE repair_id = ?", (job["id"],))
    
    parts_html = ""
    if parts:
        parts_html = """
        <div class="divider"></div>
        <p class="bold" style="font-size:11px;">Parts Replaced / Fitted:</p>
        <table>
        """
        for p in parts:
            parts_html += f"""<tr><td>{p['part_name']} x {p['qty']}</td><td class="text-right">Rs. {p['charge_price'] * p['qty']:,.0f}</td></tr>"""
        parts_html += "</table>"
    
    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#2563eb;">{'REPAIR DELIVERY & WARRANTY RECEIPT' if job['status'] == 'DELIVERED' else 'REPAIR JOB CARD (CUSTOMER COPY)'}</p>
      <p style="font-size:10.5px;">📞 {shop['phone']} | WhatsApp: {shop['whatsapp']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Ticket No:</strong> {job['job_no']}</td><td class="text-right"><strong>Date:</strong> {job['created_at'][:16]}</td></tr>
      <tr><td><strong>Customer:</strong> {job['customer_name']}</td><td class="text-right"><strong>Phone:</strong> {job['customer_phone']}</td></tr>
      <tr><td><strong>Device:</strong> {job['brand']} {job['model']}</td><td class="text-right"><strong>Status:</strong> {job['status']}</td></tr>
      <tr><td colspan="2"><strong>IMEI:</strong> {job['imei'] or 'N/A'}</td></tr>
      <tr><td colspan="2"><strong>Accessories:</strong> {job['accessories_received'] or 'Device Only'}</td></tr>
    </table>
    <div class="divider"></div>
    <div style="margin:4px 0;">
      <p><strong>Reported Problem / Fault:</strong></p>
      <p style="background:#f8fafc; padding:4px; border:1px solid #e2e8f0; font-size:11px;">{job['complaint']}</p>
    </div>
    {parts_html}
    <div class="divider"></div>
    <table style="margin-top:4px;">
      {f"<tr><td>Labor Charges:</td><td class='text-right'>Rs. {job['labor_charge']:,.0f}</td></tr>" if job['labor_charge'] > 0 else ""}
      <tr class="bold"><td>Total Charged:</td><td class="text-right">Rs. {job['total_charged'] or job['estimate']:,.0f}</td></tr>
      <tr><td>Advance Paid:</td><td class="text-right">Rs. {job['advance_paid']:,.0f}</td></tr>
      <tr class="bold" style="font-size:13px;"><td>Balance Due:</td><td class="text-right">Rs. {job['balance_due']:,.0f}</td></tr>
      <tr><td>Expected Delivery:</td><td class="text-right">{job['expected_delivery'] or 'Same Day'}</td></tr>
    </table>
    <div class="divider"></div>
    <div class="barcode-box">
      <div class="barcode-text">*{job['job_no']}*</div>
      <small style="font-size:9.5px;">Scan ticket barcode for quick lookup</small>
    </div>
    <div class="divider"></div>
    <div style="font-size:9.5px; color:#555;">
      • Devices not collected within 30 days are not the shop's responsibility.<br>
      • Repair warranty: {job['warranty_days']} Days on replaced parts only.
    </div>
    <p class="text-center bold" style="margin-top:6px; font-size:10.5px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"Repair - {job['job_no']}", body, width_mm="80", auto_print=True)

def render_software_receipt(service_id):
    job = db.query_one("SELECT * FROM software_jobs WHERE id = ?", (service_id,))
    if not job:
        return render_not_found("Service Not Found", f"No software service job found with ID #{service_id}.")
    shop = get_shop_info()
    
    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#16a34a;">SOFTWARE SERVICE RECEIPT</p>
      <p style="font-size:10.5px;">📞 {shop['phone']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Ticket #:</strong> {job['ticket_no']}</td><td class="text-right"><strong>Date:</strong> {job['created_at'][:16]}</td></tr>
      <tr><td><strong>Device:</strong> {job['brand_model']}</td><td class="text-right"><strong>IMEI:</strong> {job['imei'] or 'N/A'}</td></tr>
      <tr><td><strong>Customer:</strong> {job['customer_name'] or 'Walk-in'}</td><td class="text-right"><strong>Phone:</strong> {job['customer_phone'] or 'N/A'}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <thead>
        <tr><th>Service Provided</th><th class="text-right">Amount</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>{job['service_name']}</strong><br><small>{job['notes'] or ''}</small></td>
          <td class="text-right bold">Rs. {job['price_charged']:,.0f}</td>
        </tr>
      </tbody>
    </table>
    <div class="double-divider"></div>
    <table>
      <tr class="bold" style="font-size:13px;"><td>TOTAL PAID:</td><td class="text-right">Rs. {job['price_charged']:,.0f}</td></tr>
      <tr><td>Payment Method:</td><td class="text-right">{job['payment_method']}</td></tr>
      <tr><td>Technician:</td><td class="text-right">{job['technician_name']}</td></tr>
    </table>
    <div class="divider"></div>
    <div class="barcode-box">
      <div class="barcode-text">*{job['ticket_no']}*</div>
    </div>
    <p class="text-center" style="font-size:10px; margin-top:4px;">Software services carry no warranty once device leaves the shop.</p>
    <p class="text-center bold" style="margin-top:6px; font-size:10.5px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"Software - {job['ticket_no']}", body, width_mm="80", auto_print=True)

def render_trade_in_slip(trade_in_id):
    t = db.query_one("SELECT * FROM trade_ins WHERE id = ?", (trade_in_id,))
    if not t:
        return render_not_found("Trade-In Record Not Found", f"No device trade-in found with ID #{trade_in_id}.")
    shop = get_shop_info()
    
    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#7c3aed;">DEVICE BUYBACK / TRADE-IN VOUCHER</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Voucher #:</strong> {t['trade_in_no']}</td><td class="text-right"><strong>Date:</strong> {t['created_at'][:16]}</td></tr>
      <tr><td><strong>Seller Name:</strong> {t['customer_name']}</td><td class="text-right"><strong>Phone:</strong> {t['customer_phone']}</td></tr>
      <tr><td colspan="2"><strong>CNIC Number:</strong> {t['customer_cnic'] or 'Not provided'}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Device Bought:</strong></td><td class="text-right">{t['brand']} {t['model']}</td></tr>
      <tr><td><strong>IMEI 1:</strong></td><td class="text-right"><code>{t['imei1']}</code></td></tr>
      <tr><td><strong>Condition:</strong></td><td class="text-right">{t['condition']}</td></tr>
      <tr><td><strong>Battery Health:</strong></td><td class="text-right">{t['battery_health']}%</td></tr>
      <tr class="bold" style="font-size:13px;"><td>PURCHASE PRICE PAID:</td><td class="text-right">Rs. {t['purchase_price']:,.0f}</td></tr>
    </table>
    <div class="divider"></div>
    <p style="font-size:10px; text-align:justify; color:#333;">
      <strong>Seller Declaration:</strong> I hereby confirm that I am the legal owner of this device and it is free from any theft, police complaint or illegal record. I accept the payment amount specified above.
    </p>
    <br>
    <table>
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Seller Signature</td>
        <td style="width:10%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Shop Signature</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:12px; font-size:10px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"TradeIn - {t['trade_in_no']}", body, width_mm="80", auto_print=True)

def render_return_receipt(return_id):
    ret = db.query_one("SELECT * FROM returns WHERE id = ?", (return_id,))
    if not ret:
        return render_not_found("Return Voucher Not Found", f"No return voucher found with ID #{return_id}.")
    shop = get_shop_info()
    
    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#dc2626;">SALE RETURN & REFUND VOUCHER</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Return #:</strong> {ret['return_no']}</td><td class="text-right"><strong>Date:</strong> {ret['created_at'][:16]}</td></tr>
      <tr><td><strong>Original Invoice:</strong> {ret['invoice_no']}</td><td class="text-right"><strong>Customer:</strong> {ret['customer_name'] or 'Walk-in'}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Return Reason:</strong></td><td class="text-right">{ret['reason'] or 'Customer Return'}</td></tr>
      <tr><td><strong>Refund Mode:</strong></td><td class="text-right"><strong>{ret['refund_type']}</strong></td></tr>
      <tr class="bold" style="font-size:13px; color:#b91c1c;"><td>TOTAL REFUND AMOUNT:</td><td class="text-right">Rs. {ret['refund_amount']:,.0f}</td></tr>
    </table>
    <div class="divider"></div>
    <p style="font-size:10px; text-align:center; color:#555;">
      Returned items verified & restocked.<br>
      {shop['footer_note']}
    </p>
    <p class="text-center bold" style="margin-top:12px; font-size:10px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"Return - {ret['return_no']}", body, width_mm=shop['printer_width'], auto_print=True)

def render_barcode_label(item_name, variant_details, imei_or_barcode, price, width_mm="50"):
    """50x30 mm thermal barcode sticker for phones & accessories."""
    body = f"""
    <div style="text-align:center; font-family:sans-serif; padding:2px;">
      <p style="font-size:11px; font-weight:800; white-space:nowrap; overflow:hidden;">{item_name[:24]}</p>
      <p style="font-size:10px; color:#333;">{variant_details[:28]}</p>
      <div style="margin:4px 0;">
        <span style="font-family:monospace; font-size:14px; font-weight:bold; letter-spacing:1px;">*{imei_or_barcode}*</span>
      </div>
      <p style="font-size:11px; font-weight:bold;">Rs. {float(price):,.0f}</p>
    </div>
    """
    return print_wrapper_html("Barcode Label", body, width_mm=width_mm, auto_print=True)

def render_supplier_payment_receipt(ledger_id):
    """Renders thermal receipt for payment made to supplier."""
    entry = db.query_one("""
        SELECT l.*, s.name AS supplier_name, s.phone AS supplier_phone, s.company
        FROM supplier_ledger l
        JOIN suppliers s ON l.supplier_id = s.id
        WHERE l.id = ?
    """, (ledger_id,))
    if not entry:
        return render_not_found("Payment Entry Not Found", f"No supplier payment entry found with ID #{ledger_id}.")
    shop = get_shop_info()

    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#0d9488;">SUPPLIER PAYMENT VOUCHER</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Voucher Ref:</strong> #{entry['id']}</td><td class="text-right"><strong>Date:</strong> {entry['timestamp'][:16]}</td></tr>
      <tr><td><strong>Supplier:</strong> {entry['supplier_name']}</td><td class="text-right"><strong>Company:</strong> {entry['company'] or '-'}</td></tr>
      <tr><td><strong>Phone:</strong> {entry['supplier_phone']}</td><td class="text-right"><strong>Method:</strong> {entry['payment_method']}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <tr class="bold" style="font-size:14px;">
        <td>AMOUNT PAID:</td>
        <td class="text-right">Rs. {entry['amount']:,.0f}</td>
      </tr>
      <tr>
        <td>Remaining Balance:</td>
        <td class="text-right">Rs. {entry['balance_after']:,.0f}</td>
      </tr>
      {f'<tr><td colspan="2"><em>Ref: {entry["reference"]} - {entry["notes"]}</em></td></tr>' if entry['reference'] or entry['notes'] else ''}
    </table>
    <div class="divider"></div>
    <br>
    <table>
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Receiver Signature</td>
        <td style="width:10%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Authorized By</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:12px; font-size:10px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"SupplierPay-{entry['id']}", body, width_mm="80", auto_print=True)

def render_udhaar_payment_receipt(ledger_id):
    """Renders thermal receipt (80mm) for udhaar / credit payment collected from customer."""
    entry = db.query_one("""
        SELECT u.*, c.name AS customer_name, c.phone AS customer_phone, c.cnic AS customer_cnic,
               COALESCE(usr.full_name, usr.username, 'Staff') AS staff_name
        FROM udhaar_ledger u
        JOIN customers c ON u.customer_id = c.id
        LEFT JOIN users usr ON u.user_id = usr.id
        WHERE u.id = ?
    """, (ledger_id,))
    if not entry:
        return render_not_found("Payment Record Not Found", f"No Udhaar payment found with voucher ID #{ledger_id}.")
    shop = get_shop_info()

    phone_disp = "-" if not entry["customer_phone"] or entry["customer_phone"].startswith("NOP-") else entry["customer_phone"]
    date_disp = entry["transaction_date"] if entry.get("transaction_date") else (entry.get("timestamp") or "")[:16]

    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#16a34a;">UDHAAR PAYMENT RECOVERY RECEIPT</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
      <p style="font-size:10px;">📞 {shop['phone']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Voucher Ref:</strong> #UDH-{entry['id']:05d}</td><td class="text-right"><strong>Date:</strong> {date_disp}</td></tr>
      <tr><td><strong>Customer:</strong> {entry['customer_name']}</td><td class="text-right"><strong>Phone:</strong> {phone_disp}</td></tr>
      <tr><td><strong>Payment Mode:</strong> {entry['payment_method']}</td><td class="text-right"><strong>Received By:</strong> {entry['staff_name']}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <tr class="bold" style="font-size:14px; color:#16a34a;">
        <td>AMOUNT COLLECTED:</td>
        <td class="text-right">Rs. {entry['amount']:,.0f}</td>
      </tr>
      <tr style="font-weight:bold; color:{'#dc2626' if entry['balance_after'] > 0 else '#16a34a'};">
        <td>Remaining Khata Balance:</td>
        <td class="text-right">Rs. {entry['balance_after']:,.0f}</td>
      </tr>
      {f'<tr><td colspan="2" style="font-size:11px; color:#555; padding-top:4px;"><em>Note: {entry["notes"]}</em></td></tr>' if entry['notes'] else ''}
    </table>
    <div class="divider"></div>
    <p class="text-center" style="font-size:11px; font-weight:bold; color:#16a34a; margin-top:6px;">
      {'✅ KHATA FULLY CLEARED! Zero Balance Due.' if entry['balance_after'] <= 0 else 'Thank you for your payment.'}
    </p>
    <br>
    <table>
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Customer Signature</td>
        <td style="width:10%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Cashier / Seal</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:10px; font-size:10px;">Developed by Ahmed &bull; Keep this receipt for your records</p>
    """
    return print_wrapper_html(f"UdhaarPay-{entry['id']}", body, width_mm="80", auto_print=True)

def render_installment_contract(installment_id):
    """Renders A4 / 80mm installment financing agreement and monthly payment schedule."""
    inst = db.query_one("""
        SELECT i.*, c.name AS customer_name, c.phone AS customer_phone, c.cnic AS customer_cnic, c.address AS customer_address, s.invoice_no
        FROM installments i
        JOIN customers c ON i.customer_id = c.id
        LEFT JOIN sales s ON i.sale_id = s.id
        WHERE i.id = ?
    """, (installment_id,))
    if not inst:
        return render_not_found("Agreement Not Found", f"No installment agreement found with ID #{installment_id}.")
    
    schedule = db.query_all("SELECT * FROM installment_schedule WHERE installment_id = ? ORDER BY installment_no ASC", (installment_id,))
    shop = get_shop_info()

    sched_rows = ""
    for s in schedule:
        status_badge = "✓ PAID" if s['status'] == 'PAID' else s['status']
        sched_rows += f"""
        <tr>
          <td style="padding:4px; border-bottom:1px solid #ddd;">#{s['installment_no']}</td>
          <td style="padding:4px; border-bottom:1px solid #ddd;">{s['due_date']}</td>
          <td style="padding:4px; border-bottom:1px solid #ddd; text-align:right;">Rs. {s['due_amount']:,.0f}</td>
          <td style="padding:4px; border-bottom:1px solid #ddd; text-align:center;">{status_badge}</td>
        </tr>
        """

    body = f"""
    <div class="text-center">
      <h2 style="font-size:18px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:12px; font-weight:bold; color:#b45309;">EASY INSTALLMENT CONTRACT & FINANCING PLAN</p>
      <p style="font-size:11px;">📍 {shop['address']} | 📞 {shop['phone']}</p>
    </div>
    <hr style="margin:10px 0;">
    <table style="width:100%; font-size:12px;">
      <tr><td><strong>Contract No:</strong> INST-{inst['id']:04d}</td><td style="text-align:right;"><strong>Invoice Ref:</strong> {inst['invoice_no'] or 'N/A'}</td></tr>
      <tr><td><strong>Customer Name:</strong> {inst['customer_name']}</td><td style="text-align:right;"><strong>Phone:</strong> {inst['customer_phone']}</td></tr>
      <tr><td><strong>CNIC:</strong> {inst['customer_cnic'] or '-'}</td><td style="text-align:right;"><strong>Start Date:</strong> {inst['start_date']}</td></tr>
      <tr><td colspan="2"><strong>Address:</strong> {inst['customer_address'] or '-'}</td></tr>
    </table>
    <hr style="margin:10px 0;">
    <h4 style="margin-bottom:6px;">GUARANTORS (ZAMEEN)</h4>
    <table style="width:100%; font-size:11.5px; background:#f9fafb; padding:6px; border:1px solid #e5e7eb;">
      <tr>
        <td style="width:50%;"><strong>1st Guarantor:</strong> {inst['guarantor1_name'] or 'None'}<br>Phone: {inst['guarantor1_phone'] or '-'}<br>CNIC: {inst['guarantor1_cnic'] or '-'}</td>
        <td style="width:50%;"><strong>2nd Guarantor:</strong> {inst['guarantor2_name'] or 'None'}<br>Phone: {inst['guarantor2_phone'] or '-'}<br>CNIC: {inst['guarantor2_cnic'] or '-'}</td>
      </tr>
    </table>
    <hr style="margin:10px 0;">
    <table style="width:100%; font-size:12px;">
      <tr><td>Total Price:</td><td style="text-align:right;">Rs. {inst['total_price']:,.0f}</td></tr>
      <tr><td>Down Payment Paid:</td><td style="text-align:right; color:#16a34a;">- Rs. {inst['down_payment']:,.0f}</td></tr>
      <tr style="font-weight:bold;"><td>Financed Total Payable:</td><td style="text-align:right;">Rs. {inst['financed_amount']:,.0f}</td></tr>
      <tr style="font-weight:bold; color:#b45309;"><td>Monthly Installment ({inst['total_months']} Months):</td><td style="text-align:right;">Rs. {inst['monthly_due']:,.0f} / month</td></tr>
    </table>
    <h4 style="margin:12px 0 6px 0;">PAYMENT SCHEDULE</h4>
    <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
      <tr style="background:#eee; font-weight:bold;">
        <th style="padding:4px; text-align:left;">#</th>
        <th style="padding:4px; text-align:left;">Due Date</th>
        <th style="padding:4px; text-align:right;">Due Amount</th>
        <th style="padding:4px; text-align:center;">Status</th>
      </tr>
      {sched_rows}
    </table>
    <div style="margin-top:20px; font-size:11px;">
      <p><strong>Terms:</strong> Late payments will incur service follow-up. Customer and guarantors are jointly responsible until all installments are cleared.</p>
    </div>
    <br><br>
    <table style="width:100%;">
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:28%;">Customer Thumb / Sign</td>
        <td style="width:8%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:28%;">Guarantor Sign</td>
        <td style="width:8%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:28%;">Shop Stamp & Sign</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:16px; font-size:11px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"InstallmentContract-{inst['id']}", body, width_mm="A4", auto_print=True)

def render_installment_payment_receipt(schedule_id):
    """Renders thermal 80mm receipt for monthly installment collection."""
    sch = db.query_one("""
        SELECT s.*, i.customer_id, i.total_months, c.name AS customer_name, c.phone AS customer_phone, c.balance_udhaar
        FROM installment_schedule s
        JOIN installments i ON s.installment_id = i.id
        JOIN customers c ON i.customer_id = c.id
        WHERE s.id = ?
    """, (schedule_id,))
    if not sch:
        return render_not_found("Payment Record Not Found", f"No installment payment found with ID #{schedule_id}.")
    shop = get_shop_info()

    body = f"""
    <div class="text-center">
      <h2 style="font-size:15px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:11px; font-weight:bold; color:#16a34a;">INSTALLMENT PAYMENT RECEIPT</p>
      <p style="font-size:10.5px;">📍 {shop['address']}</p>
    </div>
    <div class="divider"></div>
    <table>
      <tr><td><strong>Receipt #:</strong> {sch['receipt_no']}</td><td class="text-right"><strong>Date:</strong> {sch['paid_date']}</td></tr>
      <tr><td><strong>Customer:</strong> {sch['customer_name']}</td><td class="text-right"><strong>Phone:</strong> {sch['customer_phone']}</td></tr>
      <tr><td><strong>Installment:</strong> Month #{sch['installment_no']} of {sch['total_months']}</td><td class="text-right"><strong>Status:</strong> {sch['status']}</td></tr>
    </table>
    <div class="divider"></div>
    <table>
      <tr class="bold" style="font-size:14px;">
        <td>COLLECTED AMOUNT:</td>
        <td class="text-right">Rs. {sch['paid_amount']:,.0f}</td>
      </tr>
      <tr>
        <td>Remaining Balance Due:</td>
        <td class="text-right">Rs. {sch['balance_udhaar']:,.0f}</td>
      </tr>
    </table>
    <div class="divider"></div>
    <p class="text-center bold" style="margin-top:10px; font-size:10.5px;">Keep this receipt as official payment proof.</p>
    <p class="text-center bold" style="margin-top:8px; font-size:10px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"InstPay-{sch['id']}", body, width_mm="80", auto_print=True)

def render_day_closing_z_report(target_date):
    """Renders 80mm thermal Z-Report for daily cash drawer closing and reconciliation."""
    import accounting
    data = accounting.get_day_closing_data(target_date)
    closing = db.query_one("SELECT * FROM day_closings WHERE closing_date = ?", (target_date,))
    
    act_cash = closing["actual_cash"] if closing and closing["actual_cash"] is not None else data["expected_cash"]
    op_cash = closing["opening_cash"] if closing and closing["opening_cash"] is not None else data["opening_cash"]
    diff = (act_cash - data["expected_cash"]) if not closing else closing["cash_difference"]
    closed_at = closing["closed_at"] if closing else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    closed_by = closing["closed_by_name"] if closing else "Counter Admin"

    shop = get_shop_info()
    diff_color = "#16a34a" if diff >= 0 else "#dc2626"
    diff_status = "BALANCED" if diff == 0 else ("SURPLUS" if diff > 0 else "SHORTAGE")

    # Expenses by category rows
    exp_cat_rows = ""
    for cat in data["expenses_by_category"]:
        exp_cat_rows += f"""
        <tr>
          <td>{cat['category']}</td>
          <td class="text-right">Rs. {cat['total']:,.0f}</td>
        </tr>
        """
    if not exp_cat_rows:
        exp_cat_rows = "<tr><td colspan='2' class='text-center' style='color:#777;'>No expenses recorded</td></tr>"

    # Itemized expenses rows (Which expenses occurred with full details)
    exp_item_rows = ""
    for ex in data.get("expenses_list", []):
        acc = "Cash Drawer" if ex.get("is_cash") else ex.get("payment_method", "Bank")
        desc = ex.get("description") or ex.get("category") or "Expense"
        amt = float(ex.get("amount") or 0)
        exp_item_rows += f"""
        <tr style="border-bottom:1px dotted #e2e8f0;">
          <td style="padding:2px 0;">
            <div style="font-weight:bold; font-size:10px;">{desc}</div>
            <div style="font-size:9px; color:#555;">{ex.get('category')} &bull; {acc}</div>
          </td>
          <td class="text-right" style="vertical-align:top; font-weight:bold; font-size:10.5px;">Rs. {amt:,.0f}</td>
        </tr>
        """
    if not exp_item_rows:
        exp_item_rows = "<tr><td colspan='2' class='text-center' style='color:#777; font-size:10px; padding:3px 0;'>No itemized expenses</td></tr>"

    # Products sold today
    prods_sold = db.query_all("""
        SELECT si.item_name, si.variant_details, si.item_type, SUM(si.qty) as qty, SUM(si.line_total) as total
        FROM sale_items si
        JOIN sales s ON si.sale_id = s.id
        WHERE (s.transaction_date = ? OR (s.transaction_date = '' AND substr(s.created_at, 1, 10) = ?))
          AND s.status NOT IN ('CANCELLED', 'VOIDED')
          AND (si.is_returned IS NULL OR si.is_returned = 0)
        GROUP BY si.item_name, si.variant_details
        ORDER BY total DESC
    """, (target_date, target_date))
    prods_sold_rows = ""
    for p in prods_sold:
        specs = f" ({p['variant_details']})" if p.get("variant_details") else ""
        prods_sold_rows += f"""
        <tr style="border-bottom:1px dotted #e2e8f0; font-size:10px;">
          <td style="padding:2px 0;">{p['item_name']}{specs} <strong style="color:#0f172a;">x{p['qty']}</strong></td>
          <td class="text-right bold" style="padding:2px 0;">Rs. {float(p['total'] or 0):,.0f}</td>
        </tr>
        """
    if not prods_sold_rows:
        prods_sold_rows = "<tr><td colspan='2' class='text-center' style='color:#777; font-size:10px; padding:3px 0;'>No products sold today</td></tr>"

    body = f"""
    <div class="text-center">
      <h2 style="font-size:16px; font-weight:800;">{shop['name']}</h2>
      <p style="font-size:12px; font-weight:bold; color:#0f172a;">DAILY CLOSING Z-REPORT</p>
      <p style="font-size:10.5px;">Date: {target_date} | Closed: {closed_at[:16]}</p>
      <p style="font-size:10px;">Closed By: {closed_by}</p>
    </div>
    <div class="divider"></div>
    <p class="bold" style="font-size:11.5px; margin-bottom:2px;">CASH INFLOWS (DRAWER):</p>
    <table>
      <tr><td>Opening Cash:</td><td class="text-right">Rs. {op_cash:,.0f}</td></tr>
      <tr><td>POS Cash Sales:</td><td class="text-right">Rs. {data['cash_sales']:,.0f}</td></tr>
      <tr><td>Udhaar Collected (Cash):</td><td class="text-right">Rs. {data['udhaar_received']:,.0f}</td></tr>
      <tr><td>Hardware Repairs (Cash):</td><td class="text-right">Rs. {data['repair_income']:,.0f}</td></tr>
      <tr><td>Software Services (Cash):</td><td class="text-right">Rs. {data['software_income']:,.0f}</td></tr>
      <tr><td>Quick Services Commission:</td><td class="text-right">Rs. {data['quick_service_income']:,.0f}</td></tr>
      <tr class="bold" style="border-top:1px dashed #999;"><td>Total Cash In:</td><td class="text-right">Rs. {data['total_cash_in']:,.0f}</td></tr>
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:11.5px; margin-bottom:2px;">CASH OUTFLOWS (PAID OUT):</p>
    <table>
      <tr><td>Shop Expenses (Cash Drawer):</td><td class="text-right">- Rs. {data['cash_expenses_total']:,.0f}</td></tr>
      <tr><td>Supplier Payments (Cash):</td><td class="text-right">- Rs. {data['supplier_payments']:,.0f}</td></tr>
      <tr><td>Customer Refunds (Cash):</td><td class="text-right">- Rs. {data['refunds']:,.0f}</td></tr>
      <tr class="bold" style="border-top:1px dashed #999;"><td>Total Cash Out:</td><td class="text-right">- Rs. {data['total_cash_out']:,.0f}</td></tr>
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:11.5px; margin-bottom:2px;">DRAWER RECONCILIATION:</p>
    <table>
      <tr class="bold"><td>EXPECTED CASH:</td><td class="text-right">Rs. {data['expected_cash']:,.0f}</td></tr>
      <tr class="bold" style="font-size:13px;"><td>ACTUAL CASH COUNTED:</td><td class="text-right">Rs. {act_cash:,.0f}</td></tr>
      <tr class="bold" style="color:{diff_color}; font-size:13px;">
        <td>DIFFERENCE ({diff_status}):</td>
        <td class="text-right">Rs. {diff:+,.0f}</td>
      </tr>
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:11px; margin-bottom:2px;">PRODUCTS SOLD TODAY:</p>
    <table style="font-size:10.5px;">
      {prods_sold_rows}
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:11px; margin-bottom:2px;">EXPENSES BY CATEGORY:</p>
    <table style="font-size:10.5px;">
      {exp_cat_rows}
      <tr style="border-top:1px solid #ddd; font-weight:bold;">
        <td>Cash Drawer Expenses:</td>
        <td class="text-right">Rs. {data['cash_expenses_total']:,.0f}</td>
      </tr>
      <tr style="font-weight:bold; color:#555;">
        <td>Bank / Wallet Expenses:</td>
        <td class="text-right">Rs. {data['non_cash_expenses_total']:,.0f}</td>
      </tr>
      <tr style="border-top:1px dashed #999; font-weight:bold;">
        <td>Total Shop Expenses:</td>
        <td class="text-right">Rs. {data['total_expenses']:,.0f}</td>
      </tr>
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:11px; margin-bottom:2px;">ITEMIZED EXPENSES (DETAILS):</p>
    <table style="font-size:10px;">
      {exp_item_rows}
    </table>
    <div class="divider"></div>
    <p class="bold" style="font-size:10.5px; color:#555;">NON-CASH TURNOVER & OTHER:</p>
    <table style="color:#444; font-size:10.5px;">
      <tr><td>Card Payments:</td><td class="text-right">Rs. {data['card_sales']:,.0f}</td></tr>
      <tr><td>Online / Bank Transfers:</td><td class="text-right">Rs. {data['online_sales']:,.0f}</td></tr>
      <tr><td>New Udhaar Created Today:</td><td class="text-right">Rs. {data['udhaar_sales']:,.0f}</td></tr>
      <tr><td>Bank/Wallet Expenses:</td><td class="text-right">Rs. {data['non_cash_expenses_total']:,.0f}</td></tr>
    </table>
    <div class="divider"></div>
    <br>
    <table>
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Cashier Sign</td>
        <td style="width:10%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:45%;">Manager Sign</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:10px; font-size:10px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"ZReport-{target_date}", body, width_mm="80", auto_print=True)

def render_monthly_report(year, month):
    """Renders comprehensive A4 monthly financial statement and profit summary."""
    import accounting
    rep = accounting.get_monthly_report(year, month)
    e = rep["earnings"]
    shop = get_shop_info()

    # Expenses rows
    exp_rows = ""
    for exp in rep["expenses_by_category"]:
        exp_rows += f"""
        <tr>
          <td style="padding:4px; border-bottom:1px solid #eee;">{exp['category']}</td>
          <td style="padding:4px; border-bottom:1px solid #eee; text-align:right;">Rs. {exp['total']:,.0f}</td>
        </tr>
        """
    if not exp_rows:
        exp_rows = "<tr><td colspan='2' style='padding:4px; text-align:center; color:#888;'>No expenses recorded for this month</td></tr>"

    # Top selling models rows
    top_rows = ""
    for m in rep["top_selling_models"]:
        top_rows += f"""
        <tr>
          <td style="padding:4px; border-bottom:1px solid #eee;">{m['brand']} {m['model_name']}</td>
          <td style="padding:4px; border-bottom:1px solid #eee; text-align:center;">{m['total_sold']} units</td>
          <td style="padding:4px; border-bottom:1px solid #eee; text-align:right;">Rs. {m['revenue']:,.0f}</td>
        </tr>
        """
    if not top_rows:
        top_rows = "<tr><td colspan='3' style='padding:4px; text-align:center; color:#888;'>No phone sales recorded this month</td></tr>"

    body = f"""
    <div style="text-align:center; margin-bottom:15px;">
      <h1 style="font-size:22px; font-weight:800;">{shop['name']}</h1>
      <h3 style="font-size:14px; color:#4338ca; margin:4px 0;">MONTHLY BUSINESS & PROFIT STATEMENT</h3>
      <p style="font-size:12px;"><strong>Month:</strong> {rep['month']} | 📍 {shop['address']} | 📞 {shop['phone']}</p>
    </div>
    <hr style="margin:12px 0;">

    <h3 style="font-size:14px; margin-bottom:6px;">1. FIVE REVENUE & EARNINGS STREAMS</h3>
    <table style="width:100%; border-collapse:collapse; font-size:12px;">
      <tr style="background:#f1f5f9; font-weight:bold;">
        <th style="padding:6px; text-align:left; border:1px solid #cbd5e1;">Business Stream</th>
        <th style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Revenue / Volume</th>
        <th style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Direct Cost</th>
        <th style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Net Profit</th>
      </tr>
      <tr>
        <td style="padding:6px; border:1px solid #cbd5e1;"><strong>Phone Retail Sales</strong> ({e['stream1_phones']['units_sold']} units)</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream1_phones']['revenue']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream1_phones']['cost']:,.0f}</td>
        <td style="padding:6px; text-align:right; font-weight:bold; color:#16a34a; border:1px solid #cbd5e1;">Rs. {e['stream1_phones']['profit']:,.0f}</td>
      </tr>
      <tr>
        <td style="padding:6px; border:1px solid #cbd5e1;"><strong>Accessories & Glass</strong> ({e['stream2_accessories']['items_sold']} items)</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream2_accessories']['revenue']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream2_accessories']['cost']:,.0f}</td>
        <td style="padding:6px; text-align:right; font-weight:bold; color:#16a34a; border:1px solid #cbd5e1;">Rs. {e['stream2_accessories']['profit']:,.0f}</td>
      </tr>
      <tr>
        <td style="padding:6px; border:1px solid #cbd5e1;"><strong>Hardware Repairs</strong> ({e['stream3_repairs']['jobs_delivered']} jobs)</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream3_repairs']['revenue']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream3_repairs']['cost']:,.0f}</td>
        <td style="padding:6px; text-align:right; font-weight:bold; color:#16a34a; border:1px solid #cbd5e1;">Rs. {e['stream3_repairs']['profit']:,.0f}</td>
      </tr>
      <tr>
        <td style="padding:6px; border:1px solid #cbd5e1;"><strong>Software Services</strong> ({e['stream4_software']['tickets_completed']} tickets)</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream4_software']['revenue']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream4_software']['cost']:,.0f}</td>
        <td style="padding:6px; text-align:right; font-weight:bold; color:#16a34a; border:1px solid #cbd5e1;">Rs. {e['stream4_software']['profit']:,.0f}</td>
      </tr>
      <tr>
        <td style="padding:6px; border:1px solid #cbd5e1;"><strong>Quick Services</strong> (EasyPaisa/Load comm.)</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['stream5_quick_services']['volume']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">-</td>
        <td style="padding:6px; text-align:right; font-weight:bold; color:#16a34a; border:1px solid #cbd5e1;">Rs. {e['stream5_quick_services']['profit']:,.0f}</td>
      </tr>
      <tr style="background:#f8fafc; font-weight:bold;">
        <td style="padding:6px; border:1px solid #cbd5e1;">TOTAL GROSS EARNINGS</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">Rs. {e['total_revenue']:,.0f}</td>
        <td style="padding:6px; text-align:right; border:1px solid #cbd5e1;">-</td>
        <td style="padding:6px; text-align:right; color:#16a34a; font-size:13px; border:1px solid #cbd5e1;">Rs. {e['total_gross_profit']:,.0f}</td>
      </tr>
    </table>

    <div style="display:flex; justify-content:space-between; margin-top:15px; gap:20px;">
      <div style="flex:1;">
        <h3 style="font-size:13px; margin-bottom:6px;">2. EXPENSES BREAKDOWN</h3>
        <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
          <tr style="background:#f1f5f9; font-weight:bold;">
            <th style="padding:4px; text-align:left;">Category</th>
            <th style="padding:4px; text-align:right;">Amount</th>
          </tr>
          {exp_rows}
          <tr style="font-weight:bold; background:#fff1f2;">
            <td style="padding:4px;">TOTAL EXPENSES</td>
            <td style="padding:4px; text-align:right; color:#e11d48;">Rs. {e['total_expenses']:,.0f}</td>
          </tr>
        </table>
      </div>

      <div style="flex:1;">
        <h3 style="font-size:13px; margin-bottom:6px;">3. TOP 5 SELLING MODELS</h3>
        <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
          <tr style="background:#f1f5f9; font-weight:bold;">
            <th style="padding:4px; text-align:left;">Model</th>
            <th style="padding:4px; text-align:center;">Qty</th>
            <th style="padding:4px; text-align:right;">Revenue</th>
          </tr>
          {top_rows}
        </table>
      </div>
    </div>

    <div style="background:#f0fdf4; border:2px solid #86efac; border-radius:6px; padding:12px; margin-top:20px;">
      <table style="width:100%; font-size:14px; font-weight:bold;">
        <tr>
          <td>Total Gross Profit:</td>
          <td style="text-align:right; color:#15803d;">Rs. {e['total_gross_profit']:,.0f}</td>
        </tr>
        <tr>
          <td>Less Total Business Expenses:</td>
          <td style="text-align:right; color:#b91c1c;">- Rs. {e['total_expenses']:,.0f}</td>
        </tr>
        <tr style="font-size:18px; border-top:1px solid #86efac;">
          <td style="padding-top:6px;">NET CLEAR PROFIT:</td>
          <td style="padding-top:6px; text-align:right; color:#16a34a;">Rs. {e['net_profit']:,.0f}</td>
        </tr>
      </table>
    </div>

    <div style="margin-top:15px; font-size:11.5px; color:#475569;">
      <p><strong>Inventory Health Alert:</strong> {rep['aging_stock']['aging_count']} unsold phone(s) are aging in stock (> 30 days) with capital tie-up of Rs. {rep['aging_stock']['aging_value']:,.0f}.</p>
    </div>

    <br><br>
    <table style="width:100%;">
      <tr>
        <td style="border-top:1px solid #000; text-align:center; width:30%;">Prepared By</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #000; text-align:center; width:30%;">Owner / Director Sign</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:20px; font-size:11px;">Developed by Ahmed</p>
    """
    return print_wrapper_html(f"MonthlyReport-{rep['month']}", body, width_mm="A4", auto_print=True)

def render_a4_reorder_sheet(items):
    """Renders comprehensive A4 Purchase Advice & Low Stock Reorder Sheet."""
    shop = get_shop_info()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    rows_html = ""
    tot_est_capital = 0.0
    for idx, it in enumerate(items, 1):
        suggested = int(it.get("suggested_reorder_qty") or 0)
        last_cost = float(it.get("last_cost") or 0)
        est_line = suggested * last_cost
        tot_est_capital += est_line
        
        status_color = "#ef4444" if it.get("state") == "OUT" else "#f59e0b"
        status_label = "OUT OF STOCK" if it.get("state") == "OUT" else f"LOW ({it.get('current_stock')})"
        
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:6px 8px; text-align:center;">{idx}</td>
          <td style="padding:6px 8px;"><strong>{it.get('brand')} {it.get('model_name')}</strong><br><small style="color:#64748b;">{it.get('specs', '')}</small></td>
          <td style="padding:6px 8px;">{it.get('category')}</td>
          <td style="padding:6px 8px; text-align:center; font-weight:bold; color:{status_color};">{status_label}</td>
          <td style="padding:6px 8px; text-align:center;">{it.get('effective_level')}</td>
          <td style="padding:6px 8px; text-align:center; font-weight:bold; background:#f0fdf4; color:#16a34a; font-size:13px;">{suggested}</td>
          <td style="padding:6px 8px;">{it.get('last_supplier_name') or 'Wholesale Hub'}<br><small>{it.get('last_supplier_phone') or ''}</small></td>
          <td style="padding:6px 8px; text-align:right;">Rs. {last_cost:,.0f}</td>
          <td style="padding:6px 8px; text-align:right; font-weight:bold;">Rs. {est_line:,.0f}</td>
        </tr>
        """
        
    body = f"""
    <div style="border-bottom:2px solid #0f172a; padding-bottom:10px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
      <div>
        <h1 style="font-size:20px; font-weight:800; color:#0f172a;">{shop['name']}</h1>
        <p style="font-size:11.5px; color:#475569;">{shop['address']} &bull; Phone/WhatsApp: {shop['phone']}</p>
      </div>
      <div style="text-align:right;">
        <h2 style="font-size:16px; font-weight:bold; color:#e11d48;">STOCK REORDER & PURCHASE ADVICE</h2>
        <p style="font-size:11px; color:#64748b;">Generated: {now_str}</p>
      </div>
    </div>

    <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:10px 14px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
      <div>
        <span style="font-weight:bold; color:#991b1b; font-size:13px;">Total Urgent Items Requiring Reorder:</span>
        <span style="font-size:15px; font-weight:800; color:#b91c1c; margin-left:6px;">{len(items)} Items</span>
      </div>
      <div>
        <span style="font-weight:bold; color:#0f172a; font-size:13px;">Estimated Reorder Capital:</span>
        <span style="font-size:16px; font-weight:800; color:#15803d; margin-left:6px;">Rs. {tot_est_capital:,.0f}</span>
      </div>
    </div>

    <table style="width:100%; border-collapse:collapse; font-size:11.5px; margin-bottom:20px;">
      <thead>
        <tr style="background:#0f172a; color:#fff; text-align:left;">
          <th style="padding:6px 8px; width:30px; text-align:center;">#</th>
          <th style="padding:6px 8px;">Product & Specs</th>
          <th style="padding:6px 8px;">Category</th>
          <th style="padding:6px 8px; text-align:center;">Current Stock</th>
          <th style="padding:6px 8px; text-align:center;">Alert Level</th>
          <th style="padding:6px 8px; text-align:center;">Suggested Qty</th>
          <th style="padding:6px 8px;">Last Supplier</th>
          <th style="padding:6px 8px; text-align:right;">Unit Cost</th>
          <th style="padding:6px 8px; text-align:right;">Est. Total</th>
        </tr>
      </thead>
      <tbody>
        {rows_html or '<tr><td colspan="9" style="text-align:center; padding:20px; color:#888;">All inventory stock levels are healthy! No items need reorder.</td></tr>'}
      </tbody>
    </table>

    <br><br>
    <table style="width:100%; margin-top:24px;">
      <tr>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Inventory Manager Sign</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Purchase Approved By</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:20px; font-size:11px; text-align:center; color:#94a3b8;">Developed by Ahmed &bull; Mobile Shop ERP</p>
    """
    return print_wrapper_html("Stock-Reorder-Advice-Sheet", body, width_mm="A4", auto_print=True)

def render_a4_top_sellers_report(report_data):
    """Renders comprehensive A4 Category-Wise Top Selling & Velocity Report."""
    shop = get_shop_info()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    items = report_data.get("items", [])
    
    rows_html = ""
    for idx, it in enumerate(items, 1):
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:6px 8px; text-align:center; font-weight:bold;">{idx}</td>
          <td style="padding:6px 8px;"><strong>{it.get('brand')} {it.get('model_name')}</strong><br><small style="color:#64748b;">{it.get('specs', '')}</small></td>
          <td style="padding:6px 8px;">{it.get('category')}</td>
          <td style="padding:6px 8px; text-align:center; font-weight:800; font-size:13px; color:#2563eb;">{it.get('net_units_sold')}</td>
          <td style="padding:6px 8px; text-align:center;">{it.get('current_stock')}</td>
          <td style="padding:6px 8px; text-align:right;">Rs. {it.get('gross_revenue', 0):,.0f}</td>
          <td style="padding:6px 8px; text-align:right; font-weight:bold; color:#16a34a;">Rs. {it.get('net_profit', 0):,.0f}</td>
          <td style="padding:6px 8px; text-align:center; font-weight:bold;">{it.get('margin_percent', 0)}%</td>
          <td style="padding:6px 8px; text-align:center; background:#f0fdf4; color:#15803d; font-weight:bold;">{it.get('reorder_suggestion', 0)}</td>
        </tr>
        """
        
    body = f"""
    <div style="border-bottom:2px solid #0f172a; padding-bottom:10px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
      <div>
        <h1 style="font-size:20px; font-weight:800; color:#0f172a;">{shop['name']}</h1>
        <p style="font-size:11.5px; color:#475569;">{shop['address']} &bull; Phone/WhatsApp: {shop['phone']}</p>
      </div>
      <div style="text-align:right;">
        <h2 style="font-size:16px; font-weight:bold; color:#2563eb;">TOP-SELLING PRODUCTS & VELOCITY REPORT</h2>
        <p style="font-size:11px; color:#64748b;">Period: {report_data.get('start_date')} to {report_data.get('end_date')} ({report_data.get('period').upper()})</p>
      </div>
    </div>

    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:16px;">
      <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:6px; padding:10px; text-align:center;">
        <div style="font-size:10px; color:#1e40af; font-weight:bold;">NET UNITS SOLD</div>
        <div style="font-size:18px; font-weight:800; color:#1d4ed8; margin-top:2px;">{report_data.get('total_net_units', 0)} Units</div>
      </div>
      <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:10px; text-align:center;">
        <div style="font-size:10px; color:#166534; font-weight:bold;">GROSS REVENUE</div>
        <div style="font-size:18px; font-weight:800; color:#15803d; margin-top:2px;">Rs. {report_data.get('total_revenue', 0):,.0f}</div>
      </div>
      <div style="background:#fdf2f8; border:1px solid #fbcfe8; border-radius:6px; padding:10px; text-align:center;">
        <div style="font-size:10px; color:#9d174d; font-weight:bold;">TOTAL NET PROFIT</div>
        <div style="font-size:18px; font-weight:800; color:#be185d; margin-top:2px;">Rs. {report_data.get('total_profit', 0):,.0f}</div>
      </div>
      <div style="background:#faf5ff; border:1px solid #e9d5ff; border-radius:6px; padding:10px; text-align:center;">
        <div style="font-size:10px; color:#6b21a8; font-weight:bold;">AVERAGE MARGIN</div>
        <div style="font-size:18px; font-weight:800; color:#7e22ce; margin-top:2px;">{report_data.get('overall_margin_percent', 0)}%</div>
      </div>
    </div>

    <table style="width:100%; border-collapse:collapse; font-size:11.5px; margin-bottom:20px;">
      <thead>
        <tr style="background:#0f172a; color:#fff; text-align:left;">
          <th style="padding:6px 8px; width:30px; text-align:center;">#</th>
          <th style="padding:6px 8px;">Product & Variant</th>
          <th style="padding:6px 8px;">Category</th>
          <th style="padding:6px 8px; text-align:center;">Units Sold</th>
          <th style="padding:6px 8px; text-align:center;">In Stock</th>
          <th style="padding:6px 8px; text-align:right;">Revenue</th>
          <th style="padding:6px 8px; text-align:right;">Net Profit</th>
          <th style="padding:6px 8px; text-align:center;">Margin %</th>
          <th style="padding:6px 8px; text-align:center;">Reorder Adv.</th>
        </tr>
      </thead>
      <tbody>
        {rows_html or '<tr><td colspan="9" style="text-align:center; padding:20px; color:#888;">No sales recorded for this period.</td></tr>'}
      </tbody>
    </table>

    <table style="width:100%; margin-top:24px;">
      <tr>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Prepared By</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Owner Signature</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:20px; font-size:11px; text-align:center; color:#94a3b8;">Developed by Ahmed &bull; Mobile Shop ERP</p>
    """
    return print_wrapper_html("Top-Sellers-Velocity-Report", body, width_mm="A4", auto_print=True)

def render_daily_sales_report(start_date, end_date, salesperson_id=None, payment_method=None, is_admin=True):
    """Renders professional A4 Comprehensive Date-Wise / Single-Day Sales & Audit Statement."""
    import accounting
    summary = accounting.get_date_wise_sales_summary(
        start_date, end_date,
        salesperson_id=salesperson_id,
        payment_method=payment_method,
        is_admin=is_admin
    )
    det = accounting.get_detailed_sales_report_data(
        start_date, end_date,
        salesperson_id=salesperson_id,
        payment_method=payment_method,
        is_admin=is_admin
    )
    shop = get_shop_info()
    tot = summary["totals"]
    days = summary["days"]
    sales_list = det.get("sales", [])
    expenses_list = det.get("expenses", [])
    products_sold = det.get("products_sold", [])
    udhaar_recoveries = det.get("udhaar_recoveries", [])
    det_tot = det.get("totals", {})
    day_closing = det.get("day_closing")

    # 1. Detailed Invoices & Itemized Products Sold Table
    sales_items_html = ""
    for s in sales_list:
        status_color = "#16a34a" if s.get("status") == "COMPLETED" else ("#dc2626" if s.get("status") in ("RETURNED", "CANCELLED", "VOIDED") else "#f59e0b")
        status_badge = f'<span style="background:{status_color}; color:#fff; padding:2px 6px; border-radius:3px; font-size:9.5px; font-weight:bold;">{s.get("status")}</span>'
        pm_badge = f'<span style="background:#e2e8f0; color:#1e293b; padding:2px 6px; border-radius:3px; font-size:9.5px; font-weight:bold;">{s.get("payment_method") or "CASH"}</span>'
        
        inner_items = ""
        for it in s.get("items", []):
            ret_mark = '<span style="color:#dc2626; font-weight:bold; font-size:9px;"> [RETURNED]</span>' if it.get("is_returned") else ''
            imei_str = ""
            if it.get("imei1") or it.get("imei2"):
                imeis = [f"IMEI1: {it['imei1']}"] if it.get("imei1") else []
                if it.get("imei2"):
                    imeis.append(f"IMEI2: {it['imei2']}")
                imei_str = f'<div style="font-size:9px; color:#475569; font-family:monospace; margin-top:1px;">{" | ".join(imeis)}</div>'
            specs_str = f'<span style="color:#64748b; font-size:9.5px;">({it["variant_details"]})</span>' if it.get("variant_details") else ''
            
            cost_col = f'<td style="text-align:right; font-size:10px; color:#64748b;">Rs. {float(it.get("cost_price") or 0):,.0f}</td>' if is_admin else ''
            profit_col = f'<td style="text-align:right; font-size:10px; font-weight:bold; color:{"#16a34a" if float(it.get("profit") or 0) >= 0 else "#dc2626"};">Rs. {float(it.get("profit") or 0):,.0f}</td>' if is_admin else ''

            inner_items += f"""
            <tr style="border-bottom:1px dotted #cbd5e1; font-size:10px; background:#fff;">
              <td style="padding:4px 6px;">
                <strong>{it.get('item_name') or 'Item'}</strong> {specs_str} {ret_mark}
                {imei_str}
              </td>
              <td style="padding:4px 6px; text-align:center;"><span style="background:#f1f5f9; padding:1px 4px; border-radius:2px; font-size:9px;">{it.get('item_type') or 'ACC'}</span></td>
              <td style="padding:4px 6px; text-align:center; font-weight:bold;">{it.get('qty')}</td>
              <td style="padding:4px 6px; text-align:right;">Rs. {float(it.get('unit_price') or 0):,.0f}</td>
              <td style="padding:4px 6px; text-align:right; color:#dc2626;">{f"-Rs. {float(it.get('discount') or 0):,.0f}" if float(it.get('discount') or 0) > 0 else "-"}</td>
              <td style="padding:4px 6px; text-align:right; font-weight:bold;">Rs. {float(it.get('line_total') or 0):,.0f}</td>
              {cost_col}
              {profit_col}
            </tr>
            """
        
        due_str = f'<span style="color:#dc2626; font-weight:bold; margin-left:4px;"> (Udhaar: Rs. {float(s.get("balance_due") or 0):,.0f})</span>' if float(s.get("balance_due") or 0) > 0 else ""
        cust_str = f"{s.get('customer_name') or 'Walk-in Customer'}"
        if s.get("customer_phone"):
            cust_str += f" &bull; {s.get('customer_phone')}"

        sales_items_html += f"""
        <div style="border:1px solid #cbd5e1; border-radius:6px; margin-bottom:10px; overflow:hidden; page-break-inside:avoid;">
          <div style="background:#f8fafc; padding:6px 10px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; font-size:11px; border-bottom:1px solid #cbd5e1;">
            <div>
              <strong style="color:#0f172a; font-size:12px;">Invoice #{s.get('invoice_no')}</strong> &bull; 
              <span style="color:#64748b;">{s.get('created_at', '')[:16]}</span> &bull; 
              <span>👤 {cust_str}</span> &bull; 
              <span style="color:#64748b;">Cashier: {s.get('staff_name')}</span>
            </div>
            <div style="display:flex; gap:6px; align-items:center;">
              {pm_badge}
              {status_badge}
              <span style="font-weight:bold; font-size:12px; color:#0f172a; margin-left:4px;">Total: Rs. {float(s.get('grand_total') or 0):,.0f}</span>
              {due_str}
            </div>
          </div>
          <table style="width:100%; border-collapse:collapse;">
            <thead>
              <tr style="background:#f1f5f9; color:#475569; font-size:9.5px; text-transform:uppercase;">
                <th style="padding:3px 6px; text-align:left;">Product & Specifications / IMEIs</th>
                <th style="padding:3px 6px; text-align:center;">Type</th>
                <th style="padding:3px 6px; text-align:center;">Qty</th>
                <th style="padding:3px 6px; text-align:right;">Rate</th>
                <th style="padding:3px 6px; text-align:right;">Disc.</th>
                <th style="padding:3px 6px; text-align:right;">Total</th>
                {('<th style="padding:3px 6px; text-align:right;">Cost</th><th style="padding:3px 6px; text-align:right;">Profit</th>' if is_admin else '')}
              </tr>
            </thead>
            <tbody>
              {inner_items or '<tr><td colspan="8" style="text-align:center; padding:6px; color:#888;">No items</td></tr>'}
            </tbody>
          </table>
        </div>
        """

    if not sales_items_html:
        sales_items_html = '<div style="padding:14px; text-align:center; color:#64748b; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:6px; font-size:11.5px;">No sales invoices recorded for this date/period.</div>'

    # 2. Itemized Expenses Rows (Which expenses occurred with full details)
    exp_details_html = ""
    for idx, ex in enumerate(expenses_list, 1):
        acc_label = "Cash Drawer" if ex.get("is_cash") else (ex.get("payment_method") or "Bank/Online")
        acc_badge = f'<span style="background:{"#dcfce7; color:#15803d" if ex.get("is_cash") else "#e0e7ff; color:#3730a3"}; padding:2px 5px; border-radius:3px; font-size:9.5px; font-weight:bold;">{acc_label}</span>'
        exp_details_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:10.5px;">
          <td style="padding:4px 6px; text-align:center; color:#64748b;">{idx}</td>
          <td style="padding:4px 6px; font-weight:bold; color:#0f172a;">{ex.get('eff_date', '')}</td>
          <td style="padding:4px 6px;">
            <strong>{ex.get('description') or ex.get('category')}</strong>
          </td>
          <td style="padding:4px 6px;"><span style="background:#f1f5f9; padding:2px 5px; border-radius:3px; font-size:10px;">{ex.get('category')}</span></td>
          <td style="padding:4px 6px;">{acc_badge}</td>
          <td style="padding:4px 6px; color:#64748b; font-size:10px;">{ex.get('user_name') or 'Admin'}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold; color:#dc2626;">Rs. {float(ex.get('amount') or 0):,.0f}</td>
        </tr>
        """
    if not exp_details_html:
        exp_details_html = '<tr><td colspan="7" style="text-align:center; padding:12px; color:#64748b;">No expenses recorded for this date/period.</td></tr>'

    # 3. Udhaar Recoveries Rows
    udhaar_rows_html = ""
    for idx, u in enumerate(udhaar_recoveries, 1):
        acc_label = "Cash Drawer" if u.get("is_cash") else (u.get("payment_method") or "Bank/Online")
        cust_name = u.get("customer_name") or "Customer"
        if u.get("customer_phone"):
            cust_name += f" ({u['customer_phone']})"
        udhaar_rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:10.5px;">
          <td style="padding:4px 6px; text-align:center; color:#64748b;">{idx}</td>
          <td style="padding:4px 6px;">{u.get('eff_date', '')}</td>
          <td style="padding:4px 6px; font-weight:bold;">Voucher #{u.get('id')}</td>
          <td style="padding:4px 6px;">{cust_name}</td>
          <td style="padding:4px 6px;">{acc_label}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold; color:#16a34a;">+Rs. {float(u.get('amount') or 0):,.0f}</td>
        </tr>
        """
    if not udhaar_rows_html:
        udhaar_rows_html = '<tr><td colspan="6" style="text-align:center; padding:10px; color:#64748b;">No credit / udhaar payments collected in this period.</td></tr>'

    # 4. Products Sold Summary Rows
    prod_summary_html = ""
    for idx, p in enumerate(products_sold, 1):
        specs_str = f" <span style='color:#64748b;'>({p['variant_details']})</span>" if p.get("variant_details") else ""
        prof_td = f'<td style="padding:4px 6px; text-align:right; font-weight:bold; color:{"#16a34a" if p.get("profit", 0) >= 0 else "#dc2626"};">Rs. {p.get("profit", 0):,.0f}</td>' if is_admin else ''
        prod_summary_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:10.5px;">
          <td style="padding:4px 6px; text-align:center; color:#64748b;">{idx}</td>
          <td style="padding:4px 6px;"><strong>{p['item_name']}</strong>{specs_str}</td>
          <td style="padding:4px 6px; text-align:center;"><span style="background:#f1f5f9; padding:2px 5px; border-radius:3px; font-size:9.5px;">{p['item_type']}</span></td>
          <td style="padding:4px 6px; text-align:center; font-weight:bold;">{p['qty']}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold;">Rs. {p['revenue']:,.0f}</td>
          {prof_td}
        </tr>
        """
    if not prod_summary_html:
        prod_summary_html = '<tr><td colspan="6" style="text-align:center; padding:10px; color:#64748b;">No product items sold in this period.</td></tr>'

    # 4b. Quick Services (EasyPaisa / JazzCash / Loads / Bills)
    quick_services = det.get("quick_services", [])
    qs_totals = det.get("qs_totals", {})
    qs_rows_html = ""
    for idx, q in enumerate(quick_services, 1):
        act = (q.get("action_type") or "SEND").strip().upper()
        amt = float(q.get("amount") or 0)
        comm = float(q.get("profit") or q.get("fee_commission") or 0)
        c_flow_amt = float(q.get("cash_flow_amount") or (amt + comm if act != "RECEIVE" else max(0.0, amt - comm)))
        
        if act in ("RECEIVE", "CASH_OUT", "WITHDRAWAL"):
            act_badge = '<span style="background:#fee2e2; color:#b91c1c; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;">📥 RECEIVE (Cash Out)</span>'
            flow_str = f'<span style="color:#dc2626; font-weight:bold;">-Rs. {c_flow_amt:,.0f} (Out)</span>'
        elif act == "LOAD":
            act_badge = '<span style="background:#f3e8ff; color:#7e22ce; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;">📱 LOAD</span>'
            flow_str = f'<span style="color:#16a34a; font-weight:bold;">+Rs. {c_flow_amt:,.0f} (In)</span>'
        elif act == "BILL":
            act_badge = '<span style="background:#e0f2fe; color:#0369a1; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;">💡 BILL</span>'
            flow_str = f'<span style="color:#16a34a; font-weight:bold;">+Rs. {c_flow_amt:,.0f} (In)</span>'
        else: # SEND
            act_badge = '<span style="background:#dcfce7; color:#15803d; padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;">📤 SEND (Cash-In)</span>'
            flow_str = f'<span style="color:#16a34a; font-weight:bold;">+Rs. {c_flow_amt:,.0f} (In)</span>'

        prof_td = f'<td style="padding:4px 6px; text-align:right; font-weight:bold; color:#16a34a;">+Rs. {comm:,.0f}</td>' if is_admin else ''
        net_label = f" <span style='color:#64748b;'>({q['network']})</span>" if q.get("network") else ""
        qs_rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:10.5px;">
          <td style="padding:4px 6px; text-align:center; color:#64748b;">{idx}</td>
          <td style="padding:4px 6px; color:#475569;">{q.get('timestamp', '')[:16]}</td>
          <td style="padding:4px 6px;"><strong>{q.get('service_type')}</strong>{net_label}</td>
          <td style="padding:4px 6px;">{act_badge}</td>
          <td style="padding:4px 6px; font-family:monospace;">{q.get('customer_phone') or '-'}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold;">Rs. {amt:,.0f}</td>
          {prof_td}
          <td style="padding:4px 6px; text-align:right;">{flow_str}</td>
          <td style="padding:4px 6px; font-size:10px; color:#64748b;">{q.get('notes') or '-'}</td>
        </tr>
        """
    if not qs_rows_html:
        qs_rows_html = '<tr><td colspan="9" style="text-align:center; padding:10px; color:#64748b;">No EasyPaisa, JazzCash, or Quick Service transactions recorded for this period.</td></tr>'

    # 5. Date-wise summary table (multi-day breakdown)
    rows_html = ""
    for d in days:
        cost_td = f'<td style="text-align:right;">Rs. {d["cost"]:,.0f}</td>' if is_admin else ''
        profit_td = f'<td style="text-align:right; font-weight:bold; color:{"#16a34a" if d["profit"] >= 0 else "#dc2626"};">Rs. {d["profit"]:,.0f}</td>' if is_admin else ''
        exp_td = f'<td style="text-align:right; color:#dc2626;">Rs. {d["expenses"]:,.0f}</td>' if is_admin else ''
        net_day_td = f'<td style="text-align:right; font-weight:800; color:{"#15803d" if d["net_of_day"] >= 0 else "#dc2626"};">Rs. {d["net_of_day"]:,.0f}</td>' if is_admin else ''

        rows_html += f"""
        <tr style="border-bottom:1px solid #f1f5f9;">
          <td style="padding:5px 6px; font-weight:bold;">{d['date']}</td>
          <td style="text-align:center;">{d['invoices_count']}</td>
          <td style="text-align:center;">{d['phones_sold']}</td>
          <td style="text-align:center;">{d['accessories_sold']}</td>
          <td style="text-align:right;">Rs. {d['gross_sale']:,.0f}</td>
          <td style="text-align:right; color:#dc2626;">{f'-Rs. {d["returns"]:,.0f}' if d["returns"] > 0 else '-'}</td>
          <td style="text-align:right; font-weight:bold;">Rs. {d['net_sale']:,.0f}</td>
          {cost_td}
          {profit_td}
          <td style="text-align:right; font-size:10.5px; color:#475569;">C: {d['cash_paid']:,.0f} | B: {d['online_paid']+d['card_paid']:,.0f} | U: {d['udhaar_amount']:,.0f}</td>
          {exp_td}
          {net_day_td}
        </tr>
        """

    tot_cost_th = f'<th style="text-align:right;">Rs. {tot.get("cost", 0):,.0f}</th>' if is_admin else ''
    tot_prof_th = f'<th style="text-align:right; color:{"#16a34a" if tot.get("profit", 0) >= 0 else "#dc2626"};">Rs. {tot.get("profit", 0):,.0f}</th>' if is_admin else ''
    tot_exp_th = f'<th style="text-align:right; color:#dc2626;">Rs. {tot.get("expenses", 0):,.0f}</th>' if is_admin else ''
    tot_net_day_th = f'<th style="text-align:right; color:{"#15803d" if tot.get("net_of_day", 0) >= 0 else "#dc2626"}; font-weight:800;">Rs. {tot.get("net_of_day", 0):,.0f}</th>' if is_admin else ''

    admin_headers = """
      <th style="padding:6px; text-align:right;">Cost</th>
      <th style="padding:6px; text-align:right;">Gross Profit</th>
    """ if is_admin else ""

    admin_headers_end = """
      <th style="padding:6px; text-align:right;">Expenses</th>
      <th style="padding:6px; text-align:right;">Net of Day</th>
    """ if is_admin else ""

    period_title = "DAILY COMPREHENSIVE SALES & BUSINESS AUDIT REPORT" if start_date == end_date else "DATE-WISE DAILY SALES & REVENUE REPORT"
    date_display = f"Date: <strong>{start_date}</strong>" if start_date == end_date else f"Period: <strong>{start_date}</strong> to <strong>{end_date}</strong>"

    # Day closing drawer box (if single day)
    drawer_reconcile_box = ""
    if day_closing:
        cl_rec = day_closing.get("existing_record")
        act_c = cl_rec["actual_cash"] if cl_rec and cl_rec.get("actual_cash") is not None else day_closing["expected_cash"]
        diff_c = (act_c - day_closing["expected_cash"]) if not cl_rec else cl_rec["cash_difference"]
        diff_col = "#16a34a" if diff_c >= 0 else "#dc2626"
        diff_st = "BALANCED" if diff_c == 0 else ("SURPLUS" if diff_c > 0 else "SHORTAGE")
        drawer_reconcile_box = f"""
        <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:10px 14px; margin-bottom:14px; page-break-inside:avoid;">
          <div style="font-size:12px; font-weight:bold; color:#0f172a; margin-bottom:6px; border-bottom:1px solid #e2e8f0; padding-bottom:4px;">
            🔒 CASH DRAWER RECONCILIATION SUMMARY (Z-AUDIT)
          </div>
          <div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; font-size:11px; text-align:center;">
            <div><span style="color:#64748b;">Opening Drawer:</span><div style="font-weight:bold; margin-top:2px;">Rs. {day_closing['opening_cash']:,.0f}</div></div>
            <div><span style="color:#16a34a;">Total Cash In:</span><div style="font-weight:bold; color:#16a34a; margin-top:2px;">+Rs. {day_closing['total_cash_in']:,.0f}</div></div>
            <div><span style="color:#dc2626;">Total Cash Out:</span><div style="font-weight:bold; color:#dc2626; margin-top:2px;">-Rs. {day_closing['total_cash_out']:,.0f}</div></div>
            <div><span style="color:#0284c7;">Expected Drawer:</span><div style="font-weight:800; color:#0284c7; margin-top:2px;">Rs. {day_closing['expected_cash']:,.0f}</div></div>
            <div><span style="color:#0f172a;">Counted / Diff:</span><div style="font-weight:800; color:{diff_col}; margin-top:2px;">Rs. {act_c:,.0f} ({diff_st})</div></div>
          </div>
        </div>
        """

    # Multi-day table section
    multiday_table_html = ""
    if start_date != end_date:
        multiday_table_html = f"""
        <div style="margin-bottom:16px;">
          <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:6px;">📅 DATE-WISE DAILY SUMMARY STATEMENT</h3>
          <table style="width:100%; border-collapse:collapse; font-size:10.5px; margin-bottom:8px;">
            <thead>
              <tr style="background:#0f172a; color:#fff;">
                <th style="padding:6px; text-align:left;">Date</th>
                <th style="padding:6px; text-align:center;">Bills</th>
                <th style="padding:6px; text-align:center;">Phones</th>
                <th style="padding:6px; text-align:center;">Acc</th>
                <th style="padding:6px; text-align:right;">Gross</th>
                <th style="padding:6px; text-align:right;">Returns</th>
                <th style="padding:6px; text-align:right;">NET Sale</th>
                {admin_headers}
                <th style="padding:6px; text-align:right;">Pay Split (C/B/U)</th>
                {admin_headers_end}
              </tr>
            </thead>
            <tbody>
              {rows_html or '<tr><td colspan="12" style="text-align:center; padding:16px; color:#888;">No sales in selected period</td></tr>'}
            </tbody>
            <tfoot>
              <tr style="background:#f8fafc; border-top:2px solid #0f172a; font-weight:bold;">
                <th style="padding:6px; text-align:left;">TOTALS</th>
                <th style="text-align:center;">{tot['invoices_count']}</th>
                <th style="text-align:center;">{tot['phones_sold']}</th>
                <th style="text-align:center;">{tot['acc_sold']}</th>
                <th style="text-align:right;">Rs. {tot['gross_sale']:,.0f}</th>
                <th style="text-align:right; color:#dc2626;">-Rs. {tot['returns']:,.0f}</th>
                <th style="text-align:right;">Rs. {tot['net_sale']:,.0f}</th>
                {tot_cost_th}
                {tot_prof_th}
                <th style="text-align:right; font-size:10px;">C:{tot['cash_paid']:,.0f} | B:{tot['online_paid']+tot['card_paid']:,.0f} | U:{tot['udhaar_amount']:,.0f}</th>
                {tot_exp_th}
                {tot_net_day_th}
              </tr>
            </tfoot>
          </table>
        </div>
        """

    body = f"""
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; border-bottom:2px solid #0f172a; padding-bottom:8px;">
      <div>
        <h1 style="font-size:20px; font-weight:800; margin:0; color:#0f172a;">{shop['name']}</h1>
        <p style="font-size:11.5px; margin:2px 0; color:#475569;">{shop['tagline']}</p>
        <p style="font-size:11px; margin:0; color:#64748b;">📍 {shop['address']} &bull; 📞 {shop['phone']}</p>
      </div>
      <div style="text-align:right;">
        <span style="background:#0f172a; color:#fff; padding:4px 10px; border-radius:4px; font-size:11.5px; font-weight:800;">{period_title}</span>
        <div style="font-size:11px; font-weight:bold; color:#334155; margin:3px 0 1px;">DATE-WISE DAILY SALES & REVENUE REPORT</div>
        <p style="font-size:12px; font-weight:bold; margin:2px 0 0; color:#0f172a;">{date_display}</p>
        <p style="font-size:10px; color:#64748b; margin:0;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} | Admin View</p>
      </div>
    </div>

    <!-- KPI Summary Row -->
    <div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; margin-bottom:14px; font-size:11px;">
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px; text-align:center;">
        <span style="color:#64748b; font-size:10px; font-weight:bold;">TOTAL INVOICES</span>
        <div style="font-size:16px; font-weight:bold; color:#0284c7; margin-top:2px;">{tot['invoices_count']}</div>
        <div style="font-size:9.5px; color:#64748b; margin-top:1px;">{tot['phones_sold']} Phones &bull; {tot['acc_sold']} Acc</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px; text-align:center;">
        <span style="color:#64748b; font-size:10px; font-weight:bold;">NET SALES VOLUME</span>
        <div style="font-size:16px; font-weight:bold; color:#15803d; margin-top:2px;">Rs. {tot['net_sale']:,.0f}</div>
        <div style="font-size:9.5px; color:#64748b; margin-top:1px;">Gross: Rs. {tot['gross_sale']:,.0f}</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px; text-align:center;">
        <span style="color:#64748b; font-size:10px; font-weight:bold;">QUICK SERVICES (EP/JC)</span>
        <div style="font-size:16px; font-weight:bold; color:#d97706; margin-top:2px;">Rs. {det_tot.get('qs_total_vol', 0):,.0f}</div>
        <div style="font-size:9.5px; color:#16a34a; font-weight:bold; margin-top:1px;">+Rs. {det_tot.get('qs_profit', 0):,.0f} Commission</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px; text-align:center;">
        <span style="color:#64748b; font-size:10px; font-weight:bold;">{('GROSS EARNINGS' if is_admin else 'CASH RECEIVED')}</span>
        <div style="font-size:16px; font-weight:bold; color:#059669; margin-top:2px;">Rs. {(det_tot.get('total_gross_income', tot.get('profit', tot['cash_paid']))):,.0f}</div>
        <div style="font-size:9.5px; color:#64748b; margin-top:1px;">Sales + QS + Repairs</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px; text-align:center;">
        <span style="color:#64748b; font-size:10px; font-weight:bold;">{('NET PROFIT / BALANCE' if is_admin else 'DRAWER CASH')}</span>
        <div style="font-size:16px; font-weight:bold; color:{'#15803d' if det_tot.get('net_of_period', 0) >= 0 else '#dc2626'}; margin-top:2px;">Rs. {(det_tot.get('net_of_period', tot.get('profit', tot['cash_paid']))):,.0f}</div>
        <div style="font-size:9.5px; color:{'#15803d' if det_tot.get('net_of_period', 0) >= 0 else '#dc2626'}; font-weight:bold; margin-top:1px;">{('Net Profit' if det_tot.get('net_of_period', 0) >= 0 else 'Operating Deficit (Exp > Prof)') if is_admin else 'Inflow'}</div>
      </div>
    </div>

    {drawer_reconcile_box}

    {multiday_table_html}

    <!-- SECTION 1: DETAILED INVOICES & PRODUCTS SOLD -->
    <div style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin:0;">
          🧾 ITEMIZED INVOICES & PRODUCTS SOLD ({tot['invoices_count']} Invoices &bull; Net: Rs. {tot['net_sale']:,.0f})
        </h3>
        <span style="font-size:10px; color:#64748b;">Includes customer details, IMEIs & line items</span>
      </div>
      {sales_items_html}
    </div>

    <!-- SECTION 2: PRODUCTS SOLD SUMMARY -->
    <div style="margin-bottom:16px; page-break-inside:avoid;">
      <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        📦 PRODUCTS SOLD BREAKDOWN ({len(products_sold)} Unique Products)
      </h3>
      <table style="width:100%; border-collapse:collapse; font-size:10.5px; margin-bottom:8px;">
        <thead>
          <tr style="background:#334155; color:#fff;">
            <th style="padding:4px 6px; text-align:center; width:35px;">#</th>
            <th style="padding:4px 6px; text-align:left;">Product & Specifications</th>
            <th style="padding:4px 6px; text-align:center; width:70px;">Type</th>
            <th style="padding:4px 6px; text-align:center; width:60px;">Qty Sold</th>
            <th style="padding:4px 6px; text-align:right; width:110px;">Total Revenue</th>
            {('<th style="padding:4px 6px; text-align:right; width:90px;">Profit</th>' if is_admin else '')}
          </tr>
        </thead>
        <tbody>
          {prod_summary_html}
        </tbody>
      </table>
    </div>

    <!-- SECTION 3: ITEMIZED EXPENSES -->
    <div style="margin-bottom:16px; page-break-inside:avoid;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin:0;">
          💸 ITEMIZED SHOP EXPENSES ({len(expenses_list)} Expenses &bull; Total: Rs. {det_tot.get('expenses_total', 0):,.0f})
        </h3>
        <span style="font-size:10px; font-weight:bold; color:#475569;">
          Cash Drawer: <span style="color:#15803d;">Rs. {det_tot.get('cash_expenses_total', 0):,.0f}</span> | 
          Bank/Online: <span style="color:#3730a3;">Rs. {det_tot.get('non_cash_expenses_total', 0):,.0f}</span>
        </span>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:10.5px; margin-bottom:8px;">
        <thead>
          <tr style="background:#475569; color:#fff;">
            <th style="padding:4px 6px; text-align:center; width:35px;">#</th>
            <th style="padding:4px 6px; text-align:left; width:85px;">Date</th>
            <th style="padding:4px 6px; text-align:left;">Description / Title (Reason)</th>
            <th style="padding:4px 6px; text-align:left; width:110px;">Category</th>
            <th style="padding:4px 6px; text-align:left; width:110px;">Payment Method</th>
            <th style="padding:4px 6px; text-align:left; width:80px;">Logged By</th>
            <th style="padding:4px 6px; text-align:right; width:90px;">Amount</th>
          </tr>
        </thead>
        <tbody>
          {exp_details_html}
        </tbody>
        <tfoot>
          <tr style="background:#f1f5f9; border-top:2px solid #475569; font-weight:bold; font-size:11px;">
            <td colspan="6" style="padding:5px 6px; text-align:right;">TOTAL EXPENSES:</td>
            <td style="padding:5px 6px; text-align:right; color:#dc2626;">Rs. {det_tot.get('expenses_total', 0):,.0f}</td>
          </tr>
        </tfoot>
      </table>
    </div>

    <!-- SECTION 4: UDHAAR & CREDIT RECOVERIES -->
    <div style="margin-bottom:16px; page-break-inside:avoid;">
      <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        💵 UDHAAR / CREDIT RECOVERIES RECEIVED (Total Collected: Rs. {det_tot.get('udhaar_recovered', 0):,.0f})
      </h3>
      <table style="width:100%; border-collapse:collapse; font-size:10.5px; margin-bottom:8px;">
        <thead>
          <tr style="background:#64748b; color:#fff;">
            <th style="padding:4px 6px; text-align:center; width:35px;">#</th>
            <th style="padding:4px 6px; text-align:left; width:85px;">Date</th>
            <th style="padding:4px 6px; text-align:left; width:95px;">Voucher #</th>
            <th style="padding:4px 6px; text-align:left;">Customer Name & Phone</th>
            <th style="padding:4px 6px; text-align:left; width:120px;">Payment Method</th>
            <th style="padding:4px 6px; text-align:right; width:100px;">Collected (Rs.)</th>
          </tr>
        </thead>
        <tbody>
          {udhaar_rows_html}
        </tbody>
      </table>
    </div>

    <!-- SECTION 5: QUICK SERVICES & DIGITAL WALLETS (EasyPaisa, JazzCash, Load, Bills) -->
    <div style="margin-bottom:16px; page-break-inside:avoid;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        <h3 style="font-size:13px; font-weight:800; color:#0f172a; margin:0;">
          📲 QUICK SERVICES &amp; DIGITAL WALLETS ({det_tot.get('qs_count', 0)} Transactions &bull; Volume: Rs. {det_tot.get('qs_total_vol', 0):,.0f})
        </h3>
        <span style="font-size:10.5px; font-weight:bold;">
          Commission / Profit: <span style="color:#16a34a; font-size:12px;">+Rs. {det_tot.get('qs_profit', 0):,.0f}</span>
        </span>
      </div>
      <div style="display:flex; gap:12px; margin-bottom:6px; font-size:10px; background:#f8fafc; padding:4px 8px; border-radius:4px; border:1px solid #e2e8f0; flex-wrap:wrap;">
        <span>📤 <strong>Sent Volume:</strong> Rs. {det_tot.get('qs_send_vol', 0):,.0f}</span>
        <span>📥 <strong>Received Volume:</strong> Rs. {det_tot.get('qs_recv_vol', 0):,.0f}</span>
        <span>💵 <strong>Drawer Cash Inflow:</strong> +Rs. {det_tot.get('qs_cash_inflow', 0):,.0f}</span>
        <span>💸 <strong>Drawer Cash Outflow:</strong> -Rs. {det_tot.get('qs_cash_outflow', 0):,.0f}</span>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:10px; margin-bottom:8px;">
        <thead>
          <tr style="background:#0284c7; color:#fff;">
            <th style="padding:4px 6px; text-align:center; width:30px;">#</th>
            <th style="padding:4px 6px; text-align:left; width:100px;">Date &amp; Time</th>
            <th style="padding:4px 6px; text-align:left; width:110px;">Service</th>
            <th style="padding:4px 6px; text-align:left; width:130px;">Operation</th>
            <th style="padding:4px 6px; text-align:left; width:100px;">Phone / Account</th>
            <th style="padding:4px 6px; text-align:right; width:90px;">Volume (Rs.)</th>
            {('<th style="padding:4px 6px; text-align:right; width:80px;">Commission</th>' if is_admin else '')}
            <th style="padding:4px 6px; text-align:right; width:95px;">Drawer Flow</th>
            <th style="padding:4px 6px; text-align:left;">Notes / TID</th>
          </tr>
        </thead>
        <tbody>
          {qs_rows_html}
        </tbody>
        <tfoot>
          <tr style="background:#f1f5f9; border-top:2px solid #0284c7; font-weight:bold; font-size:10.5px;">
            <td colspan="5" style="padding:5px 6px; text-align:right;">TOTALS:</td>
            <td style="padding:5px 6px; text-align:right;">Rs. {det_tot.get('qs_total_vol', 0):,.0f}</td>
            {('<td style="padding:5px 6px; text-align:right; color:#16a34a;">+Rs. ' + f"{det_tot.get('qs_profit', 0):,.0f}" + '</td>') if is_admin else ''}
            <td style="padding:5px 6px; text-align:right; color:#0f172a;">Rs. {det_tot.get('qs_cash_inflow', 0) - det_tot.get('qs_cash_outflow', 0):+,.0f}</td>
            <td></td>
          </tr>
        </tfoot>
      </table>
    </div>

    <table style="width:100%; margin-top:28px; page-break-inside:avoid;">
      <tr>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Prepared By (Cashier)</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Verified By (Shop Owner)</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:16px; font-size:10px; text-align:center; color:#94a3b8;">Developed by Ahmed &bull; Mobile Shop ERP</p>
    """
    return print_wrapper_html(f"Daily-Sales-{start_date}-to-{end_date}", body, width_mm="A4", auto_print=True)

def render_monthly_closing_report(month_str, is_admin=True):
    """Renders printable A4 Monthly Cash Closing & Reconciliation Audit Report."""
    import accounting
    shop = get_shop_info()
    data = accounting.get_month_day_closings(month_str)
    m = data["month"]
    days = data["days"]
    tot = data["totals"]

    var_color = "#16a34a" if tot["cash_difference"] >= 0 else "#dc2626"
    var_sign = "+" if tot["cash_difference"] > 0 else ""

    # Monthly Quick Services query
    qs_month_rows = db.query_all("""
        SELECT 
            COUNT(*) AS count,
            COALESCE(SUM(amount), 0) AS total_vol,
            COALESCE(SUM(profit), 0) AS total_comm,
            COALESCE(SUM(CASE WHEN (action_type = 'RECEIVE' OR UPPER(service_type) LIKE '%CASH%OUT%') THEN amount ELSE 0 END), 0) AS recv_vol,
            COALESCE(SUM(CASE WHEN NOT (action_type = 'RECEIVE' OR UPPER(service_type) LIKE '%CASH%OUT%') THEN amount ELSE 0 END), 0) AS send_vol
        FROM quick_services
        WHERE substr(timestamp, 1, 7) = ? AND (is_void IS NULL OR is_void = 0)
    """, (m,))
    qs_m = dict(qs_month_rows[0]) if qs_month_rows else {"count": 0, "total_vol": 0, "total_comm": 0, "recv_vol": 0, "send_vol": 0}

    rows_html = ""
    for d in days:
        st_badge = '<span style="color:#16a34a; font-weight:bold;">CLOSED</span>' if d["is_closed"] else '<span style="color:#f59e0b; font-weight:bold;">OPEN</span>'
        diff_str = f"{d['difference']:+,.0f}" if d["is_closed"] else "-"
        diff_style = "color:#16a34a; font-weight:bold;" if d["difference"] >= 0 else "color:#dc2626; font-weight:bold;"
        act_str = f"Rs. {d['actual_cash']:,.0f}" if d["is_closed"] else "-"
        
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11px;">
          <td style="padding:4px 6px; font-weight:bold;">{d['date']}</td>
          <td style="padding:4px 6px; text-align:center;">{st_badge}</td>
          <td style="padding:4px 6px; text-align:right;">Rs. {d['opening_cash']:,.0f}</td>
          <td style="padding:4px 6px; text-align:right; color:#16a34a;">+Rs. {d['inflow']:,.0f}</td>
          <td style="padding:4px 6px; text-align:right; color:#dc2626;">-Rs. {d['outflow']:,.0f}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold;">Rs. {d['expected_cash']:,.0f}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold;">{act_str}</td>
          <td style="padding:4px 6px; text-align:right; {diff_style}">{diff_str}</td>
          <td style="padding:4px 6px; font-size:10px; color:#64748b;">{d['closed_by'] or '-'}</td>
          <td style="padding:4px 6px; font-size:10px; color:#64748b;">{d['notes'] or '-'}</td>
        </tr>
        """

    # Monthly Expenses Table
    month_exp_list = data.get("expenses", [])
    tot_exp_amt = sum(float(x.get("amount") or 0) for x in month_exp_list)
    tot_cash_exp = data.get("total_cash_expenses", 0.0)
    tot_non_cash_exp = data.get("total_non_cash_expenses", 0.0)

    cat_chips = ""
    for cat in data.get("expenses_by_category", []):
        cat_chips += f"""
        <div style="background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px; padding:3px 6px; font-size:9.5px;">
          <span style="color:#64748b;">{cat['category']}:</span> 
          <strong style="color:#0f172a;">Rs. {cat['total']:,.0f}</strong>
        </div>
        """

    exp_rows = ""
    for idx, ex in enumerate(month_exp_list, 1):
        acc = "Cash Drawer" if ex.get("is_cash") else (ex.get("payment_method") or "Bank/Online")
        acc_col = "#15803d" if ex.get("is_cash") else "#3730a3"
        exp_rows += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:10px;">
          <td style="padding:3px 5px; text-align:center; color:#64748b;">{idx}</td>
          <td style="padding:3px 5px; font-weight:bold;">{ex.get('eff_date', '')}</td>
          <td style="padding:3px 5px;"><strong>{ex.get('description') or ex.get('category')}</strong></td>
          <td style="padding:3px 5px;"><span style="background:#f1f5f9; padding:1px 4px; border-radius:2px;">{ex.get('category')}</span></td>
          <td style="padding:3px 5px; color:{acc_col}; font-weight:bold;">{acc}</td>
          <td style="padding:3px 5px; color:#64748b;">{ex.get('user_name') or 'Admin'}</td>
          <td style="padding:3px 5px; text-align:right; font-weight:bold; color:#dc2626;">Rs. {float(ex.get('amount') or 0):,.0f}</td>
        </tr>
        """
    if not exp_rows:
        exp_rows = '<tr><td colspan="7" style="text-align:center; padding:10px; color:#64748b;">No expenses recorded in this month</td></tr>'

    body = f"""
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; border-bottom:2px solid #0f172a; padding-bottom:8px;">
      <div>
        <h1 style="font-size:20px; font-weight:800; margin:0; color:#0f172a;">{shop['name']}</h1>
        <p style="font-size:12px; margin:2px 0; color:#475569;">{shop['tagline']}</p>
        <p style="font-size:11px; margin:0; color:#64748b;">📍 {shop['address']} &bull; 📞 {shop['phone']}</p>
      </div>
      <div style="text-align:right;">
        <span style="background:#0f172a; color:#fff; padding:4px 10px; border-radius:4px; font-size:12px; font-weight:800;">MONTHLY CLOSING REPORT</span>
        <p style="font-size:13px; font-weight:bold; margin:4px 0 0; color:#0f172a;">Month: {m}</p>
        <p style="font-size:10px; color:#64748b; margin:0;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
      </div>
    </div>

    <!-- KPI Summary Grid -->
    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:8px; margin-bottom:14px;">
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px;">
        <div style="font-size:10px; color:#64748b; font-weight:bold;">CLOSED / TOTAL DAYS</div>
        <div style="font-size:16px; font-weight:800; color:#0f172a; margin-top:2px;">{tot['closed_count']} / {tot['days_count']} Days</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px;">
        <div style="font-size:10px; color:#64748b; font-weight:bold;">TOTAL CASH INFLOW</div>
        <div style="font-size:16px; font-weight:800; color:#16a34a; margin-top:2px;">+Rs. {tot['total_cash_in']:,.0f}</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px;">
        <div style="font-size:10px; color:#64748b; font-weight:bold;">TOTAL CASH OUTFLOW</div>
        <div style="font-size:16px; font-weight:800; color:#dc2626; margin-top:2px;">-Rs. {tot['total_cash_out']:,.0f}</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px;">
        <div style="font-size:10px; color:#64748b; font-weight:bold;">NET CASH VARIANCE</div>
        <div style="font-size:16px; font-weight:800; color:{var_color}; margin-top:2px;">{var_sign}Rs. {tot['cash_difference']:,.0f}</div>
      </div>
    </div>

    <!-- Detailed Audit Table -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:16px;">
      <thead>
        <tr style="background:#0f172a; color:#fff; font-size:11px;">
          <th style="padding:6px; text-align:left;">Date</th>
          <th style="padding:6px; text-align:center;">Status</th>
          <th style="padding:6px; text-align:right;">Opening</th>
          <th style="padding:6px; text-align:right;">Inflow</th>
          <th style="padding:6px; text-align:right;">Outflow</th>
          <th style="padding:6px; text-align:right;">Expected</th>
          <th style="padding:6px; text-align:right;">Counted</th>
          <th style="padding:6px; text-align:right;">Diff</th>
          <th style="padding:6px; text-align:left;">Closed By</th>
          <th style="padding:6px; text-align:left;">Notes</th>
        </tr>
      </thead>
      <tbody>
        {rows_html or '<tr><td colspan="10" style="text-align:center; padding:16px; color:#888;">No closing records in this month</td></tr>'}
      </tbody>
      <tfoot>
        <tr style="background:#f1f5f9; border-top:2px solid #0f172a; font-weight:bold; font-size:11.5px;">
          <td style="padding:6px;">TOTALS</td>
          <td style="padding:6px; text-align:center;">{tot['closed_count']} Closed</td>
          <td style="padding:6px; text-align:right;">-</td>
          <td style="padding:6px; text-align:right; color:#16a34a;">+Rs. {tot['total_cash_in']:,.0f}</td>
          <td style="padding:6px; text-align:right; color:#dc2626;">-Rs. {tot['total_cash_out']:,.0f}</td>
          <td style="padding:6px; text-align:right;">Rs. {tot['expected_cash']:,.0f}</td>
          <td style="padding:6px; text-align:right;">Rs. {tot['actual_cash']:,.0f}</td>
          <td style="padding:6px; text-align:right; color:{var_color};">{var_sign}Rs. {tot['cash_difference']:,.0f}</td>
          <td colspan="2"></td>
        </tr>
      </tfoot>
    </table>

    <!-- Monthly Expenses Audit Section -->
    <div style="margin-top:16px; page-break-inside:avoid;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        <h3 style="font-size:12.5px; font-weight:800; color:#0f172a; margin:0;">
          💸 MONTHLY EXPENSES AUDIT & DETAILS ({len(month_exp_list)} Expenses &bull; Total: Rs. {tot_exp_amt:,.0f})
        </h3>
        <span style="font-size:10px; font-weight:bold;">
          Drawer Cash: <span style="color:#15803d;">Rs. {tot_cash_exp:,.0f}</span> | 
          Bank/Online: <span style="color:#3730a3;">Rs. {tot_non_cash_exp:,.0f}</span>
        </span>
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px;">
        {cat_chips}
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:10px; margin-bottom:10px;">
        <thead>
          <tr style="background:#475569; color:#fff;">
            <th style="padding:3px 5px; text-align:center; width:30px;">#</th>
            <th style="padding:3px 5px; text-align:left; width:75px;">Date</th>
            <th style="padding:3px 5px; text-align:left;">Description / Reason</th>
            <th style="padding:3px 5px; text-align:left; width:95px;">Category</th>
            <th style="padding:3px 5px; text-align:left; width:95px;">Account</th>
            <th style="padding:3px 5px; text-align:left; width:75px;">Logged By</th>
            <th style="padding:3px 5px; text-align:right; width:85px;">Amount</th>
          </tr>
        </thead>
        <tbody>
          {exp_rows}
        </tbody>
      </table>
    </div>

    <!-- Monthly Quick Services Summary -->
    <div style="margin-top:16px; page-break-inside:avoid;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; border-bottom:1px solid #cbd5e1; padding-bottom:4px;">
        <h3 style="font-size:12.5px; font-weight:800; color:#0f172a; margin:0;">
          📲 MONTHLY QUICK SERVICES (EasyPaisa / JazzCash / Loads / Bills)
        </h3>
        <span style="font-size:11px; font-weight:bold; color:#16a34a;">
          Total Commission / Profit: Rs. {float(qs_m.get('total_comm') or 0):,.0f}
        </span>
      </div>
      <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; font-size:11px; background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:8px 12px; text-align:center;">
        <div><span style="color:#64748b;">Operations:</span><div style="font-weight:bold; font-size:14px; margin-top:2px;">{qs_m.get('count', 0)} Trans</div></div>
        <div><span style="color:#64748b;">Total Volume Handled:</span><div style="font-weight:bold; font-size:14px; color:#0284c7; margin-top:2px;">Rs. {float(qs_m.get('total_vol') or 0):,.0f}</div></div>
        <div><span style="color:#64748b;">Sent (Cash-In) Volume:</span><div style="font-weight:bold; font-size:14px; color:#15803d; margin-top:2px;">Rs. {float(qs_m.get('send_vol') or 0):,.0f}</div></div>
        <div><span style="color:#64748b;">Received (Cash-Out):</span><div style="font-weight:bold; font-size:14px; color:#dc2626; margin-top:2px;">Rs. {float(qs_m.get('recv_vol') or 0):,.0f}</div></div>
      </div>
    </div>

    <table style="width:100%; margin-top:24px;">
      <tr>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Prepared By (Cashier)</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Verified By (Shop Owner)</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:14px; font-size:10px; text-align:center; color:#94a3b8;">Developed by Ahmed &bull; Mobile Shop ERP</p>
    """
    return print_wrapper_html(f"Monthly-Closing-Report-{m}", body, width_mm="A4", auto_print=True)

def render_monthly_expenses_report(start_date, end_date, category=None):
    """Renders printable A4 Shop Expenses Report with category breakdown and audit table."""
    import accounting
    shop = get_shop_info()
    items = accounting.list_expenses(category=category or "", start_date=start_date, end_date=end_date, limit=5000)

    total_amt = sum(float(x.get("amount") or 0) for x in items)
    cash_amt = sum(float(x.get("amount") or 0) for x in items if x.get("is_cash"))
    non_cash_amt = total_amt - cash_amt

    cat_map = {}
    for ex in items:
        c = ex.get("category") or "Miscellaneous"
        cat_map[c] = cat_map.get(c, 0.0) + float(ex.get("amount") or 0)
    sorted_cats = sorted(cat_map.items(), key=lambda x: x[1], reverse=True)

    cat_summary_html = "".join(
        f'<div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:4px; padding:6px 8px; font-size:11px;">'
        f'<span style="color:#64748b; font-weight:bold;">{c[0]}:</span> <strong style="color:#0f172a;">Rs. {c[1]:,.0f}</strong>'
        f'</div>'
        for c in sorted_cats
    )

    rows_html = ""
    for ex in items:
        dt = ex.get("expense_date") or ex.get("transaction_date") or (ex.get("created_at") or "")[:10]
        acc_tag = '<span style="color:#0284c7; font-weight:bold;">Drawer Cash</span>' if ex.get("is_cash") else f'<span style="color:#10b981;">{ex.get("payment_method")}</span>'
        rows_html += f"""
        <tr style="border-bottom:1px solid #e2e8f0; font-size:11.5px;">
          <td style="padding:4px 6px;">{dt}</td>
          <td style="padding:4px 6px; font-weight:bold;">{ex.get('category')}</td>
          <td style="padding:4px 6px; color:#334155;">{ex.get('description') or '-'}</td>
          <td style="padding:4px 6px; text-align:right; font-weight:bold; color:#dc2626;">Rs. {float(ex.get('amount') or 0):,.0f}</td>
          <td style="padding:4px 6px;">{acc_tag}</td>
          <td style="padding:4px 6px; font-size:10.5px; color:#64748b;">{ex.get('reference') or '-'}</td>
        </tr>
        """

    cat_filter_note = f" (Category: {category})" if category else ""
    body = f"""
    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px; border-bottom:2px solid #0f172a; padding-bottom:8px;">
      <div>
        <h1 style="font-size:20px; font-weight:800; margin:0; color:#0f172a;">{shop['name']}</h1>
        <p style="font-size:12px; margin:2px 0; color:#475569;">{shop['tagline']}</p>
        <p style="font-size:11px; margin:0; color:#64748b;">📍 {shop['address']} &bull; 📞 {shop['phone']}</p>
      </div>
      <div style="text-align:right;">
        <span style="background:#dc2626; color:#fff; padding:4px 10px; border-radius:4px; font-size:12px; font-weight:800;">EXPENSES REPORT</span>
        <p style="font-size:12px; font-weight:bold; margin:4px 0 0; color:#0f172a;">{start_date} to {end_date}{cat_filter_note}</p>
        <p style="font-size:10px; color:#64748b; margin:0;">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
      </div>
    </div>

    <!-- Summary Box -->
    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; margin-bottom:14px;">
      <div style="background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:10px;">
        <div style="font-size:10.5px; color:#991b1b; font-weight:bold;">TOTAL EXPENSES</div>
        <div style="font-size:18px; font-weight:800; color:#dc2626; margin-top:2px;">Rs. {total_amt:,.0f}</div>
        <div style="font-size:10px; color:#64748b; margin-top:2px;">{len(items)} Entries Recorded</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:10px;">
        <div style="font-size:10.5px; color:#475569; font-weight:bold;">PAID FROM CASH DRAWER</div>
        <div style="font-size:18px; font-weight:800; color:#0284c7; margin-top:2px;">Rs. {cash_amt:,.0f}</div>
        <div style="font-size:10px; color:#64748b; margin-top:2px;">Deducted from drawer cash</div>
      </div>
      <div style="background:#f8fafc; border:1px solid #cbd5e1; border-radius:6px; padding:10px;">
        <div style="font-size:10.5px; color:#475569; font-weight:bold;">PAID VIA BANK / WALLET</div>
        <div style="font-size:18px; font-weight:800; color:#10b981; margin-top:2px;">Rs. {non_cash_amt:,.0f}</div>
        <div style="font-size:10px; color:#64748b; margin-top:2px;">Online / Bank account</div>
      </div>
    </div>

    <!-- Category Breakdown Grid -->
    <div style="margin-bottom:14px;">
      <div style="font-size:11px; font-weight:bold; color:#475569; margin-bottom:6px; text-transform:uppercase;">Category Breakdown</div>
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:6px;">
        {cat_summary_html or '<div style="color:#888; font-size:11px;">No expense categories</div>'}
      </div>
    </div>

    <!-- Detailed Expenses Table -->
    <table style="width:100%; border-collapse:collapse; margin-bottom:16px;">
      <thead>
        <tr style="background:#0f172a; color:#fff; font-size:11px;">
          <th style="padding:6px; text-align:left;">Date</th>
          <th style="padding:6px; text-align:left;">Category</th>
          <th style="padding:6px; text-align:left;">Description / Payee</th>
          <th style="padding:6px; text-align:right;">Amount (Rs.)</th>
          <th style="padding:6px; text-align:left;">Paid From</th>
          <th style="padding:6px; text-align:left;">Reference</th>
        </tr>
      </thead>
      <tbody>
        {rows_html or '<tr><td colspan="6" style="text-align:center; padding:16px; color:#888;">No expenses found for this period</td></tr>'}
      </tbody>
      <tfoot>
        <tr style="background:#f1f5f9; border-top:2px solid #0f172a; font-weight:bold; font-size:12px;">
          <td colspan="3" style="padding:6px; text-align:left;">TOTAL EXPENSES</td>
          <td style="padding:6px; text-align:right; color:#dc2626;">Rs. {total_amt:,.0f}</td>
          <td colspan="2"></td>
        </tr>
      </tfoot>
    </table>

    <table style="width:100%; margin-top:24px;">
      <tr>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Prepared By</td>
        <td style="width:40%;"></td>
        <td style="border-top:1px solid #334155; text-align:center; width:30%; padding-top:6px; font-size:11px;">Approved By (Admin)</td>
      </tr>
    </table>
    <p class="text-center bold" style="margin-top:14px; font-size:10px; text-align:center; color:#94a3b8;">Developed by Ahmed &bull; Mobile Shop ERP</p>
    """
    return print_wrapper_html(f"Expenses-Report-{start_date}-to-{end_date}", body, width_mm="A4", auto_print=True)





