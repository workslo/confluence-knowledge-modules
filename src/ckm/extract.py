"""Run one extraction: export directory -> vault (raw/, wiki/, archive/, manifest, index, log).

Idempotent: a second run over an unchanged export writes nothing. Module paths are stable
across runs (taken from the manifest once assigned). Curated modules are never overwritten.
"""

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from ckm import fsio
from ckm.config import Config
from ckm.convert import LinkResolver, convert_content
from ckm.manifest import ManifestRow, read_manifest, write_manifest
from ckm.module import ModuleMeta, render_module, split_frontmatter
from ckm.parse import Page, list_export_pages, load_page
from ckm.redact import scan
from ckm.text import slugify
from ckm.vault import Vault

ATTACHMENT_DIR = "attachments"


@dataclass
class RunReport:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    curated_skipped: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    unresolved: dict[str, list[str]] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"written={len(self.written)} unchanged={len(self.unchanged)} "
            f"curated={len(self.curated_skipped)} blocked={len(self.blocked)} "
            f"archived={len(self.archived)} pages_with_unresolved_refs={len(self.unresolved)}"
        )


def run_extract(
    export_dir: Path,
    vault: Vault,
    config: Config,
    *,
    today: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> RunReport:
    today = today or dt.date.today().isoformat()
    report = RunReport()
    previous = read_manifest(vault.manifest)
    pages = [load_page(p, config) for p in list_export_pages(export_dir, config)]
    _check_duplicate_ids(pages)
    paths = _assign_module_paths(pages, previous)
    rows: dict[str, ManifestRow] = dict(previous)

    for page in pages[:limit] if limit else pages:
        rows[page.page_id] = _process_page(
            page,
            export_dir,
            vault,
            config,
            paths,
            previous.get(page.page_id),
            today,
            dry_run,
            report,
        )

    if limit is None:  # with --limit, absent pages are just unprocessed, not removed
        seen = {p.page_id for p in pages}
        for page_id, row in sorted(previous.items()):
            if page_id not in seen and row.status != "archived":
                rows[page_id] = _archive(row, vault, today, dry_run, report)

    write_manifest(vault.manifest, rows, dry_run=dry_run)
    vault.write_index(rows, dry_run=dry_run)
    vault.append_log(report.log_lines, dry_run=dry_run)
    return report


def _check_duplicate_ids(pages: list[Page]) -> None:
    seen: dict[str, str] = {}
    for page in pages:
        if page.page_id in seen:
            raise ValueError(
                f"page id {page.page_id} appears in both {seen[page.page_id]} "
                f"and {page.source_file.name}"
            )
        seen[page.page_id] = page.source_file.name


def _assign_module_paths(pages: list[Page], previous: dict[str, ManifestRow]) -> dict[str, str]:
    """page_id -> module filename. Existing assignments win; new slugs avoid collisions."""
    paths: dict[str, str] = {}
    taken: set[str] = set()
    for page in pages:
        row = previous.get(page.page_id)
        if row and row.module_path:
            name = Path(row.module_path).name
            paths[page.page_id] = name
            taken.add(name)
    for page in pages:
        if page.page_id in paths:
            continue
        name = f"{slugify(page.title)}.md"
        if name in taken:
            name = f"{slugify(page.title)}-{page.page_id}.md"
        paths[page.page_id] = name
        taken.add(name)
    return paths


def _process_page(
    page: Page,
    export_dir: Path,
    vault: Vault,
    config: Config,
    paths: dict[str, str],
    prev: ManifestRow | None,
    today: str,
    dry_run: bool,
    report: RunReport,
) -> ManifestRow:
    source_hash = fsio.sha256_bytes(page.raw_bytes)
    module_name = paths[page.page_id]
    module_file = vault.wiki / module_name
    row = ManifestRow(
        page_id=page.page_id,
        title=page.title,
        source_file=page.source_file.name,
        source_sha256=source_hash,
        module_path=f"wiki/{module_name}",
        status="extracted",
        extracted=prev.extracted if prev and prev.source_sha256 == source_hash else today,
    )

    findings = scan(page.raw_text, config)
    if findings:
        row.status = "blocked"
        row.note = "redaction: " + ", ".join(f"{f.name}x{f.count}" for f in findings)
        report.blocked.append(page.page_id)
        if module_file.is_file() and _module_status(module_file) != "curated" and not dry_run:
            module_file.unlink()  # never leave a previously written copy of flagged content
        if not prev or prev.status != "blocked":
            report.log_lines.append(f"{today} block {page.page_id} ({row.note})")
        return row

    if module_file.is_file() and _module_status(module_file) == "curated":
        row.status = "curated"
        if prev and prev.source_sha256 != source_hash:
            row.note = "source changed since curation"
            row.extracted = prev.extracted
            report.log_lines.append(f"{today} drift {row.module_path}: source changed")
        report.curated_skipped.append(page.page_id)
        return row

    resolver = LinkResolver(page_paths=paths, attachment_dir=ATTACHMENT_DIR)
    body = convert_content(page.content, resolver)
    raw_html = vault.raw / f"{page.page_id}.html"
    raw_text = vault.raw / f"{page.page_id}.txt"
    meta = ModuleMeta(
        page_id=page.page_id,
        title=page.title,
        source_file=page.source_file.name,
        source_sha256=source_hash,
        extracted=row.extracted,
    )
    text = render_module(meta, body, [f"../raw/{raw_text.name}", f"../raw/{raw_html.name}"])

    changed = fsio.write_bytes(raw_html, page.raw_bytes, dry_run=dry_run)
    changed |= fsio.write_text(raw_text, page.raw_text, dry_run=dry_run)
    for src, out_name in sorted(resolver.assets.items()):
        source = export_dir / unquote(src.split("?", 1)[0])
        if source.is_file():
            changed |= fsio.copy_file(
                source, vault.wiki / ATTACHMENT_DIR / out_name, dry_run=dry_run
            )
        else:
            resolver.unresolved.append(f"missing-file:{src}")
    changed |= fsio.write_text(module_file, text, dry_run=dry_run)

    if resolver.unresolved:
        report.unresolved[page.page_id] = sorted(set(resolver.unresolved))
        row.note = f"unresolved refs: {len(set(resolver.unresolved))}"
    if changed:
        report.written.append(page.page_id)
        verb = "compile" if prev is None else "recompile"
        report.log_lines.append(f"{today} {verb} {row.module_path} from {page.source_file.name}")
    else:
        report.unchanged.append(page.page_id)
    return row


def _module_status(path: Path) -> str:
    front, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return str(front.get("status", ""))


def _archive(
    row: ManifestRow, vault: Vault, today: str, dry_run: bool, report: RunReport
) -> ManifestRow:
    src = vault.root / row.module_path
    dst = vault.archive / Path(row.module_path).name
    if src.is_file():
        text = src.read_text(encoding="utf-8").replace(
            "> Status: Current",
            f"> Status: Outdated\n> Reason: page no longer in the Confluence export ({today})",
            1,
        )
        fsio.write_text(dst, text, dry_run=dry_run)
        if not dry_run:
            src.unlink()
    report.archived.append(row.page_id)
    report.log_lines.append(f"{today} archive {row.module_path}: page no longer in export")
    row.status = "archived"
    row.module_path = f"archive/{dst.name}"
    row.note = f"removed from export {today}"
    return row
