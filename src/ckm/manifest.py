"""The manifest: one row per source page, the control ledger for counts and status."""

import csv
import io
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ckm.fsio import write_text

# extracted: module written from source · curated: human-owned, never overwritten
# blocked: redaction hit, module not written · archived: page gone from the export
ROW_STATUSES = ("extracted", "curated", "blocked", "archived")


@dataclass
class ManifestRow:
    page_id: str
    title: str
    source_file: str
    source_sha256: str
    module_path: str
    status: str
    extracted: str
    note: str = ""


FIELDS = [f.name for f in fields(ManifestRow)]


def read_manifest(path: Path) -> dict[str, ManifestRow]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [ManifestRow(**row) for row in csv.DictReader(handle)]
    return {row.page_id: row for row in rows}


def write_manifest(path: Path, rows: dict[str, ManifestRow], *, dry_run: bool = False) -> bool:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for page_id in sorted(rows, key=_page_sort_key):
        writer.writerow(asdict(rows[page_id]))
    return write_text(path, buffer.getvalue(), dry_run=dry_run)


def _page_sort_key(page_id: str) -> tuple[int, str]:
    return (int(page_id), page_id) if page_id.isdigit() else (1 << 62, page_id)
