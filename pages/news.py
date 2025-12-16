import requests
from datetime import datetime

News_API_Key= "53382e6fa6ba40398c08d280c0d9f732"

def fetch_news(tickers, page_size=5):
    articles=[]

    for ticker in tickers:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": ticker,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": page_size,
            "apiKey": News_API_Key,
        }
        r=requests.get(url,params=params)
        r.raise_for_status()

        for a in r.json().get("articles", []):
            articles.append({
                "ticker": ticker,
                "title": a["title"],
                "description": a["description"],
                "url": a["url"],
                "publishedAt": datetime.strptime(a["publishedAt"], "%Y-%m-%dT%H:%M:%SZ"),
            })
            return sorted(articles, key=lambda x: x["publishedAt"], reverse=True)