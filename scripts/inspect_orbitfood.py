import requests
from bs4 import BeautifulSoup

def crawl_site():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    r = s.get('https://orbitfood.co.uk/', timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')
    
    print("Title:", soup.title.text if soup.title else "No title")
    print("\nAll links:")
    links = set()
    for a in soup.find_all('a', href=True):
        links.add(a['href'])
    for l in sorted(links):
        print(" ", l)

    print("\nAll scripts:")
    for sc in soup.find_all('script', src=True):
        print(" ", sc['src'])

if __name__ == '__main__':
    crawl_site()
