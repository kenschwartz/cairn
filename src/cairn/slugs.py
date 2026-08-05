import re
import unicodedata
import uuid


def slugify(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    ascii_text = ascii_text.strip("-")
    if len(ascii_text) > 60:
        ascii_text = ascii_text[:60].rstrip("-")
    if not ascii_text:
        return f"note-{uuid.uuid4().hex[:8]}"
    return ascii_text
