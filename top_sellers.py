# MOBILE & ACCESSORIES ERP — Category-Wise Top Sellers & Velocity Intelligence
from datetime import datetime, timedelta
import db, alert_engine

def resolve_period_range(period="this_month", custom_start=None, custom_end=None):
    """Returns (start_date, end_date) strings YYYY-MM-DD."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    if period == "today":
        return today_str, today_str
    elif period == "yesterday":
        yest = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return yest, yest
    elif period == "7days":
        start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        return start, today_str
    elif period == "30days":
        start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        return start, today_str
    elif period == "last_month":
        # First day of this month minus 1 day gives last day of previous month
        first_this = now.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev.strftime("%Y-%m-%d"), last_prev.strftime("%Y-%m-%d")
    elif period == "custom" and custom_start and custom_end:
        return str(custom_start)[:10], str(custom_end)[:10]
    else: # default "this_month"
        first_this = now.strftime("%Y-%m-01")
        return first_this, today_str

def get_top_sellers_report(period="this_month", category=None, brand=None, sort_by="units", limit=50, is_admin=True, custom_start=None, custom_end=None):
    """
    Retrieves category-wise and brand-filtered top selling items from sales_daily_by_variant.
    Supports sort_by in ('units', 'revenue', 'profit').
    If is_admin is False, cost, profit, and revenue fields are redacted for employee security.
    """
    start_date, end_date = resolve_period_range(period, custom_start, custom_end)

    sql = """
        SELECT 
            s.variant_id,
            s.product_id,
            p.name AS model_name,
            p.brand,
            p.category,
            p.item_type,
            v.ram,
            v.storage,
            v.color,
            v.sku,
            v.barcode,
            v.retail_price,
            v.wholesale_price,
            v.low_stock_level,
            v.reorder_qty,
            COALESCE(ast.state, 'OK') AS alert_state,
            COALESCE(ast.current_stock, 0) AS current_stock,
            COALESCE(ast.on_order_qty, 0) AS on_order_qty,
            SUM(s.units_sold) AS gross_units_sold,
            SUM(s.units_returned) AS units_returned,
            SUM(s.units_sold - s.units_returned) AS net_units_sold,
            SUM(s.gross_revenue) AS gross_revenue,
            SUM(s.cost_total) AS cost_total,
            SUM(s.net_profit) AS net_profit
        FROM sales_daily_by_variant s
        JOIN variants v ON s.variant_id = v.id
        JOIN products p ON s.product_id = p.id
        LEFT JOIN stock_alert_state ast ON v.id = ast.variant_id
        WHERE s.date >= ? AND s.date <= ?
    """
    params = [start_date, end_date]

    if category and category.strip() and category.strip().lower() != "all":
        sql += " AND s.category = ?"
        params.append(category.strip())

    if brand and brand.strip() and brand.strip().lower() != "all":
        sql += " AND s.brand = ?"
        params.append(brand.strip())

    sql += " GROUP BY s.variant_id"

    # Sorting
    if sort_by == "revenue" and is_admin:
        sql += " ORDER BY gross_revenue DESC, net_units_sold DESC"
    elif sort_by == "profit" and is_admin:
        sql += " ORDER BY net_profit DESC, net_units_sold DESC"
    else: # default "units"
        sql += " ORDER BY net_units_sold DESC, gross_revenue DESC"

    sql += " LIMIT ?"
    params.append(int(limit))

    rows = db.query_all(sql, params)

    # Calculate overall totals for category/brand summary
    total_net_units = 0
    total_revenue = 0.0
    total_profit = 0.0

    items = []
    for r in rows:
        net_units = int(r["net_units_sold"] or 0)
        rev = float(r["gross_revenue"] or 0)
        prof = float(r["net_profit"] or 0)
        total_net_units += net_units
        total_revenue += rev
        total_profit += prof

        specs = f"{r['ram']} {r['storage']} {r['color']}".strip()
        margin_pct = round((prof / rev * 100.0), 1) if (rev > 0) else 0.0

        # Suggested reorder qty intelligence
        reorder_info = alert_engine.get_reorder_intelligence(r["variant_id"]) if is_admin else None

        item_dict = {
            "variant_id": r["variant_id"],
            "product_id": r["product_id"],
            "model_name": r["model_name"],
            "brand": r["brand"],
            "category": r["category"],
            "item_type": r["item_type"],
            "specs": specs,
            "sku": r["sku"] or "",
            "barcode": r["barcode"] or "",
            "retail_price": r["retail_price"],
            "current_stock": r["current_stock"],
            "on_order_qty": r["on_order_qty"],
            "alert_state": r["alert_state"],
            "net_units_sold": net_units,
            "units_returned": int(r["units_returned"] or 0),
            "reorder_suggestion": reorder_info["suggested_reorder_qty"] if reorder_info else (r["reorder_qty"] or 10),
            "days_left": reorder_info["days_stock_left"] if reorder_info else None
        }

        if is_admin:
            item_dict["gross_revenue"] = rev
            item_dict["cost_total"] = float(r["cost_total"] or 0)
            item_dict["net_profit"] = prof
            item_dict["margin_percent"] = margin_pct
            item_dict["last_supplier_name"] = reorder_info["last_supplier_name"] if reorder_info else ""
            item_dict["last_cost"] = reorder_info["last_cost"] if reorder_info else 0

        items.append(item_dict)

    # Categories list for filter chips
    cats_query = db.query_all("SELECT DISTINCT category FROM sales_daily_by_variant WHERE date >= ? AND date <= ? ORDER BY category ASC", (start_date, end_date))
    available_categories = [c["category"] for c in cats_query if c["category"]]

    # Brands list for filter chips
    brands_query = db.query_all("SELECT DISTINCT brand FROM sales_daily_by_variant WHERE date >= ? AND date <= ? ORDER BY brand ASC", (start_date, end_date))
    available_brands = [b["brand"] for b in brands_query if b["brand"]]

    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "category": category or "All",
        "brand": brand or "All",
        "sort_by": sort_by,
        "items": items,
        "total_count": len(items),
        "total_net_units": total_net_units,
        "total_revenue": total_revenue if is_admin else None,
        "total_profit": total_profit if is_admin else None,
        "overall_margin_percent": round((total_profit / total_revenue * 100.0), 1) if (total_revenue > 0 and is_admin) else 0.0,
        "available_categories": available_categories,
        "available_brands": available_brands
    }

def get_pos_quick_top_sellers(category=None, limit=20):
    """
    Lightweight query tailored for POS quick-add tabs:
    Returns top sellers with current in-stock status and units sold.
    Strictly employee-safe (no costs, no profits).
    Fast index lookup < 3ms.
    """
    now = datetime.now()
    start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    today_str = now.strftime("%Y-%m-%d")

    sql = """
        SELECT 
            s.variant_id,
            s.product_id,
            p.name AS model_name,
            p.brand,
            p.category,
            p.item_type,
            v.ram,
            v.storage,
            v.color,
            v.barcode,
            v.retail_price,
            COALESCE(ast.state, 'OK') AS alert_state,
            COALESCE(ast.current_stock, 0) AS current_stock,
            SUM(s.units_sold - s.units_returned) AS net_units_sold
        FROM sales_daily_by_variant s
        JOIN variants v ON s.variant_id = v.id
        JOIN products p ON s.product_id = p.id
        LEFT JOIN stock_alert_state ast ON v.id = ast.variant_id
        WHERE s.date >= ? AND s.date <= ? AND v.is_archived = 0 AND p.is_archived = 0
    """
    params = [start_date, today_str]

    if category and category.strip() and category.strip().lower() != "all":
        sql += " AND s.category = ?"
        params.append(category.strip())

    sql += " GROUP BY s.variant_id ORDER BY net_units_sold DESC LIMIT ?"
    params.append(int(limit))

    rows = db.query_all(sql, params)
    res = []
    for r in rows:
        specs = f"{r['ram']} {r['storage']} {r['color']}".strip()
        res.append({
            "variant_id": r["variant_id"],
            "product_id": r["product_id"],
            "model_name": r["model_name"],
            "brand": r["brand"],
            "category": r["category"],
            "item_type": r["item_type"],
            "specs": specs,
            "barcode": r["barcode"] or "",
            "retail_price": r["retail_price"],
            "current_stock": r["current_stock"],
            "alert_state": r["alert_state"],
            "net_units_sold": int(r["net_units_sold"] or 0)
        })
    return res
