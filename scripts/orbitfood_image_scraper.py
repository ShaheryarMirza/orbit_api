#!/usr/bin/env python3
"""
Orbitfood Product Image Scraper & Supabase Restorer
====================================================
1. Queries database for products missing valid image URLs.
2. Uses Excel catalog (orbitfood_products.xlsx) and/or Selenium (www.orbitfood.co.uk) as image source.
3. Downloads high-resolution image binary buffers into memory.
4. Uploads image binaries directly to Supabase Storage (products bucket).
5. Updates portal database image_url column with permanent Public URLs.
"""

import sys
import os
import re
import time
import argparse
import mimetypes
import urllib.request
import urllib.parse
import urllib.error
import pandas as pd
from io import BytesIO

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from sqlalchemy import text
from app.db.database import SessionLocal

# Selenium imports (optional fallback)
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Configuration
EXCEL_PATH = os.path.join(os.path.dirname(os.path.dirname(backend_dir)), "orbitfood_products.xlsx")
ORBITFOOD_DOMAINS = ["https://www.orbitfood.co.uk", "https://orbitfood.co.uk"]
ORBITFOOD_USER = "shahbaz"
ORBITFOOD_PASS = "Shahbaz@123"

SUPABASE_URL = "https://iqwpwawpmndewyxmvpju.supabase.co"
SUPABASE_BUCKET = "products"
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
)
PUBLIC_URL_PREFIX = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}"


def build_excel_image_map():
    """Builds a mapping of SKU -> Picture URL from orbitfood_products.xlsx if available."""
    excel_map = {}
    if os.path.exists(EXCEL_PATH):
        try:
            df = pd.read_excel(EXCEL_PATH)
            for idx, row in df.iterrows():
                name_val = str(row.get("Name", "")).strip() if pd.notna(row.get("Name")) else ""
                pic_val = str(row.get("Picture URL", "")).strip() if pd.notna(row.get("Picture URL")) else ""
                if name_val and pic_val and (pic_val.startswith("http://") or pic_val.startswith("https://")):
                    match = re.match(r"^([a-zA-Z0-9\-]+)\s+(.*)$", name_val)
                    sku = match.group(1).strip().lower() if match else name_val.lower()
                    excel_map[sku] = pic_val
            print(f"[+] Loaded {len(excel_map)} product image URLs from {os.path.basename(EXCEL_PATH)}.")
        except Exception as exc:
            print(f"[!] Warning: Could not read Excel image map ({exc}).")
    return excel_map


def setup_selenium_driver(headless=True):
    """Initializes Selenium Chrome webdriver."""
    if not SELENIUM_AVAILABLE:
        return None
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(20)
        return driver
    except Exception as exc:
        print(f"[!] Selenium driver setup skipped ({exc}).")
        return None


def fetch_missing_products(db, force_all=False, sku_target=None, limit=None):
    """Queries portal database for products missing valid image URLs."""
    if sku_target:
        query = text("SELECT id, product_code, product_name, image_url FROM products WHERE LOWER(product_code) = :sku")
        rows = db.execute(query, {"sku": sku_target.lower()}).fetchall()
    elif force_all:
        query = text("SELECT id, product_code, product_name, image_url FROM products ORDER BY id")
        rows = db.execute(query).fetchall()
    else:
        query = text("""
            SELECT id, product_code, product_name, image_url 
            FROM products 
            WHERE image_url IS NULL 
               OR image_url = '' 
               OR LOWER(image_url) IN ('none', 'null', 'nan', 'undefined')
               OR image_url NOT LIKE 'http%'
            ORDER BY id
        """)
        rows = db.execute(query).fetchall()

    if limit:
        rows = rows[:limit]

    return rows


def download_image_binary(url, max_retries=3):
    """Downloads image file directly into memory as a binary buffer."""
    import ssl
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    last_err = None

    # Method A: requests Session with SSL verify=False
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, verify=False, timeout=25)
            if resp.status_code == 200 and len(resp.content) > 0:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return resp.content, content_type
        except Exception as exc:
            last_err = exc

        # Method B: urllib with unverified SSL context
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=25) as resp:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                data = resp.read()
                if len(data) > 0:
                    return data, content_type
        except Exception as exc:
            last_err = exc

        if attempt < max_retries:
            time.sleep(1)

    raise Exception(f"Image download failed: {last_err}")



def upload_to_supabase_storage(filename, file_bytes, content_type):
    """Uploads binary image buffer directly to Supabase Storage products bucket."""
    local_paths = [
        os.path.join(backend_dir, "uploads", "products", filename),
        os.path.join(os.path.dirname(backend_dir), "frontend", "public", "uploads", "products", filename)
    ]
    for p in local_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(file_bytes)
        except Exception:
            pass

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
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass
        except Exception as exc:
            print(f"[!] Supabase upload notice for {filename}: {exc}")

    return f"{PUBLIC_URL_PREFIX}/{filename}"


def sanitize_sku_filename(sku, content_type, url):
    """Generates standard SKU filename (e.g. prod_00775-03.jpg)."""
    ext = mimetypes.guess_extension(content_type)
    if not ext:
        if ".png" in url.lower(): ext = ".png"
        elif ".jpeg" in url.lower() or ".jpg" in url.lower(): ext = ".jpg"
        elif ".webp" in url.lower(): ext = ".webp"
        else: ext = ".jpg"
    if ext == ".jpe": ext = ".jpg"

    clean_sku = re.sub(r"[^a-zA-Z0-9\-]", "_", str(sku).strip())
    return f"prod_{clean_sku}{ext}"


def run_scraper(force_all=False, sku_target=None, limit=None, headless=True):
    db = SessionLocal()
    driver = None
    
    success_count = 0
    error_count = 0
    skipped_count = 0

    try:
        # Step 1: Identify Missing Images in Database
        products_to_process = fetch_missing_products(db, force_all=force_all, sku_target=sku_target, limit=limit)
        print(f"[+] Found {len(products_to_process)} target products in database.")

        if not products_to_process:
            print("[+] All products in database currently have valid image URLs. No missing images to restore!")
            return success_count, error_count, skipped_count

        # Step 2: Excel Image Mapping & Selenium Fallback
        excel_image_map = build_excel_image_map()
        site_image_map = {}

        driver = setup_selenium_driver(headless=headless)
        if driver:
            try:
                for domain in ORBITFOOD_DOMAINS:
                    try:
                        driver.get(f"{domain}/login.html")
                        time.sleep(2)
                        driver.find_element(By.ID, "username").send_keys(ORBITFOOD_USER)
                        driver.find_element(By.ID, "password").send_keys(ORBITFOOD_PASS)
                        driver.find_element(By.ID, "button").click()
                        time.sleep(3)
                        break
                    except Exception:
                        pass
                
                images_on_site = driver.find_elements(By.TAG_NAME, "img")
                for img in images_on_site:
                    src = img.get_attribute("src") or ""
                    if "/img/products/" in src:
                        try: parent_text = img.find_element(By.XPATH, "./ancestor::div[1]").text
                        except Exception: parent_text = ""
                        match = re.search(r"\b([a-zA-Z0-9]{3,8}-[a-zA-Z0-9]{2,4})\b", parent_text)
                        if match:
                            site_image_map[match.group(1).strip().lower()] = src
            except Exception as exc:
                print(f"[!] Selenium browser load notice: {exc}")

        # Step 3 & 4: Download Binary, Supabase Upload & DB Update
        print("\n--- Starting Image Download, Supabase Upload & DB Restorer ---")
        
        for idx, (prod_id, prod_code, prod_name, curr_url) in enumerate(products_to_process, start=1):
            sku_clean = str(prod_code).strip().lower()
            img_src = excel_image_map.get(sku_clean) or site_image_map.get(sku_clean)

            if not img_src:
                errors_msg = f"No image source URL found for SKU '{prod_code}' ({prod_name})"
                print(f"[{idx}/{len(products_to_process)}] [SKIPPED] Product ID {prod_id} | SKU {prod_code}: {errors_msg}")
                skipped_count += 1
                continue

            try:
                # Download binary directly into memory buffer
                img_binary, content_type = download_image_binary(img_src)
                filename = sanitize_sku_filename(prod_code, content_type, img_src)

                # Upload directly to Supabase Storage
                permanent_url = upload_to_supabase_storage(filename, img_binary, content_type)

                # Update Portal Database row
                db.execute(
                    text("UPDATE products SET image_url = :url, updated_at = NOW() WHERE id = :id"),
                    {"url": permanent_url, "id": prod_id}
                )
                db.commit()

                success_count += 1
                print(f"[{idx}/{len(products_to_process)}] [SUCCESS] Product ID {prod_id} | SKU {prod_code} => {permanent_url}")

            except Exception as exc:
                db.rollback()
                error_count += 1
                print(f"[{idx}/{len(products_to_process)}] [ERROR] Product ID {prod_id} | SKU {prod_code}: {exc}")

    finally:
        db.close()
        if driver:
            try: driver.quit()
            except Exception: pass

    # Summary
    print("\n" + "="*60)
    print("ORBITFOOD IMAGE SCRAPER & SUPABASE RESTORER SUMMARY")
    print("="*60)
    print(f"Total Target Products: {len(products_to_process) if 'products_to_process' in locals() else 0}")
    print(f"Successfully Restored: {success_count}")
    print(f"Skipped / Unmatched:   {skipped_count}")
    print(f"Failed / Errors:       {error_count}")
    print("="*60 + "\n")

    return success_count, error_count, skipped_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orbitfood Selenium Image Scraper & Supabase Restorer")
    parser.add_argument("--all", action="store_true", help="Force process all products in database")
    parser.add_argument("--sku", type=str, help="Target a specific product by SKU")
    parser.add_argument("--limit", type=int, help="Limit number of products to process")
    parser.add_argument("--no-headless", action="store_true", help="Run browser in visible mode")

    args = parser.parse_args()
    run_scraper(force_all=args.all, sku_target=args.sku, limit=args.limit, headless=not args.no_headless)
