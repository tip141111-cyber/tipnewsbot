import re


def is_russian_summary(text: str) -> bool:
    """Reject untranslated prose while allowing Latin product names and abbreviations."""
    prose = re.sub(r"https?://\S+|<[^>]+>", "", text)
    russian = re.findall(r"[А-Яа-яЁё]", prose)
    letters = [character for character in prose if character.isalpha()]
    words = re.findall(r"[А-Яа-яЁё]{2,}", prose)
    return len(words) >= 2 and len(russian) >= 10 and len(russian) / max(1, len(letters)) >= 0.55
