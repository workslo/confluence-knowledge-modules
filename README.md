# confluence-knowledge-modules

Turn a Confluence **HTML export** into Markdown **knowledge modules** that agents (GitHub Copilot)
and people can both use — with provenance, quality gates, and a way to prove retrieval works.

> **Status:** starter, v0.1.0 · 46 tests · tested on Linux with Python 3.12 (Windows not yet run)

---

## Quick start

```bash
uv sync
uv run ckm extract --export path/to/html-export --vault vault --dry-run   # see what would change
uv run ckm extract --export path/to/html-export --vault vault
uv run ckm check   --vault vault                                          # gates; exit 1 on error
```

Export from Confluence: *Space settings → Export space → HTML*. Unzip; point `--export` at the
folder that holds the `*.html` pages and `attachments/`.

---

## What you get

```text
vault/
├── raw/            source snapshots — <page_id>.html (as exported) + <page_id>.txt (plain text)
├── wiki/           one module per page — <slug>.md
│   └── attachments/  images and files, renamed <page_id>_<file>
├── archive/        modules whose page left the export (moved, never deleted)
├── manifest.csv    one row per page: id, title, source hash, module path, status, note
├── index.md        map of current modules (generated)
└── log.md          append-only: compile / recompile / drift / block / archive
```

Each module:

```markdown
---
page_id: '100002'
title: Month-End Procedure
source_file: Month-End-Procedure_100002.html
source_sha256: db25f80…
extracted: '2026-10-02'
status: extracted          # set to `curated` to take ownership; the extractor stops overwriting
---

# Month-End Procedure

**Version 1.0.0** · Confluence page 100002 · extracted 2026-10-02

> Raw: [raw/100002.txt](../raw/100002.txt), [raw/100002.html](../raw/100002.html)
> Fingerprint: confluence:100002@sha256:db25f8076a49
> Status: Current

## AI READING INSTRUCTION
…
```

See `tests/golden/vault/` for a complete example built from `tests/fixtures/export/`.

---

## Workflow

| Step | Command / action | Notes |
|---|---|---|
| 1 Extract | `ckm extract` | Idempotent: an unchanged export writes nothing. Paths stay stable across runs. |
| 2 Check | `ckm check` | Fix every error before committing the vault. `--strict` also fails on warnings. |
| 3 Curate | set `status: curated`, then edit | Add HADS `**[SPEC]**` / `**[BUG]**` blocks; unverified material goes in `**[?]**`. |
| 4 Re-export | `ckm extract` again | Changed pages recompile; curated pages report **drift** instead; removed pages archive. |
| 5 Pilot | `ckm pilot` | 20–30 real questions → citation hit-rate and "said unknown when it should". |

---

## Quality gates (`ckm check`)

| Gate | Fails when | Severity |
|---|---|---|
| counts | manifest current rows ≠ module files on disk (either direction) | error |
| redaction | a page was blocked by the secret / PII scan | error |
| frontmatter | missing key, unknown `status` | error |
| hads | no H1, no `**Version X.Y.Z**` in first 20 lines, manifest not first H2, unbold tag, `[BUG]` without symptom + fix | error |
| links | a relative link or image doesn't resolve (code is ignored) | error |
| zero-width | any zero-width character left in a module | error |
| grounding | a number in a module isn't in its `> Raw:` sources (`[?]` blocks exempt) | error |
| drift | a curated module's source changed since curation | warning |
| references | the converter couldn't resolve a page/attachment link | warning |

Every gate has a test that makes it fail (`tests/test_gates.py`).

---

## Redaction (fails closed)

Every page is scanned before anything is written. A hit means: no module, no raw copy of the new
version, an existing generated module is removed, and the manifest records `blocked` with the
pattern names (never the matched text). Built-in patterns: private keys, AWS keys, GitHub and Slack
tokens, JWTs, `password=`-style assignments, US SSNs, Luhn-valid card numbers.

Add patterns or allow-list a known-safe literal in `config/ckm.json`.

---

## Configuration (`config/ckm.json`)

| Key | Purpose |
|---|---|
| `skip_classes` | extra CSS classes to drop (built-in: page metadata, attachments footer, TOC, breadcrumbs, icons) |
| `ignore_files` | export files that aren't pages (built-in: `index.html`) |
| `title_overrides` | `{"Source-File_123.html": "Correct Title"}` for exports with mangled titles |
| `secret_patterns` | `{"name": "regex"}` added to the built-in patterns |
| `redaction_allow` | literal strings that never block a page |

Unknown keys are rejected at load time.

---

## Converter coverage

| Confluence element | Becomes |
|---|---|
| Headings | Shifted down one level (the module H1 is the page title) |
| Paragraphs, bold, italic, strike, inline code | Markdown equivalents |
| Lists (nested, ordered/unordered) | CommonMark lists indented to the parent's content column |
| Tables (`table-wrap`) | GFM tables; `\|` escaped; multi-paragraph cells joined with `<br>`; no invented header text |
| Code macro | Fenced block with the macro's language |
| Info / note / tip / warning panels | `**[NOTE]**` block with a label |
| Expand macro | Bold title + content |
| Status lozenge | `` `STATUS` `` |
| Page links | Relative links between modules; unknown pages → plain text + warning |
| Images and attachments | Copied to `wiki/attachments/<page_id>_<file>` and linked |
| TOC macro, page metadata, attachments footer | Dropped |

**Not yet handled** (falls back to plain text): Jira macros, include/excerpt macros, page-properties
reports, multi-column layouts, merged table cells (`rowspan`/`colspan`), comments.

---

## Design choices and where they come from

| Choice | Source |
|---|---|
| `raw/` · `wiki/` · `archive/` · `index.md` · `log.md`; per-module provenance header | `grounded-vault` skill |
| Fingerprint = page id + source hash (exports carry no version number) | adapted from grounded-vault's git fingerprint |
| `**[SPEC]**` / `**[NOTE]**` / `**[BUG]**` / `**[?]**` + AI reading manifest | `hads` skill |
| HADS validator in `ckm check` | `hads` ships none; rules from its validation section |
| Walk `children`, never `find_all`; copy-alongside images; manifest as control ledger; `--dry-run` + `--limit` | prior Confluence → SharePoint project |
| Fail-closed redaction, log what was dropped | `trace-to-training-data` skill (policy) |
| Golden-file tests | gap in the marketplace; built here |

Skill copies live in `.github/skills/` (see `SOURCES.md`); Copilot instructions in
`.github/copilot-instructions.md`.

---

## Development

```bash
uv run pytest                                             # 46 tests
uv run --with ruff ruff check src tests && uv run --with ruff ruff format --check src tests
UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py        # after an intended output change
```
