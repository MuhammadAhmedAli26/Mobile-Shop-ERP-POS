import shutil
import zipfile
import os
import sys
import hashlib
import glob

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def package():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    release_dir = os.path.join(base_dir, "release")
    os.makedirs(release_dir, exist_ok=True)

    # 1. Copy Single-File Standalone EXE
    src_onefile = os.path.join(dist_dir, "Mobile_Shop_ERP.exe")
    dst_onefile = os.path.join(release_dir, "Mobile_Shop_ERP.exe")
    if os.path.exists(src_onefile):
        shutil.copy2(src_onefile, dst_onefile)
        print(f"✓ Copied {src_onefile} -> {dst_onefile} ({os.path.getsize(dst_onefile):,} bytes)")

    # 2. Package Onedir into Portable ZIP
    onedir_path = os.path.join(dist_dir, "MobileShopERP")
    if os.path.exists(onedir_path):
        # Create portable flag
        with open(os.path.join(onedir_path, "portable.flag"), "w") as f:
            f.write("")
        zip_path = os.path.join(release_dir, "MobileShopERP-1.0.0-portable.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(onedir_path):
                for file in files:
                    full_p = os.path.join(root, file)
                    rel_p = os.path.relpath(full_p, onedir_path)
                    zf.write(full_p, rel_p)
        print(f"✓ Created {zip_path} ({os.path.getsize(zip_path):,} bytes)")

    # 3. Generate SHA-256 Checksums
    checksum_file = os.path.join(release_dir, "SHA256SUMS.txt")
    with open(checksum_file, "w", encoding="utf-8") as out_f:
        for p in glob.glob(os.path.join(release_dir, "*")):
            if os.path.isfile(p) and not p.endswith(".txt"):
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                out_f.write(f"{h}  {os.path.basename(p)}\n")
    print(f"✓ Generated {checksum_file}")

if __name__ == "__main__":
    package()
