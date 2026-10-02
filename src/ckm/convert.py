"""Convert a Confluence export content tree to Markdown.

Walks `children` in document order (never `find_all`), dispatching on tag name and class.
Links and attachments go through a `LinkResolver` so this module never touches the disk.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

from bs4 import NavigableString, Tag
from bs4.element import Comment

from ckm.text import clean_inline

BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "ul", "ol", "table", "pre", "blockquote", "hr"}
    | {f"h{n}" for n in range(1, 7)}
)
_BRUSH_RE = re.compile(r"brush:\s*([\w+#-]+)")
_PANEL_RE = re.compile(r"confluence-information-macro-(information|note|warning|tip)")
_ATTACHMENT_RE = re.compile(r"(?:^|/)attachments/(\d+)/([^/?#]+)")
_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]])")


@dataclass
class LinkResolver:
    """Maps export-relative references to module-relative ones and records what it saw."""

    page_paths: dict[str, str]  # page_id -> module path relative to the module being written
    attachment_dir: str  # e.g. "attachments" — where copied files live, relative to modules
    assets: dict[str, str] = field(default_factory=dict)  # export href -> output filename
    unresolved: list[str] = field(default_factory=list)

    def page_link(self, href: str, page_id: str | None) -> str | None:
        if page_id and page_id in self.page_paths:
            return self.page_paths[page_id]
        from ckm.parse import page_id_from_filename  # local import avoids a cycle

        guessed = page_id_from_filename(href.split("#", 1)[0])
        if guessed and guessed in self.page_paths:
            return self.page_paths[guessed]
        return None

    def attachment(self, src: str) -> str | None:
        match = _ATTACHMENT_RE.search(unquote(src))
        if not match:
            return None
        owner, name = match.groups()
        out_name = f"{owner}_{name}"
        self.assets[src] = out_name
        # The file keeps its real name; the link target is URL-encoded so spaces etc. survive.
        return f"{self.attachment_dir}/{quote(out_name)}"


def convert_content(root: Tag, resolver: LinkResolver) -> str:
    return _Converter(resolver).blocks(root)


class _Converter:
    def __init__(self, resolver: LinkResolver) -> None:
        self.r = resolver

    # ---- blocks -------------------------------------------------------------

    def blocks(self, node: Tag) -> str:
        out: list[str] = []
        inline_run: list[str] = []

        def flush() -> None:
            text = "".join(inline_run).strip()
            if text:
                out.append(text)
            inline_run.clear()

        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                inline_run.append(clean_inline(str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in BLOCK_TAGS or self._is_block_macro(child):
                flush()
                block = self.block(child)
                if block:
                    out.append(block)
            elif child.name == "br":
                inline_run.append("\n")
            else:
                inline_run.append(self.inline(child))
        flush()
        return "\n\n".join(b for b in out if b.strip())

    def block(self, tag: Tag) -> str:
        name = tag.name
        classes = set(tag.get("class") or [])
        if name and re.fullmatch(r"h[1-6]", name):
            # The module H1 is the page title, so content headings shift down one level.
            level = min(int(name[1]) + 1, 6)
            return f"{'#' * level} {self.inline_children(tag).strip()}"
        if name == "p":
            return self.inline_children(tag).strip()
        if name in ("ul", "ol"):
            return self.list_block(tag, indent="")
        if name == "table":
            return self.table(tag)
        if name == "pre":
            return self.code(tag)
        if name == "blockquote":
            inner = self.blocks(tag)
            return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        if name == "hr":
            return "---"
        if "code" in classes and "panel" in classes:
            pre = tag.find("pre")
            return self.code(pre) if isinstance(pre, Tag) else self.blocks(tag)
        panel = self._panel_kind(classes)
        if panel:
            return self.panel(tag, panel)
        if "expand-container" in classes:
            return self.expand(tag)
        return self.blocks(tag)  # generic wrapper div

    def _is_block_macro(self, tag: Tag) -> bool:
        classes = set(tag.get("class") or [])
        return bool(classes & {"expand-container", "table-wrap", "code"}) or bool(
            self._panel_kind(classes)
        )

    @staticmethod
    def _panel_kind(classes: set[str]) -> str | None:
        for cls in classes:
            match = _PANEL_RE.fullmatch(cls)
            if match:
                return match.group(1)
        return None

    def panel(self, tag: Tag, kind: str) -> str:
        body = tag.find(class_="confluence-information-macro-body")
        inner = self.blocks(body if isinstance(body, Tag) else tag)
        label = {"warning": "Warning", "note": "Note", "tip": "Tip", "information": "Info"}[kind]
        # HADS: a [NOTE] block is human context; the tag sits on its own line, content follows.
        return f"**[NOTE]**\n**{label}:** {inner}"

    def expand(self, tag: Tag) -> str:
        control = tag.find(class_="expand-control-text")
        content = tag.find(class_="expand-content")
        title = self.inline_children(control).strip() if isinstance(control, Tag) else ""
        inner = self.blocks(content) if isinstance(content, Tag) else ""
        return f"**{title}**\n\n{inner}" if title else inner

    def code(self, pre: Tag) -> str:
        params = str(pre.get("data-syntaxhighlighter-params") or "")
        match = _BRUSH_RE.search(params)
        lang = match.group(1) if match else ""
        lang = "" if lang in {"plain", "text", "none"} else lang
        body = pre.get_text().replace("\r\n", "\n").strip("\n")
        fence = "````" if "```" in body else "```"
        return f"{fence}{lang}\n{body}\n{fence}"

    def list_block(self, tag: Tag, indent: str) -> str:
        """Nested items are indented to the parent item's content column (CommonMark)."""
        ordered = tag.name == "ol"
        lines: list[str] = []
        for index, li in enumerate(tag.find_all("li", recursive=False), start=1):
            marker = f"{index}." if ordered else "-"
            child_indent = indent + " " * (len(marker) + 1)
            text_parts: list[str] = []
            nested: list[str] = []
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    nested.append(self.list_block(child, child_indent))
                elif isinstance(child, Tag) and child.name in BLOCK_TAGS:
                    text_parts.append(" " + self.block(child).replace("\n", " "))
                elif isinstance(child, NavigableString) and not isinstance(child, Comment):
                    text_parts.append(clean_inline(str(child)))
                elif isinstance(child, Tag):
                    text_parts.append(self.inline(child))
            text = re.sub(r"\s+", " ", "".join(text_parts)).strip()
            lines.append(f"{indent}{marker} {text}".rstrip())
            lines.extend(nested)
        return "\n".join(lines)

    def table(self, tag: Tag) -> str:
        rows: list[list[str]] = []
        header_row = False
        for i, tr in enumerate(tag.find_all("tr")):
            if tr.find_parent("table") is not tag:
                continue  # nested tables are flattened into their cell text
            cells = tr.find_all(["th", "td"], recursive=False)
            if i == 0 and cells and all(c.name == "th" for c in cells):
                header_row = True
            rows.append([self.cell(c) for c in cells])
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        if not header_row:
            rows.insert(0, [""] * width)  # GFM needs a header row; keep it empty, not invented
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def cell(self, cell: Tag) -> str:
        text = self.blocks(cell)
        text = text.replace("\n\n", "<br>").replace("\n", "<br>")
        return text.replace("|", "\\|").strip()

    # ---- inline -------------------------------------------------------------

    def inline_children(self, tag: Tag) -> str:
        parts: list[str] = []
        for child in tag.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                parts.append(clean_inline(str(child)))
            elif isinstance(child, Tag):
                parts.append(self.inline(child))
        return "".join(parts)

    def inline(self, tag: Tag) -> str:
        name = tag.name
        classes = set(tag.get("class") or [])
        if name == "br":
            return "\n"
        if name == "img":
            return self.image(tag)
        if name == "a":
            return self.link(tag)
        if name in ("strong", "b"):
            return self._wrap(self.inline_children(tag), "**")
        if name in ("em", "i"):
            return self._wrap(self.inline_children(tag), "*")
        if name in ("s", "del", "strike"):
            return self._wrap(self.inline_children(tag), "~~")
        if name == "code":
            text = tag.get_text()
            return f"`{text}`" if text else ""
        if "status-macro" in classes:
            return f"`{tag.get_text().strip()}`"
        if name in BLOCK_TAGS:
            return " " + self.block(tag).replace("\n", " ") + " "
        # span/u/sub/sup and any unknown inline tag: keep the text, drop the markup.
        return self.inline_children(tag)

    @staticmethod
    def _wrap(text: str, marker: str) -> str:
        stripped = text.strip()
        if not stripped:
            return text
        lead = text[: len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()) :]
        return f"{lead}{marker}{stripped}{marker}{trail}"

    def image(self, tag: Tag) -> str:
        src = str(tag.get("data-image-src") or tag.get("src") or "")
        alt = clean_inline(str(tag.get("alt") or "")).strip()
        target = self.r.attachment(src)
        if target is None:
            if src.startswith(("http://", "https://")):
                return f"![{_escape(alt)}]({src})"
            self.r.unresolved.append(f"image:{src}")
            return f"[image unavailable: {_escape(alt or src)}]"
        return f"![{_escape(alt or unquote(target).rsplit('_', 1)[-1])}]({target})"

    def link(self, tag: Tag) -> str:
        href = str(tag.get("href") or "")
        text = self.inline_children(tag).strip()
        if not href:
            return text
        if href.startswith("#"):
            return text  # same-page anchors don't survive module splitting
        rtype = tag.get("data-linked-resource-type")
        is_local_html = href.split("#", 1)[0].endswith((".html", ".htm")) and "://" not in href
        if rtype == "page" or is_local_html:
            target = self.r.page_link(href, tag.get("data-linked-resource-id"))
            if target is None:
                self.r.unresolved.append(f"page:{href}")
                return text
            return f"[{text or target}]({target})"
        attachment = self.r.attachment(href)
        if attachment is not None:
            return f"[{text or unquote(attachment).rsplit('_', 1)[-1]}]({attachment})"
        if href.startswith(("http://", "https://", "mailto:")):
            return f"[{text}]({href})" if text and text != href else f"<{href}>"
        self.r.unresolved.append(f"link:{href}")
        return text


def _escape(text: str) -> str:
    return _MD_ESCAPE_RE.sub(r"\\\1", text)
