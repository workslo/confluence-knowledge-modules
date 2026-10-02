"""Each gate must fail on the defect it exists for. A gate that can't fail isn't a gate."""

from pathlib import Path

import pytest

from ckm.gates import run_checks
from ckm.vault import Vault


def errors(vault: Vault, gate: str) -> list[str]:
    return [f.message for f in run_checks(vault) if f.severity == "error" and f.gate == gate]


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture text not found: {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture
def v(extracted: tuple[Path, Vault]) -> Vault:
    return extracted[1]


def test_clean_vault_has_no_errors(v: Vault) -> None:
    assert [f for f in run_checks(v) if f.severity == "error"] == []


def test_grounding_catches_an_invented_number(v: Vault) -> None:
    edit(v.wiki / "glossary.md", "above 0.5%", "above 0.7%")
    assert errors(v, "grounding") == ["`0.7%` not found in raw sources"]


def test_grounding_exempts_unverified_blocks_only(v: Vault) -> None:
    page = v.wiki / "glossary.md"
    base = page.read_text(encoding="utf-8")
    page.write_text(base + "\n**[?]**\nPossibly 0.9% next year.\n", encoding="utf-8")
    assert errors(v, "grounding") == []
    page.write_text(base + "\nPossibly 0.9% next year.\n", encoding="utf-8")
    assert errors(v, "grounding") == ["`0.9%` not found in raw sources"]


def test_grounding_ignores_link_targets_and_list_markers(v: Vault) -> None:
    assert errors(v, "grounding") == []  # attachments/100001_200001.png and "1." are not claims


def test_dead_link_is_caught(v: Vault) -> None:
    edit(v.wiki / "getting-started.md", "(glossary.md)", "(glosary.md)")
    assert errors(v, "links") == ["link to `glosary.md` does not resolve"]


def test_missing_attachment_is_caught(v: Vault) -> None:
    (v.wiki / "attachments" / "100001_200001.png").unlink()
    assert errors(v, "links") == ["link to `attachments/100001_200001.png` does not resolve"]


def test_frontmatter_schema(v: Vault) -> None:
    edit(v.wiki / "glossary.md", "status: extracted", "status: draft")
    assert errors(v, "frontmatter") == ["status `draft` not in ('extracted', 'curated')"]


def test_hads_version_manifest_and_bold_tags(v: Vault) -> None:
    page = v.wiki / "glossary.md"
    edit(page, "**Version 1.0.0**", "Version 1.0.0")
    edit(page, "## AI READING INSTRUCTION", "## Reading notes")
    page.write_text(page.read_text(encoding="utf-8") + "\n[SPEC]\nA fact.\n", encoding="utf-8")
    assert set(errors(v, "hads")) == {
        "no **Version X.Y.Z** in the first 20 lines",
        "AI manifest is not the first H2 section",
        "block tag `[SPEC]` must be bold",
    }


def test_hads_bug_block_needs_symptom_and_fix(v: Vault) -> None:
    page = v.wiki / "glossary.md"
    page.write_text(
        page.read_text(encoding="utf-8") + "\n**[BUG]**\nIt breaks.\n", encoding="utf-8"
    )
    assert errors(v, "hads") == ["[BUG] block needs a symptom and a fix"]


def test_zero_width_is_caught(v: Vault) -> None:
    edit(v.wiki / "glossary.md", "Close", "Clo\u200bse")
    assert errors(v, "zero-width") == ["1 zero-width characters"]


def test_count_mismatch_both_directions(v: Vault) -> None:
    (v.wiki / "glossary.md").rename(v.wiki / "stray.md")
    assert set(errors(v, "counts")) == {
        "in manifest but missing on disk",
        "on disk but not a current manifest row",
    }
