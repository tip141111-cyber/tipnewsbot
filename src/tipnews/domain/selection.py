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
    def add(article: Article) -> bool:
        if topics[article.topic] >= 2 or sources[article.source_id] >= 2:
            return False
        title = re.sub(r"\W+", " ", article.title.casefold()).strip()
        if any(SequenceMatcher(None, title, old).ratio() >= 0.88 for old in titles):
            return False
        selected.append(article)
        titles.append(title)
        topics[article.topic] += 1
        sources[article.source_id] += 1
        return True

    # Give each populated rubric one slot before allowing high-volume sources
    # to fill the remaining edition.
    for topic in dict.fromkeys(article.topic for article in ordered):
        article = next((item for item in ordered if item.topic == topic), None)
        if article is not None:
            add(article)
            if len(selected) == limit:
                return selected
    for article in ordered:
        if len(selected) == limit:
            break
        add(article)
    return selected
