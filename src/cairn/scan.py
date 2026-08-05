import dataclasses
import re


@dataclasses.dataclass
class Finding:
    rule: str
    path: str
    line: int
    excerpt: str


def _mask(value: str) -> str:
    n = len(value)
    if n <= 2:
        return "[...]"
    if n <= 8:
        return value[0] + "[...]" + value[-1]
    return value[:4] + "[...]" + value[-4:]


_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|PGP) )?(?:ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
)
_AWS_RE = re.compile(
    r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA)[0-9A-Z]{16}\b"
)
_PUBLIC_KEY_RE = re.compile(r"-----BEGIN (?:.* )?PUBLIC KEY-----")
_SSH_PUB_RE = re.compile(
    r"^(?:ssh-rsa|ssh-dss|ssh-ed25519|ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9-]+)(?:@[a-z0-9.-]+)?\s+[A-Za-z0-9+/=]{40,}"
)
_GITHUB_RE = re.compile(r"gh[opsru]_[A-Za-z0-9]{36}")
_ANTHROPIC_RE = re.compile(r"sk-ant-api[A-Za-z0-9_-]{20,}")


def scan_bytes(data: bytes, path: str) -> list[Finding]:
    if b"\x00" in data[:8192]:
        return []

    findings = []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()

    for line_num, line in enumerate(lines, start=1):
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

        for m in _PUBLIC_KEY_RE.finditer(line):
            findings.append(
                Finding(
                    rule="public_key",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        for m in _SSH_PUB_RE.finditer(line):
            findings.append(
                Finding(
                    rule="ssh_public_key",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        for m in _GITHUB_RE.finditer(line):
            findings.append(
                Finding(
                    rule="github_token",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

        for m in _ANTHROPIC_RE.finditer(line):
            findings.append(
                Finding(
                    rule="anthropic_api_key",
                    path=path,
                    line=line_num,
                    excerpt=_mask(m.group(0)),
                )
            )

    return findings
