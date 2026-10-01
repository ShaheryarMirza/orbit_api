#!/usr/bin/env python3
"""
Fix and Restore Working Product Image URLs
===========================================
Scans local image uploads (1,722 files), matches them against the live production
database products, and updates image_url to valid working links.
"""

import sys
import os

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.db.database import SessionLocal

def fix_and_restore_images():
    db = SessionLocal()
    try:
        print("[*] Connecting to Live Production Database...")
        upload_dir = os.path.join(backend_dir, "uploads", "products")
        local_files = {}

        if os.path.exists(upload_dir):
            for f in os.listdir(upload_dir):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                    local_files[f.lower()] = f

        print(f"[+] Total local image files available: {len(local_files)}")

        products = db.execute(text("SELECT id, product_code, product_name, image_url FROM products ORDER BY id")).fetchall()
        print(f"[+] Total production products: {len(products)}")

        restored_count = 0

        for p_id, p_code, p_name, curr_url in products:
            sku_clean = str(p_code).strip().lower()
            
            matched_filename = None
            if curr_url:
                base_url_file = os.path.basename(str(curr_url)).strip().lower()
                if base_url_file in local_files:
                    matched_filename = local_files[base_url_file]

            if not matched_filename:
                for f_name, orig_filename in local_files.items():
                    if sku_clean and sku_clean in f_name:
                        matched_filename = orig_filename
                        break

            if matched_filename:
                working_url = f"/uploads/products/{matched_filename}"
                db.execute(
                    text("UPDATE products SET image_url = :url, updated_at = NOW() WHERE id = :id"),
                    {"url": working_url, "id": p_id}
                )
                restored_count += 1

        db.commit()
        print(f"\n[+] SUCCESS: Restored working image_url links for {restored_count} out of {len(products)} products in Production Database!")

    except Exception as exc:
        db.rollback()
        print(f"[!] Error restoring images: {exc}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    fix_and_restore_images()
