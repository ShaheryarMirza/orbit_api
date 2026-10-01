import requests

def inspect_full_html():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    r = s.get('https://orbitfood.co.uk/', timeout=10)
    print("HTML length:", len(r.text))
    print(r.text[:3000])

if __name__ == '__main__':
    inspect_full_html()
