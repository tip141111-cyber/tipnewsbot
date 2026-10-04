import re
from collections import Counter
from difflib import SequenceMatcher

from tipnews.domain.models import Article


def select_articles(articles: list[Article], limit: int = 10) -> list[Article]:
    """Bound source/topic dominance; title similarity is not semantic fact checking."""
    selected: list[Article] = []
    titles: list[str] = []
    topics: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    ordered = sorted(articles, key=lambda a: (a.priority, a.published_at), reverse=True)
    for article in ordered:
        if topics[article.topic] >= 2 or sources[article.source_id] >= 2:
            continue
        title = re.sub(r"\W+", " ", article.title.casefold()).strip()
        if any(SequenceMatcher(None, title, old).ratio() >= 0.88 for old in titles):
            continue
        selected.append(article)
        titles.append(title)
        topics[article.topic] += 1
        sources[article.source_id] += 1
        if len(selected) == limit:
            break
    return selected
