import re


def normalize_tag(tag: str) -> str:
    tag = tag.lower()
    tag = re.sub(r"\s+", "-", tag.strip())
    return tag
