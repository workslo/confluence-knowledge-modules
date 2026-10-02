"""Secret / PII scan run on every page before anything is written. Fails closed.

A hit blocks the page: its module is not written, the manifest records `blocked` with the
finding names (never the matched text), and `ckm check` fails until a human resolves it —
by fixing the source, or by allow-listing a known-safe literal in config.
"""

import re
from dataclasses import dataclass

from ckm.config import Config

DEFAULT_PATTERNS: dict[str, str] = {
    "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "slack_token": r"\bxox[abpors]-[A-Za-z0-9-]{10,}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    "password_assignment": r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key)\s*[:=]\s*\S{6,}",
    "us_ssn": r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
    "card_number": r"\b(?:\d[ -]?){13,19}\b",
}


@dataclass(frozen=True)
class Finding:
    name: str
    count: int


def scan(text: str, config: Config) -> list[Finding]:
    patterns = {**DEFAULT_PATTERNS, **config.secret_patterns}
    findings: list[Finding] = []
    for name, pattern in sorted(patterns.items()):
        hits = [
            m.group(0)
            for m in re.finditer(pattern, text)
            if m.group(0) not in config.redaction_allow
            and (name != "card_number" or _luhn_ok(m.group(0)))
        ]
        if hits:
            findings.append(Finding(name=name, count=len(hits)))
    return findings


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
