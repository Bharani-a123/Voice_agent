# Search scraping tools
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import time
import random


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}


def fetch_search_results(query: str) -> List[Dict]:
    """
    Fetch search results from DuckDuckGo HTML endpoint.
    Returns list of dicts:
    [
        {"title": "", "snippet": "", "source": ""}
    ]
    """

    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}

    try:
        # Add slight delay to avoid aggressive scraping
        time.sleep(random.uniform(1, 2))

        response = requests.post(url, data=params, headers=HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        results = []

        for result in soup.find_all("div", class_="result")[:10]:
            title_tag = result.find("a", class_="result__a")
            snippet_tag = result.find("a", class_="result__snippet")

            if title_tag:
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href")

                snippet = ""
                if snippet_tag:
                    snippet = snippet_tag.get_text(strip=True)

                results.append({
                    "title": title,
                    "snippet": snippet,
                    "source": link
                })

        return results

    except Exception as e:
        print(f"[Search Scraper Error]: {e}")
        return []