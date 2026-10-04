from html import escape

from tipnews.domain.language import is_russian_summary
from tipnews.domain.models import TOPIC_NAMES, DigestItem, Topic


def render_digest(day: str, items: list[DigestItem], topics: set[Topic]) -> str | None:
    sections = [f"<b>tipnews · {escape(day)}</b>"]
    count = 0
    for topic in (Topic.WEATHER, *(topic for topic in Topic if topic != Topic.WEATHER)):
        selected = [
            item
            for item in items
            if item.topic == topic
            and (topic in topics or topic == Topic.WEATHER)
            and is_russian_summary(item.summary)
        ]
        if not selected:
            continue
        heading = f"\n<b>{escape(TOPIC_NAMES[topic])}</b>"
        for item in selected:
            block = (
                f"\n{escape(item.summary)}\n"
                f'<a href="{escape(item.url, quote=True)}">{escape(item.source_name)}</a>\n'
            )
            addition = heading + block
            if len("\n".join(sections)) + len(addition) > 3700:
                continue
            sections.append(addition)
            heading = ""
            count += 1
    if not count:
        return None
    sections.append("\nКратко по публикациям в лентах источников.")
    return "\n".join(sections)
