import re
import unicodedata


def normalize_tag(tag: str) -> str:
    """
    Normalize a tag per DESIGN:441 (docs/decisions.md).

    Algorithm:
    1. NFKD normalization then drop combining marks (like slugs.slugify).
    2. lowercase.
    3. Split on '/'.
    4. For each segment: replace every run of non-alphanumeric characters
       with a single hyphen, strip leading/trailing hyphens.
    5. Rejoin segments with '/'.
    6. Empty result -> return original unchanged.

    Examples:
    - "Trade Finance" -> "trade-finance"
    - "CFG/Security" -> "cfg/security" (slash preserved)
    - "A & B" -> "a-b"
    - "café" -> "cafe" (NFKD)
    - "a / b" -> "a/b" (spaces around slash do not survive)
    """
    # Step 1: NFKD normalization + drop combining marks (same as slugs.slugify)
    normalized = unicodedata.normalize("NFKD", tag)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    # Step 2: lowercase
    ascii_text = ascii_text.lower()

    # Step 3: Split on '/'
    segments = ascii_text.split("/")

    # Step 4: Process each segment
    processed = []
    for seg in segments:
        # Replace runs of non-alphanumeric characters with a single hyphen
        seg = re.sub(r"[^a-z0-9]+", "-", seg)
        # Strip leading/trailing hyphens
        seg = seg.strip("-")
        processed.append(seg)

    # Step 5: Rejoin with '/'
    result = "/".join(processed)

    # Step 6: Empty result -> return original unchanged
    if not result:
        return tag

    return result
