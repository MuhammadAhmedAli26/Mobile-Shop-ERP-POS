# logo_engine.py
# Universal Logo Processing Engine (UI Web, Favicon & ESC-POS 80mm/58mm 1-bit Monochrome Thermal Bitmaps)

import io
from datetime import datetime
from PIL import Image
import db

def generate_esc_pos_raster(mono_img):
    """Encodes a PIL 1-bit image ('1' mode) into ESC-POS GS v 0 raster command format."""
    w, h = mono_img.size
    bytes_per_row = (w + 7) // 8
    
    # Header: GS v 0 m xL xH yL yH
    # m = 0 (Normal mode)
    header = bytearray([
        0x1D, 0x76, 0x30, 0x00,
        bytes_per_row % 256,
        bytes_per_row // 256,
        h % 256,
        h // 256
    ])
    
    data = bytearray()
    for y in range(h):
        row_byte = 0
        bit_count = 0
        for x in range(w):
            pixel = mono_img.getpixel((x, y))
            # In PIL '1' mode: 0 = Black, 255 = White
            # In ESC/POS thermal raster: 1 = Print dot (Black), 0 = White
            if pixel == 0:
                row_byte |= (1 << (7 - bit_count))
            bit_count += 1
            if bit_count == 8:
                data.append(row_byte)
                row_byte = 0
                bit_count = 0
        if bit_count > 0:
            data.append(row_byte)
            
    return bytes(header + data)

def process_and_store_logo(image_bytes):
    """Processes uploaded logo image into UI PNG, Favicon, and ESC-POS 80mm/58mm bitmaps."""
    if not image_bytes or len(image_bytes) < 8:
        return {"success": False, "message": "Invalid or empty image file."}

    if len(image_bytes) > 5 * 1024 * 1024:
        return {"success": False, "message": "Image file too large (maximum 5 MB)."}

    try:
        raw_img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        return {"success": False, "message": f"Unable to read image format: {e}"}

    # Convert to RGB with white background (handles transparent PNG/WebP cleanly)
    if raw_img.mode in ("RGBA", "LA") or (raw_img.mode == "P" and "transparency" in raw_img.info):
        rgba = raw_img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.paste(rgba, (0, 0), rgba)
        rgb_img = bg.convert("RGB")
    else:
        rgb_img = raw_img.convert("RGB")

    orig_w, orig_h = rgb_img.size

    # 1. UI Resized Logo (Max 320 x 100 for top-bar and receipt header)
    ui_img = rgb_img.copy()
    ui_img.thumbnail((320, 100), Image.Resampling.LANCZOS)
    ui_buf = io.BytesIO()
    ui_img.save(ui_buf, format="PNG", optimize=True)
    ui_bytes = ui_buf.getvalue()

    # 2. 80mm ESC-POS Raster (Max width 512 dots)
    max_w_80 = 512
    scale_80 = min(1.0, max_w_80 / orig_w)
    target_w_80 = int(orig_w * scale_80)
    target_h_80 = max(1, int(orig_h * scale_80))
    img_80 = rgb_img.resize((target_w_80, target_h_80), Image.Resampling.LANCZOS)
    # Floyd-Steinberg dithering to 1-bit monochrome
    mono_80 = img_80.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    esc_80_bytes = generate_esc_pos_raster(mono_80)

    # 3. 58mm ESC-POS Raster (Max width 384 dots)
    max_w_58 = 384
    scale_58 = min(1.0, max_w_58 / orig_w)
    target_w_58 = int(orig_w * scale_58)
    target_h_58 = max(1, int(orig_h * scale_58))
    img_58 = rgb_img.resize((target_w_58, target_h_58), Image.Resampling.LANCZOS)
    mono_58 = img_58.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    esc_58_bytes = generate_esc_pos_raster(mono_58)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Atomic DB update
    with db.transaction() as cx:
        cx.execute("""
            INSERT INTO shop_profile (id, has_logo, logo_mime, logo_data, logo_thermal_80, logo_thermal_58, profile_version, updated_at)
            VALUES (1, 1, 'image/png', ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                has_logo = 1,
                logo_mime = 'image/png',
                logo_data = excluded.logo_data,
                logo_thermal_80 = excluded.logo_thermal_80,
                logo_thermal_58 = excluded.logo_thermal_58,
                profile_version = shop_profile.profile_version + 1,
                updated_at = excluded.updated_at
        """, (ui_bytes, esc_80_bytes, esc_58_bytes, now))

    db.bump_change_version("profile")

    return {
        "success": True,
        "width": orig_w,
        "height": orig_h,
        "ui_size": len(ui_bytes),
        "thermal_80_bytes": len(esc_80_bytes),
        "thermal_58_bytes": len(esc_58_bytes)
    }

def remove_logo():
    """Removes shop logo and resets thermal bitmaps."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.transaction() as cx:
        cx.execute("""
            UPDATE shop_profile SET
                has_logo = 0,
                logo_mime = '',
                logo_data = NULL,
                logo_thermal_80 = NULL,
                logo_thermal_58 = NULL,
                profile_version = profile_version + 1,
                updated_at = ?
            WHERE id = 1
        """, (now,))

    db.bump_change_version("profile")
    return {"success": True}

def get_logo_data():
    """Retrieves UI logo bytes and mime type from database."""
    row = db.query_one("SELECT logo_mime, logo_data FROM shop_profile WHERE id = 1 AND has_logo = 1")
    if row and row.get("logo_data"):
        return row["logo_data"], row.get("logo_mime") or "image/png"
    return None, None
