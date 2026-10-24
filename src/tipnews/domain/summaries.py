import re


def validate_summary(result: str, material: str) -> str:
    """Shared output checks; numeric literals are not semantic fact verification."""
    result = result.strip()
    if not 25 <= len(result) <= 600 or re.search(r"https?://|<[^>]+>", result, re.IGNORECASE):
        raise ValueError("Invalid model summary")
    if not set(re.findall(r"\d+", result)) <= set(re.findall(r"\d+", material)):
        raise ValueError("Summary introduced numeric literals")
    return result
