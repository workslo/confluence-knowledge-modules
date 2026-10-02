"""Quality gates over a vault. `ckm check` exits non-zero on any error (or warning, --strict)."""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from ckm.manifest import read_manifest
from ckm.module import FRONTMATTER_KEYS, STATUSES, header_fields, split_frontmatter
from ckm.text import ZERO_WIDTH
from ckm.vault import Vault

_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)\)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)")
_NUMBER_RE = re.compile(r"(?<![\w.,])\d[\d.,]*%?(?![\w.,])")
_LIST_MARKER_RE = re.compile(r"^\s*\d+\.\s", re.M)
_VERSION_RE = re.compile(r"^\*\*Version \d+\.\d+\.\d+\*\*", re.M)
_BARE_TAG_RE = re.compile(r"^(?:\*?)\[(SPEC|NOTE|BUG|\?)\](?:\*?)\s*$", re.M)
_TAG_RE = re.compile(r"^\*\*\[(SPEC|NOTE|BUG|\?)\]", re.M)


@dataclass(frozen=True)
class Finding:
    severity: str  # "error" | "warning"
    gate: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity:7}] {self.gate:12} {self.path}: {self.message}"


def run_checks(vault: Vault) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_counts(vault)
    for module in sorted(vault.wiki.glob("*.md")):
        text = module.read_text(encoding="utf-8")
        rel = module.relative_to(vault.root).as_posix()
        findings += check_frontmatter(text, rel)
        findings += check_hads(text, rel)
        findings += check_links(text, module, rel)
        findings += check_zero_width(text, rel)
        findings += check_grounding(text, module, rel)
    return findings


def check_counts(vault: Vault) -> list[Finding]:
    """pages in manifest (current) == module files on disk, and every row points at a file."""
    out: list[Finding] = []
    rows = read_manifest(vault.manifest)
    if not rows:
        return [Finding("error", "counts", "manifest.csv", "manifest missing or empty")]
    current = {r.module_path for r in rows.values() if r.status in ("extracted", "curated")}
    on_disk = {p.relative_to(vault.root).as_posix() for p in vault.wiki.glob("*.md")}
    for path in sorted(current - on_disk):
        out.append(Finding("error", "counts", path, "in manifest but missing on disk"))
    for path in sorted(on_disk - current):
        out.append(Finding("error", "counts", path, "on disk but not a current manifest row"))
    for row in sorted(rows.values(), key=lambda r: r.page_id):
        if row.status == "blocked":
            out.append(Finding("error", "redaction", row.source_file, f"blocked — {row.note}"))
        elif row.note == "source changed since curation":
            out.append(Finding("warning", "drift", row.module_path, row.note))
        elif row.note.startswith("unresolved refs"):
            out.append(Finding("warning", "references", row.module_path, row.note))
    if not out:
        total = len(rows)
        held = total - len(current)
        out.append(
            Finding("info", "counts", "manifest.csv", f"{len(current)} current, {held} held")
        )
    return out


def check_frontmatter(text: str, rel: str) -> list[Finding]:
    front, _ = split_frontmatter(text)
    if not front:
        return [Finding("error", "frontmatter", rel, "missing or unparseable YAML frontmatter")]
    out = [
        Finding("error", "frontmatter", rel, f"missing key `{key}`")
        for key in FRONTMATTER_KEYS
        if key not in front
    ]
    status = front.get("status")
    if status is not None and status not in STATUSES:
        out.append(Finding("error", "frontmatter", rel, f"status `{status}` not in {STATUSES}"))
    return out


def check_hads(text: str, rel: str) -> list[Finding]:
    """HADS validity rules (the skill ships no validator). Lines count after frontmatter."""
    _, body = split_frontmatter(text)
    lines = body.lstrip("\n").split("\n")
    out: list[Finding] = []
    first = next((line for line in lines if line.strip()), "")
    if not first.startswith("# "):
        out.append(Finding("error", "hads", rel, "first line after frontmatter is not an H1"))
    if not _VERSION_RE.search("\n".join(lines[:20])):
        out.append(Finding("error", "hads", rel, "no **Version X.Y.Z** in the first 20 lines"))
    h2s = [line for line in lines if line.startswith("## ")]
    if not h2s or h2s[0].strip() != "## AI READING INSTRUCTION":
        out.append(Finding("error", "hads", rel, "AI manifest is not the first H2 section"))
    stripped = _strip_code(body)
    for match in _BARE_TAG_RE.finditer(stripped):
        if not match.group(0).startswith("**"):
            out.append(Finding("error", "hads", rel, f"block tag `{match.group(0)}` must be bold"))
    for block in _blocks_of(stripped, "BUG"):
        lowered = block.lower()
        if "symptom" not in lowered or "fix" not in lowered:
            out.append(Finding("error", "hads", rel, "[BUG] block needs a symptom and a fix"))
    return out


def check_links(text: str, module: Path, rel: str) -> list[Finding]:
    out: list[Finding] = []
    for _label, target in _LINK_RE.findall(_strip_code(text, inline=True)):
        path = unquote(target.split("#", 1)[0])
        if not path or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (module.parent / path).resolve().exists():
            out.append(Finding("error", "links", rel, f"link to `{target}` does not resolve"))
    return out


def check_zero_width(text: str, rel: str) -> list[Finding]:
    count = sum(text.count(ch) for ch in ZERO_WIDTH)
    return [Finding("error", "zero-width", rel, f"{count} zero-width characters")] if count else []


def check_grounding(text: str, module: Path, rel: str) -> list[Finding]:
    """Every number in the module body appears, as a whole token, in a `> Raw:` source."""
    sources = [
        module.parent / target
        for _label, target in _LINK_RE.findall(header_fields(text).get("Raw", ""))
    ]
    readable = [s for s in sources if s.is_file()]
    if not readable:
        return [Finding("error", "grounding", rel, "no readable `> Raw:` source")]
    corpus = "\n".join(s.read_text(encoding="utf-8", errors="replace") for s in readable)
    out: list[Finding] = []
    for number in sorted(set(_NUMBER_RE.findall(_claim_text(text)))):
        token = re.compile(r"(?<![\w.,])" + re.escape(number) + r"(?![\w.,])")
        if not token.search(corpus):
            out.append(Finding("error", "grounding", rel, f"`{number}` not found in raw sources"))
    return out


def _claim_text(text: str) -> str:
    """Body after the AI manifest, minus link targets, images, and generated list markers."""
    _, body = split_frontmatter(text)
    # Everything up to and including the manifest paragraph is generated, not a claim.
    manifest = re.search(r"^## AI READING INSTRUCTION\n+(?:[^\n]+\n)*", body, re.M)
    after = body[manifest.end() :] if manifest else body
    for block in _blocks_of(after, "?"):  # [?] blocks are explicitly unverified, not claims
        after = after.replace(block, " ", 1)
    after = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", after)  # images: alt text may be a filename
    after = re.sub(r"\[image unavailable:[^\]]*\]", " ", after)
    after = _LINK_RE.sub(lambda m: f" {m.group(1)} ", after)
    after = _LIST_MARKER_RE.sub(" ", after)
    return re.sub(r"^#+\s", "", after, flags=re.M)


def _strip_code(text: str, *, inline: bool = False) -> str:
    """Drop fenced blocks (and optionally inline code), as the repo's gardener does."""
    kept: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        match = _FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
            else:
                kept.append(_INLINE_CODE_RE.sub("", line) if inline else line)
            continue
        run = line.strip()
        if match and set(run) == {fence[0]} and len(run) >= len(fence):
            fence = None
    return "\n".join(kept)


def _blocks_of(text: str, tag: str) -> list[str]:
    """Text of each HADS block with the given tag, up to the next tag or heading."""
    blocks: list[str] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"**[{tag}]"):
            block = [line]
            for nxt in lines[i + 1 :]:
                if _TAG_RE.match(nxt) or nxt.startswith("#"):
                    break
                block.append(nxt)
            blocks.append("\n".join(block))
    return blocks
