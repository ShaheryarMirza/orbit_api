import requests

def inspect_login_html():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    r = s.get('https://orbitfood.co.uk/login.html', timeout=10)
    print("login.html status:", r.status_code)
    print(r.text)

if __name__ == '__main__':
    inspect_login_html()
