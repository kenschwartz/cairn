import dataclasses
import math
import re

ENTROPY_THRESHOLD = 3.0


@dataclasses.dataclass
class Finding:
    rule: str
    path: str
    line: int
    excerpt: str


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(s)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        entropy -= p * math.log2(p)
    return entropy


def _luhn_valid(digits: str) -> bool:
    if len(digits) < 2:
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask(value: str) -> str:
    if len(value) > 12:
        return value[:12]
    if len(value) > 6:
        return value[:6]
    if len(value) > 3:
        return value[:3]
    return value[:1] if value else ""


_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")
_AWS_RE = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA)[0-9A-Z]{16}\b")
_TOKEN_LABEL_RE = re.compile(
    r'(?i)\b(?:secret|token|api[_-]?key|apikey|password|passwd|access[_-]?key)\b\s*[:=]\s*["\']?([A-Za-z0-9+/=_\-]{32,})'
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_FP_RE = re.compile(r"(?i)(commit|sha|hash|uuid|guid|ticket|jira|version|build)")


def scan_bytes(data: bytes, path: str) -> list[Finding]:
    if b"\x00" in data[:8192]:
        return []

    findings = []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()

    for line_num, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if stripped.endswith("cairn:allow-secret"):
            continue

        for m in _PRIVATE_KEY_RE.finditer(line):
            findings.append(
                Finding(
                    rule="private_key",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        for m in _AWS_RE.finditer(line):
            findings.append(
                Finding(
                    rule="aws_access_key_id",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        for m in _TOKEN_LABEL_RE.finditer(line):
            token = m.group(1)
            if _shannon_entropy(token) >= ENTROPY_THRESHOLD:
                findings.append(
                    Finding(
                        rule="labelled_token",
                        path=path,
                        line=line_num,
                        excerpt=_mask(token),
                    )
                )

        for m in _SSN_RE.finditer(line):
            findings.append(
                Finding(
                    rule="us_ssn",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        i = 0
        while i < len(line):
            if line[i].isdigit():
                start = i
                digit_count = 0
                while i < len(line) and (line[i].isdigit() or line[i] in " -"):
                    if line[i].isdigit():
                        digit_count += 1
                    i += 1
                if digit_count >= 13:
                    digits_only = "".join(ch for ch in line[start:i] if ch.isdigit())
                    if 13 <= len(digits_only) <= 19 and _luhn_valid(digits_only):
                        before = line[max(0, start - 40) : start]
                        after = line[i : min(len(line), i + 40)]
                        context = before + after
                        if not _FP_RE.search(context):
                            findings.append(
                                Finding(
                                    rule="payment_card",
                                    path=path,
                                    line=line_num,
                                    excerpt=_mask(digits_only),
                                )
                            )
                continue
            i += 1

    return findings
