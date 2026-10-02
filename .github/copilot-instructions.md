# confluence-knowledge-modules

Converts a Confluence HTML export into Markdown knowledge modules for agents and people.
Python 3.12, `uv`, `ruff`, `pytest`. Code in `src/ckm/`, tests in `tests/`.

## Commands

- `uv run ckm extract --export <export-dir> --vault <vault-dir> [--dry-run] [--limit N]`
- `uv run ckm check --vault <vault-dir> [--strict]`
- `uv run ckm pilot --questions eval/questions.csv --answers eval/answers.csv`
- `uv run pytest` · `uv run --with ruff ruff check src tests`

## Rules for the vault

- `raw/` holds source snapshots and is never edited. Snapshots, not URLs.
- Modules live in `wiki/`. Each opens with frontmatter, the grounded-vault header
  (Raw / Fingerprint / Status), a HADS version line, and the AI reading manifest.
- Every number in a module must appear in one of its `> Raw:` sources (`ckm check` enforces it).
  Missing evidence goes in a `**[?]**` block — never a guess.
- To hand-edit a module, set `status: curated` first. The extractor then never overwrites it
  and reports drift when the source changes.
- Pages that leave the export move to `archive/` with a reason; `log.md` gets one line per change.
- A redaction hit blocks the page. Fix the source or allow-list the literal in `config/ckm.json`;
  never weaken a pattern to get a page through.
- Run `ckm check` before committing vault changes. A failing gate blocks the commit.

## Rules for the code

- Walk `children` in document order; never `find_all("p")` (it loses ordering).
- Output must be byte-stable: a second run over an unchanged export writes nothing.
- A converter change that alters output updates `tests/golden/` in the same commit
  (`UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py`); review that diff like code.
- Every new gate gets a test that makes it fail.

## Skills

| When you are… | Load skill |
|---|---|
| writing or converting a module | `hads`, `grounded-vault` |
| changing the extractor | `python-error-handling`, `python-type-safety`, `python-project-structure` |
| adding logs or run reports | `python-observability` |
| writing tests | `python-testing-patterns` |
| touching settings or secrets | `python-configuration` |
