"""Text normalisation shared by the converter, the raw-text extractor, and the gates."""

import re
import unicodedata

ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
_ZERO_WIDTH_RE = re.compile(f"[{ZERO_WIDTH}]")
_SPACES_RE = re.compile(r"[ \t\u00a0\u2007\u202f]+")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def clean_inline(text: str) -> str:
    """Strip zero-width characters and collapse runs of spaces (incl. non-breaking)."""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return _SPACES_RE.sub(" ", text)


def normalize_document(text: str) -> str:
    """Make output byte-stable: LF endings, no trailing spaces, <=1 blank line, one final LF."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip("\n")
    return text + "\n"


def slugify(title: str) -> str:
    """Lowercase kebab-case, ASCII only; never empty."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "untitled"
