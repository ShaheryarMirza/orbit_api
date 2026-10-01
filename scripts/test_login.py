import requests

def test_login():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    })

    # The exact string format expected by login.php
    data_str = "username='shahbaz'&password='Shahbaz@123'"
    
    r = s.post('https://orbitfood.co.uk/login.php', data=data_str, timeout=10)
    print("Login POST status:", r.status_code)
    print("Response raw text:", repr(r.text))

if __name__ == '__main__':
    test_login()
