import os
import sys
import json
import re
import requests
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath('.'))

from app.db.database import SessionLocal
from app.models.product import Product
from app.core.config import settings

SUPABASE_URL = settings.SUPABASE_URL.rstrip('/')
SUPABASE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_ANON_KEY or ""
SUPABASE_BUCKET = settings.SUPABASE_STORAGE_BUCKET or "products"

def upload_bytes_to_supabase(file_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    """Uploads bytes directly to Supabase Storage and returns permanent CDN URL."""
    object_path = f"products/{filename}"
    upload_endpoint = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_path}"
    
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
        if resp.status in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_path}"
        else:
            raise Exception(f"Supabase upload failed with status {resp.status}")

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def run_sync():
    print("==================================================")
    print("STARTING PRODUCT IMAGE SCRAPE & SUPABASE SYNC")
    print("==================================================")

    # Step 1: Fetch catalog from orbitfood.co.uk
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    url = 'https://orbitfood.co.uk/products.php?q=true'
    print(f"Fetching catalog from {url}...")
    resp = session.get(url, timeout=20)
    if resp.status_code != 200:
        print(f"Error fetching catalog: status {resp.status_code}")
        return

    data = resp.json()
    if isinstance(data, str):
        data = json.loads(data)

    orbit_items = [] # list of dicts {sku, name, id, img_file, full_img_url}
    
    for cat_name, cat_items in data.items():
        if isinstance(cat_items, dict):
            for name, val in cat_items.items():
                # val format: [id, price, desc, img_file, qty, vat]
                if not isinstance(val, list) or len(val) < 4:
                    continue
                
                raw_id = str(val[0]).strip()
                img_file = str(val[3]).strip()
                
                # Extract SKU from name if name starts with code e.g. "00079-08 Ulker..." or "4300 Mountain..."
                # SKU patterns: 5+ digits, or digits-digits (e.g. 00079-08, 4300, 2632)
                sku_match = re.match(r'^([A-Za-z0-9\-]+)\s+(.+)', name.strip())
                extracted_sku = ""
                clean_name = name.strip()
                if sku_match:
                    extracted_sku = sku_match.group(1)
                    clean_name = sku_match.group(2)

                if img_file and img_file.lower() != 'none' and img_file.strip():
                    img_url = f"https://orbitfood.co.uk/img/products/{urllib.parse.quote(img_file)}"
                    orbit_items.append({
                        'raw_id': raw_id,
                        'extracted_sku': extracted_sku,
                        'full_name': name.strip(),
                        'clean_name': clean_name,
                        'img_file': img_file,
                        'img_url': img_url,
                        'norm_name': normalize_text(clean_name),
                        'norm_full': normalize_text(name)
                    })

    print(f"Found {len(orbit_items)} products with images in orbitfood.co.uk catalog.")

    # Index orbit_items for fast lookup
    sku_map = {}
    id_map = {}
    norm_name_map = {}

    for item in orbit_items:
        if item['extracted_sku']:
            sku_map[item['extracted_sku'].lower()] = item
        if item['raw_id']:
            id_map[item['raw_id']] = item
        norm_name_map[item['norm_full']] = item
        norm_name_map[item['norm_name']] = item

    # Step 2: Query DB products
    db = SessionLocal()
    db_products = db.query(Product).filter(Product.is_active == True).all()
    print(f"Loaded {len(db_products)} active products from database.")

    updated_count = 0
    skipped_count = 0
    failed_count = 0

    for p in db_products:
        p_code = (p.product_code or "").strip()
        p_name = (p.product_name or "").strip()
        
        matched_item = None
        
        # Match Strategy 1: Exact SKU / Product Code
        if p_code.lower() in sku_map:
            matched_item = sku_map[p_code.lower()]
        
        # Match Strategy 2: Raw ID matching Product Code
        elif p_code in id_map:
            matched_item = id_map[p_code]

        # Match Strategy 3: Normalized full name / clean name
        elif normalize_text(p_name) in norm_name_map:
            matched_item = norm_name_map[normalize_text(p_name)]

        # Match Strategy 4: SKU prefix in product name
        if not matched_item:
            for item in orbit_items:
                if item['extracted_sku'] and item['extracted_sku'].lower() == p_code.lower():
                    matched_item = item
                    break

        if not matched_item:
            continue

        # Check if we should update: either image_url is missing/local, or force refresh
        is_missing_or_local = not p.image_url or p.image_url.startswith('/uploads/') or 'placeholder' in p.image_url.lower()

        # Download image from orbitfood.co.uk and upload to Supabase
        img_src_url = matched_item['img_url']
        try:
            img_resp = session.get(img_src_url, timeout=15)
            if img_resp.status_code != 200:
                print(f"FAILED to download image for SKU `{p_code}` ({p_name}): {img_src_url} status {img_resp.status_code}")
                failed_count += 1
                continue
            
            file_bytes = img_resp.content
            if len(file_bytes) < 100:
                print(f"SKIPPED (Empty file) SKU `{p_code}`: {img_src_url}")
                continue

            # Detect content type & ext
            ext = os.path.splitext(matched_item['img_file'])[1].lower()
            if not ext or ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
                ext = '.jpg'
            
            content_type = "image/png" if ext == ".png" else "image/jpeg"
            clean_filename = f"prod_{p_code}_{re.sub(r'[^a-zA-Z0-9]', '_', matched_item['img_file'])}{ext}"
            
            supabase_cdn_url = upload_bytes_to_supabase(file_bytes, clean_filename, content_type)
            
            old_url = p.image_url
            p.image_url = supabase_cdn_url
            updated_count += 1
            print(f"[{updated_count}] SUCCESS SKU `{p_code}` | Name: {p_name}")
            print(f"    From: {img_src_url}")
            print(f"    To:   {supabase_cdn_url}")

        except Exception as err:
            print(f"ERROR uploading image for SKU `{p_code}` ({p_name}): {err}")
            failed_count += 1

    db.commit()
    db.close()

    print("\n==================================================")
    print(f"SUMMARY: Successfully updated {updated_count} products with high-res images from orbitfood.co.uk!")
    print(f"Failed: {failed_count}")
    print("==================================================")

if __name__ == '__main__':
    run_sync()
