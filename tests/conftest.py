import shutil
from pathlib import Path

import pytest

from ckm.config import Config
from ckm.extract import run_extract
from ckm.vault import Vault

FIXTURES = Path(__file__).parent / "fixtures"
EXPORT = FIXTURES / "export"
GOLDEN = Path(__file__).parent / "golden" / "vault"
TODAY = "2026-10-02"


@pytest.fixture
def export_copy(tmp_path: Path) -> Path:
    """A writable copy of the fixture export, for tests that change the source."""
    dst = tmp_path / "export"
    shutil.copytree(EXPORT, dst)
    return dst


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "vault")


@pytest.fixture
def extracted(export_copy: Path, vault: Vault) -> tuple[Path, Vault]:
    run_extract(export_copy, vault, Config(), today=TODAY)
    return export_copy, vault
