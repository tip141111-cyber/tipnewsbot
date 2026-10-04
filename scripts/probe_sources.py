"""Read-only live feed diagnostics; never accepts credentials."""

import asyncio
import json

import feedparser
import httpx

URLS = [
    "https://github.blog/changelog/feed/",
    "https://kubernetes.io/feed.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://7info.ru/ryazan/feed/",
    "https://7info.ru/feed/",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
]


async def main() -> None:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, trust_env=False) as client:
        for url in URLS:
            try:
                response = await client.get(url)
                parsed = feedparser.parse(response.content)
                print(
                    json.dumps(
                        {
                            "url": url,
                            "status": response.status_code,
                            "final_url": str(response.url),
                            "bytes": len(response.content),
                            "type": response.headers.get("content-type"),
                            "version": parsed.get("version"),
                            "title": parsed.feed.get("title"),
                            "entries": len(parsed.entries),
                            "sample": [
                                {
                                    "title": e.get("title"),
                                    "date": e.get("published"),
                                    "summary_length": len(e.get("summary", "")),
                                }
                                for e in parsed.entries[:2]
                            ],
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
            except Exception as exc:
                print(json.dumps({"url": url, "error": type(exc).__name__}), flush=True)


asyncio.run(main())
