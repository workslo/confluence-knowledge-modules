"""Behaviour across runs: curation, drift, deletion upstream, redaction, limits, stable paths."""

from pathlib import Path

from conftest import TODAY

from ckm.config import Config
from ckm.extract import run_extract
from ckm.gates import run_checks
from ckm.manifest import read_manifest
from ckm.vault import Vault

LATER = "2026-11-01"


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_curated_module_is_never_overwritten_and_drift_is_flagged(
    extracted: tuple[Path, Vault],
) -> None:
    export, vault = extracted
    module = vault.wiki / "glossary.md"
    _edit(module, "status: extracted", "status: curated")
    _edit(
        module,
        "## AI READING INSTRUCTION",
        "**[SPEC]**\n- Close locks a period.\n\n## AI READING INSTRUCTION",
    )
    curated_text = module.read_text(encoding="utf-8")

    _edit(export / "100003.html", "locks a period", "closes a period")
    report = run_extract(export, vault, Config(), today=LATER)

    assert module.read_text(encoding="utf-8") == curated_text
    assert report.curated_skipped == ["100003"]
    assert read_manifest(vault.manifest)["100003"].note == "source changed since curation"
    drift = [f for f in run_checks(vault) if f.gate == "drift"]
    assert [f.severity for f in drift] == ["warning"]
    assert f"{LATER} drift wiki/glossary.md: source changed" in vault.log.read_text()


def test_page_removed_upstream_is_archived_not_deleted(extracted: tuple[Path, Vault]) -> None:
    export, vault = extracted
    (export / "100003.html").unlink()
    report = run_extract(export, vault, Config(), today=LATER)

    assert report.archived == ["100003"]
    assert not (vault.wiki / "glossary.md").exists()
    archived = (vault.archive / "glossary.md").read_text(encoding="utf-8")
    assert "> Status: Outdated" in archived
    assert f"> Reason: page no longer in the Confluence export ({LATER})" in archived
    row = read_manifest(vault.manifest)["100003"]
    assert (row.status, row.module_path) == ("archived", "archive/glossary.md")
    # Getting Started is re-converted: its link to the removed page becomes plain text and is
    # reported, rather than left dangling.
    assert "(glossary.md)" not in (vault.wiki / "getting-started.md").read_text(encoding="utf-8")
    assert report.unresolved["100001"] == ["page:100003.html"]
    assert [f.gate for f in run_checks(vault) if f.severity == "error"] == []


def test_limit_does_not_archive_unprocessed_pages(extracted: tuple[Path, Vault]) -> None:
    export, vault = extracted
    report = run_extract(export, vault, Config(), today=LATER, limit=1)
    assert report.archived == []
    assert all(r.status == "extracted" for r in read_manifest(vault.manifest).values())


def test_secret_blocks_the_page_and_fails_the_check(extracted: tuple[Path, Vault]) -> None:
    export, vault = extracted
    _edit(export / "100003.html", "locks a period.", "locks a period. password: hunter2hunter2")
    report = run_extract(export, vault, Config(), today=LATER)

    assert report.blocked == ["100003"]
    assert not (vault.wiki / "glossary.md").exists()  # the earlier clean copy is removed too
    row = read_manifest(vault.manifest)["100003"]
    assert (row.status, row.note) == ("blocked", "redaction: password_assignmentx1")
    assert "hunter2" not in (vault.root / "manifest.csv").read_text()
    assert "hunter2" not in (vault.raw / "100003.txt").read_text()  # raw keeps the clean version
    gates = {f.gate for f in run_checks(vault) if f.severity == "error"}
    # Blocked fails the check; the page linking to the withheld module also surfaces.
    assert gates == {"redaction", "links"}


def test_allow_listed_literal_does_not_block(export_copy: Path, vault: Vault) -> None:
    _edit(export_copy / "100003.html", "locks a period.", "locks a period. password: example-only")
    config = Config(redaction_allow=frozenset({"password: example-only"}))
    assert run_extract(export_copy, vault, config, today=TODAY).blocked == []


def test_attachment_names_with_spaces_link_and_pass_the_link_gate(
    export_copy: Path, vault: Vault
) -> None:
    src = export_copy / "attachments" / "100002" / "200002.pdf"
    src.rename(src.with_name("sign off v2.pdf"))
    _edit(
        export_copy / "Month-End-Procedure_100002.html",
        'href="attachments/100002/200002.pdf"',
        'href="attachments/100002/sign%20off%20v2.pdf"',
    )
    run_extract(export_copy, vault, Config(), today=TODAY)
    module = (vault.wiki / "month-end-procedure.md").read_text(encoding="utf-8")
    assert "(attachments/100002_sign%20off%20v2.pdf)" in module
    assert (vault.wiki / "attachments" / "100002_sign off v2.pdf").is_file()
    assert [f for f in run_checks(vault) if f.gate == "links"] == []
    (vault.wiki / "attachments" / "100002_sign off v2.pdf").unlink()
    assert [f.gate for f in run_checks(vault) if f.severity == "error"] == ["links"]


def test_module_path_is_stable_when_the_title_changes(extracted: tuple[Path, Vault]) -> None:
    export, vault = extracted
    _edit(export / "100003.html", "Team Space : Glossary</span>", "Team Space : Terms</span>")
    run_extract(export, vault, Config(), today=LATER)
    row = read_manifest(vault.manifest)["100003"]
    assert (row.title, row.module_path) == ("Terms", "wiki/glossary.md")
