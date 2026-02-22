import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import time
import random


HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def fetch_marketplace_results(keyword: str) -> List[Dict]:
    """
    Use DuckDuckGo search results to simulate marketplace signals.
    More stable than scraping Amazon directly.
    """

    url = "https://html.duckduckgo.com/html/"
    params = {"q": f"{keyword} buy online price India"}

    try:
        time.sleep(random.uniform(1, 2))

        response = requests.post(url, data=params, headers=HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        products = []

        for result in soup.find_all("div", class_="result")[:10]:
            title_tag = result.find("a", class_="result__a")

            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href")

                products.append({
                    "title": title,
                    "price": 0.0,
                    "rating": 0.0,
                    "reviews": 0,
                    "platform": "Web Search"
                })

        return products

    except Exception as e:
        print(f"[Marketplace Scraper Error]: {e}")
        return []