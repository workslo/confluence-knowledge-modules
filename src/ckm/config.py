"""Project configuration: one JSON file, validated at load time (fail fast)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path("config/ckm.json")


@dataclass(frozen=True)
class Config:
    # CSS classes whose elements (and children) are dropped entirely.
    skip_classes: frozenset[str] = frozenset()
    # Source filename -> corrected title, for exports with mangled titles.
    title_overrides: dict[str, str] = field(default_factory=dict)
    # Redaction: regex name -> pattern that blocks a page; allow-list of literal strings.
    secret_patterns: dict[str, str] = field(default_factory=dict)
    redaction_allow: frozenset[str] = frozenset()
    # Filenames in the export that are not content pages.
    ignore_files: frozenset[str] = frozenset()


def load_config(path: Path | None) -> Config:
    if path is None:
        path = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else None
    if path is None:
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    unknown = set(raw) - {f for f in Config.__dataclass_fields__} - {"$comment"}
    if unknown:
        raise ValueError(f"{path}: unknown config keys {sorted(unknown)}")
    return Config(
        skip_classes=frozenset(raw.get("skip_classes", [])),
        title_overrides=dict(raw.get("title_overrides", {})),
        secret_patterns=dict(raw.get("secret_patterns", {})),
        redaction_allow=frozenset(raw.get("redaction_allow", [])),
        ignore_files=frozenset(raw.get("ignore_files", [])),
    )
