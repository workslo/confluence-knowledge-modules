"""Read one page of a Confluence HTML export: id, title, content root, raw text."""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ckm.config import Config
from ckm.text import clean_inline

# Export filenames look like `Page-Title_123456.html` or plain `123456.html`.
_PAGE_ID_RE = re.compile(r"(?:^|_)(\d{3,})\.html?$")
# The export prefixes titles with "Space Name : ".
_SPACE_PREFIX_RE = re.compile(r"^.+?\s:\s+")

# Chrome around the content that is never part of a page's knowledge.
DEFAULT_SKIP_CLASSES = frozenset(
    {
        "page-metadata",
        "pageSection",
        "breadcrumb-section",
        "toc-macro",
        "expand-control-icon",
        "confluence-information-macro-icon",
        "aui-icon",
    }
)
DEFAULT_IGNORE_FILES = frozenset({"index.html"})


@dataclass(frozen=True)
class Page:
    page_id: str
    title: str
    source_file: Path
    content: Tag
    raw_bytes: bytes

    @property
    def raw_text(self) -> str:
        """Deterministic plain text of the page body; the grounding source for its module."""
        lines = (clean_inline(s).strip() for s in self.content.stripped_strings)
        return "\n".join(line for line in lines if line) + "\n"


def page_id_from_filename(name: str) -> str | None:
    match = _PAGE_ID_RE.search(name)
    return match.group(1) if match else None


def list_export_pages(export_dir: Path, config: Config) -> list[Path]:
    ignore = DEFAULT_IGNORE_FILES | config.ignore_files
    return sorted(
        p
        for p in export_dir.glob("*.htm*")
        if p.name not in ignore and page_id_from_filename(p.name) is not None
    )


def load_page(path: Path, config: Config) -> Page:
    raw = path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    page_id = page_id_from_filename(path.name)
    if page_id is None:
        raise ValueError(f"{path.name}: no page id in filename")
    content = soup.find(id="main-content") or soup.find(id="content") or soup.body
    if not isinstance(content, Tag):
        raise ValueError(f"{path.name}: no content element")
    _drop_skipped(content, DEFAULT_SKIP_CLASSES | config.skip_classes)
    return Page(
        page_id=page_id,
        title=_title(soup, path, config),
        source_file=path,
        content=content,
        raw_bytes=raw,
    )


def _title(soup: BeautifulSoup, path: Path, config: Config) -> str:
    if path.name in config.title_overrides:
        return config.title_overrides[path.name]
    node = soup.find(id="title-text") or soup.find("title")
    title = clean_inline(node.get_text()).strip() if node else ""
    title = _SPACE_PREFIX_RE.sub("", title, count=1) if " : " in title else title
    return title or path.stem


def _drop_skipped(root: Tag, skip_classes: frozenset[str]) -> None:
    for tag in root.find_all(["script", "style", "colgroup"]):
        tag.decompose()
    for tag in root.find_all(class_=True):
        if tag.decomposed:
            continue
        if skip_classes.intersection(tag.get("class") or []):
            tag.decompose()
