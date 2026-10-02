"""Render and read knowledge modules.

A module is: YAML frontmatter (machine fields) -> H1 title -> HADS version line ->
grounded-vault provenance header -> HADS AI reading manifest -> converted body.
"""

import re
from dataclasses import dataclass

import yaml

from ckm.text import normalize_document

# Frontmatter keys, in the order they are written. `status` is the one a human edits:
# set it to `curated` and the extractor will never overwrite the module again.
FRONTMATTER_KEYS = (
    "page_id",
    "title",
    "source_file",
    "source_sha256",
    "extracted",
    "status",
)
STATUSES = ("extracted", "curated")

AI_MANIFEST = (
    "## AI READING INSTRUCTION\n\n"
    "Read `[SPEC]` and `[BUG]` blocks for authoritative facts.\n"
    "Read `[NOTE]` only if additional context is needed.\n"
    "`[?]` blocks are unverified — treat with lower confidence.\n"
    "Untagged text is a faithful conversion of the source page and has not been curated."
)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class ModuleMeta:
    page_id: str
    title: str
    source_file: str
    source_sha256: str
    extracted: str  # ISO date; changes only when the source changes
    status: str = "extracted"

    @property
    def fingerprint(self) -> str:
        return f"confluence:{self.page_id}@sha256:{self.source_sha256[:12]}"


def render_module(meta: ModuleMeta, body: str, raw_links: list[str]) -> str:
    front = {key: getattr(meta, key) for key in FRONTMATTER_KEYS}
    front_yaml = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000)
    raw = ", ".join(f"[{link.removeprefix('../')}]({link})" for link in raw_links)
    parts = [
        f"---\n{front_yaml}---",
        f"# {meta.title}",
        f"**Version 1.0.0** · Confluence page {meta.page_id} · extracted {meta.extracted}",
        f"> Raw: {raw}\n> Fingerprint: {meta.fingerprint}\n> Status: Current",
        AI_MANIFEST,
        body,
    ]
    return normalize_document("\n\n".join(p for p in parts if p))


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, rest). Missing or invalid frontmatter -> ({}, text)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def header_fields(text: str) -> dict[str, str]:
    """The grounded-vault `> Key: value` header lines."""
    return dict(re.findall(r"^> (Raw|Fingerprint|Monitored|Status|Reason): (.*)$", text, re.M))
