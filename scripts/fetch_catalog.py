import requests
import json

def fetch_orbitfood_catalog():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    url = 'https://orbitfood.co.uk/products.php?q=true'
    r = s.get(url, timeout=15)
    print("Catalog status:", r.status_code)
    
    # Try parsing json
    try:
        data = r.json()
        if isinstance(data, str):
            data = json.loads(data)
        
        print(f"Categories found: {len(data.keys())}")
        total_items = 0
        samples = []
        for cat, items in data.items():
            if isinstance(items, dict):
                for name, val in items.items():
                    total_items += 1
                    if len(samples) < 10:
                        # val structure: [id, price, desc, img_file, qty, vat]
                        samples.append((cat, name, val))
        
        print(f"Total products in catalog: {total_items}")
        print("\nFirst 10 sample products:")
        for cat, name, val in samples:
            print(f" Category: {cat} | Name: {name}")
            print(f"   Details: ID={val[0]}, Price={val[1]}, Img={val[3]}")
    except Exception as e:
        print("Error parsing json:", e)
        print("Raw text response (first 500 chars):", r.text[:500])

if __name__ == '__main__':
    fetch_orbitfood_catalog()
