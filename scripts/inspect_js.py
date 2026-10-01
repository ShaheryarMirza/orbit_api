import requests

def inspect_js():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    js_files = [
        'https://orbitfood.co.uk/js/index.js',
        'https://orbitfood.co.uk/js/simple_cart/simpleCart.js'
    ]

    for url in js_files:
        r = s.get(url, timeout=10)
        print(f"\n--- {url} (Status: {r.status_code}, Length: {len(r.text)}) ---")
        lines = r.text.splitlines()
        for line in lines:
            if any(k in line.lower() for k in ['http', 'ajax', 'login', 'api', 'product', 'image', 'url', 'php']):
                print(" ", line[:120].strip())

if __name__ == '__main__':
    inspect_js()
