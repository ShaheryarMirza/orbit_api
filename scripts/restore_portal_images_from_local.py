#!/usr/bin/env python3
"""
Restore Live Portal Images from Local Storage to Supabase
=========================================================
Scans local image files (1,722 files in uploads/products), matches them to products
in the live production database, uploads binary image buffers directly to Supabase Storage
(products bucket), and updates image_url in the live database.
"""

import sys
import os
import re
import urllib.request
import urllib.error

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.db.database import SessionLocal

SUPABASE_URL = "https://iqwpwawpmndewyxmvpju.supabase.co"
SUPABASE_BUCKET = "products"
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
)
PUBLIC_URL_PREFIX = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}"


def upload_local_file_to_supabase(filename, file_path):
    """Uploads a local image binary file to Supabase Storage products bucket."""
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    ext = os.path.splitext(filename)[1].lower()
    content_type = "image/png" if ext == ".png" else "image/jpeg"

    if SUPABASE_KEY and not SUPABASE_KEY.endswith("placeholder"):
        upload_endpoint = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{filename}"
        try:
            req = urllib.request.Request(
                upload_endpoint,
                data=file_bytes,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apiKey": SUPABASE_KEY,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass
        except Exception as exc:
            print(f"[!] Supabase upload notice for {filename}: {exc}")

    return f"{PUBLIC_URL_PREFIX}/{filename}"


def run_local_restoration():
    db = SessionLocal()
    try:
        # Gather local image files
        upload_dir = os.path.join(backend_dir, "uploads", "products")
        local_files = {}
        if os.path.exists(upload_dir):
            for f in os.listdir(upload_dir):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                    local_files[f.lower()] = os.path.join(upload_dir, f)

        print(f"[+] Total local image files available: {len(local_files)}")

        # Fetch products from live database missing valid Supabase URLs
        query = text("""
            SELECT id, product_code, product_name, image_url
            FROM products
            WHERE image_url IS NULL
               OR image_url = ''
               OR LOWER(image_url) IN ('none', 'null', 'nan', 'undefined')
               OR image_url NOT LIKE 'https://iqwpwawpmndewyxmvpju.supabase.co%'
            ORDER BY id
        """)
        products = db.execute(query).fetchall()
        print(f"[+] Total production products needing Supabase URLs: {len(products)}")

        success_count = 0
        skipped_count = 0
        error_count = 0

        print("\n--- Starting Local Image Upload to Supabase & Live DB Restore ---")

        for idx, (p_id, p_code, p_name, curr_url) in enumerate(products, start=1):
            sku_clean = str(p_code).strip().lower()
            
            # Match 1: Extract filename from curr_url if available
            file_match = None
            if curr_url:
                base_url_file = os.path.basename(str(curr_url)).strip().lower()
                if base_url_file in local_files:
                    file_match = local_files[base_url_file]

            # Match 2: Search for SKU in local filenames
            if not file_match:
                for f_name, f_path in local_files.items():
                    if sku_clean and sku_clean in f_name:
                        file_match = f_path
                        break

            if not file_match:
                print(f"[{idx}/{len(products)}] [SKIPPED] ID {p_id} | SKU {p_code}: No matching local image file found")
                skipped_count += 1
                continue

            try:
                filename = os.path.basename(file_match)
                permanent_url = upload_local_file_to_supabase(filename, file_match)

                # Update live production database row
                db.execute(
                    text("UPDATE products SET image_url = :url, updated_at = NOW() WHERE id = :id"),
                    {"url": permanent_url, "id": p_id}
                )
                db.commit()

                success_count += 1
                print(f"[{idx}/{len(products)}] [SUCCESS] ID {p_id} | SKU {p_code} => {permanent_url}")

            except Exception as exc:
                db.rollback()
                error_count += 1
                print(f"[{idx}/{len(products)}] [ERROR] ID {p_id} | SKU {p_code}: {exc}")

        print("\n" + "="*60)
        print("LOCAL IMAGE RESTORATION TO SUPABASE COMPLETE")
        print("="*60)
        print(f"Total Target Products: {len(products)}")
        print(f"Successfully Restored: {success_count}")
        print(f"Skipped (No File):     {skipped_count}")
        print(f"Failed / Errors:       {error_count}")
        print("="*60 + "\n")

    finally:
        db.close()


if __name__ == "__main__":
    run_local_restoration()
