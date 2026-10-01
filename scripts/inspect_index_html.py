import requests

def inspect_index_html():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    r = s.get('https://orbitfood.co.uk/index.html', timeout=10)
    print("index.html status:", r.status_code)
    print(r.text)

if __name__ == '__main__':
    inspect_index_html()
