"""Golden-file test: the fixture export must produce exactly the checked-in vault.

Regenerate after an intended output change:  UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
Review the diff of tests/golden/ like any other code change.
"""

import os
import shutil
from pathlib import Path

from conftest import EXPORT, GOLDEN, TODAY

from ckm.config import Config
from ckm.extract import run_extract
from ckm.gates import run_checks
from ckm.vault import Vault


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_fixture_export_matches_golden_vault(tmp_path: Path) -> None:
    out = Vault(tmp_path / "vault")
    run_extract(EXPORT, out, Config(), today=TODAY)
    if os.environ.get("UPDATE_GOLDEN"):
        shutil.rmtree(GOLDEN, ignore_errors=True)
        shutil.copytree(out.root, GOLDEN)
    got, want = _files(out.root), _files(GOLDEN)
    assert sorted(got) == sorted(want)
    for name in sorted(want):
        assert got[name] == want[name], f"{name} differs from golden"


def test_golden_vault_passes_every_gate() -> None:
    errors = [f for f in run_checks(Vault(GOLDEN)) if f.severity == "error"]
    assert errors == []


def test_second_run_writes_nothing(extracted: tuple[Path, Vault]) -> None:
    export, vault = extracted
    before = _files(vault.root)
    report = run_extract(export, vault, Config(), today="2030-01-01")  # later date, same source
    assert report.written == []
    assert _files(vault.root) == before


def test_dry_run_writes_nothing(export_copy: Path, vault: Vault) -> None:
    report = run_extract(export_copy, vault, Config(), today=TODAY, dry_run=True)
    assert len(report.written) == 3
    assert not vault.root.exists()
